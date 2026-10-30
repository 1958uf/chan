"""FastAPI入口：导入不写数据库、不联网，资源在lifespan内初始化。"""
import ipaddress
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .api.shares_routes import shares_router
from .config import ROOT, Settings, default_etfs
from .demo import DEMO_NOW, DemoProvider, seed_demo
from .services import TaskManager
from .storage import Repository


def local_host(host):
    """功能：验证环回主机；输入：主机名/IP；输出：是否本机。"""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def safe_origin(origin, settings, request=None):
    """功能：校验本机白名单或同源Origin；输入：Origin和请求；输出：是否允许。"""
    try:
        parsed = urlsplit(origin)
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return False
        if parsed.scheme not in ("http", "https") or not local_host(parsed.hostname) or parsed.hostname == "testclient" or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return False
        if origin in settings.allowed_origins:
            return True
        if request and local_host(request.url.hostname):
            return origin == f"{request.url.scheme}://{request.url.netloc}"
        return False
    except ValueError:
        return False


def create_app(settings: Settings | None = None, provider=None, clock=None):
    """功能：创建可注入应用；输入：配置、provider、固定时钟；输出：无I/O的FastAPI。"""
    selected = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        """功能：管理仓储与worker生命周期；输入：应用；输出：已初始化服务。"""
        app.state.settings = selected.model_copy(deep=True)
        if clock is not None:
            app.state.clock = clock
        elif selected.mode == "demo":
            app.state.clock = lambda: DEMO_NOW
        else:
            app.state.clock = lambda: datetime.now(ZoneInfo("Asia/Shanghai"))
        app.state.token = selected.token or secrets.token_urlsafe(32)
        app.state.repository = Repository(selected.data_dir / ("demo.sqlite" if selected.mode == "demo" else "live.sqlite"))
        app.state.repository.initialize()
        if not app.state.repository.etfs():
            app.state.repository.put_etfs(default_etfs())
        saved = app.state.repository.document("metadata", "settings")
        if saved:
            app.state.settings = Settings.model_validate({**app.state.settings.model_dump(), **saved})
        if selected.mode == "demo":
            app.state.settings.scheduler_enabled = False
            seed_demo(app.state.repository, app.state.repository.etfs())
        if provider is not None:
            app.state.provider = provider
        elif selected.mode == "demo":
            app.state.provider = DemoProvider(app.state.settings)
        else:
            from .providers import LiveProvider
            app.state.provider = LiveProvider(app.state.settings)
        app.state.tasks = TaskManager(app.state.repository, app.state.provider, app.state.settings, app.state.clock)
        app.state.tasks.start()
        try:
            yield
        finally:
            app.state.tasks.close()

    app = FastAPI(title="独立ETF监控", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def security(request: Request, call_next):
        """功能：校验本机文档、Origin和所有变更令牌；输入：请求；输出：安全响应。"""
        host = request.url.hostname
        client = request.client.host if request.client else None
        if not local_host(host):
            return JSONResponse({"detail": "仅接受localhost Host，防止DNS重绑定"}, status_code=403)
        local_only = request.url.path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/api/session")
        local_client = local_host(client) or client == "testclient" and "http.response.debug" in request.scope.get("extensions", {})
        if local_only and not local_client:
            return JSONResponse({"detail": "会话与文档仅限本机访问"}, status_code=403)
        settings_now = getattr(app.state, "settings", selected)
        origin = request.headers.get("origin")
        if origin and not safe_origin(origin, settings_now, request):
            return JSONResponse({"detail": "Origin不在本机同源白名单"}, status_code=403)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not local_client or not origin or not safe_origin(origin, settings_now, request):
                return JSONResponse({"detail": "变更请求必须来自本机并携带可信Origin"}, status_code=403)
            supplied = request.headers.get("x-etf-token", "")
            expected = getattr(app.state, "token", "")
            if not supplied or not expected or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                return JSONResponse({"detail": "缺少或错误X-ETF-Token"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path == "/api/session":
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
    app.include_router(shares_router)
    dist = ROOT / "frontend" / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
