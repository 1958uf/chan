"""有界传输与隔离调用。接口名称参考MIT许可AKShare文档，未复制其实现。"""
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .base import ProviderError


class BoundedHTTP:
    """固定超时、有限次数、非重试性错误快速失败的HTTP客户端。"""

    def __init__(self, settings, *, client=None, sleeper=time.sleep):
        """功能：创建客户端；输入：Settings和可注入mock；输出：有界HTTP实例。"""
        self.timeout = settings.request_timeout
        self.retries = settings.max_retries
        self.client = client or httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"})
        self.sleeper = sleeper
        self.clock = time.monotonic
        self.max_bytes = 32 * 1024 * 1024
        self.failures = {}

    def _response(self, source, url, params, headers, deadline):
        """功能：流式限制体积和墙钟预算；输入：截止时刻；输出：已验证响应。"""
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise ProviderError(source, "请求总时间预算已耗尽", retryable=True)
        with self.client.stream("GET", url, params=params, headers=headers, timeout=min(self.timeout, remaining)) as streamed:
            streamed.raise_for_status()
            content = bytearray()
            # 不指定大块聚合：每次原始网络读取都检查总时限，防止连续慢流无限拖延。
            for chunk in streamed.iter_bytes():
                if self.clock() >= deadline:
                    raise ProviderError(source, "流式响应超过总时间预算", retryable=True)
                if len(content) + len(chunk) > self.max_bytes:
                    raise ProviderError(source, "响应超过32MiB上限")
                content.extend(chunk)
            if self.clock() >= deadline:
                raise ProviderError(source, "请求超过总时间预算", retryable=True)
            clean_headers = [(key, value) for key, value in streamed.headers.raw if key.lower() not in {b"content-encoding", b"content-length"}]
            return httpx.Response(streamed.status_code, headers=clean_headers, content=bytes(content), request=streamed.request)

    def get(self, source, url, *, params=None, headers=None):
        """功能：有限重试、墙钟限制及熔断；输入：固定URL；输出：响应或显式错误。"""
        count, until = self.failures.get(source, (0, 0))
        if until > self.clock():
            raise ProviderError(source, "数据源熔断冷却中，请稍后再试", retryable=True)
        deadline = self.clock() + self.timeout * (self.retries + 1) + 2
        for attempt in range(self.retries + 1):
            retryable = False
            try:
                response = self._response(source, url, params, headers, deadline)
                self.failures.pop(source, None)
                return response
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                message = f"HTTP {exc.response.status_code}"
            except httpx.TransportError as exc:
                retryable = True
                message = f"网络失败({type(exc).__name__})"
            except ProviderError as exc:
                retryable = exc.retryable
                message = str(exc)
            if not retryable or attempt == self.retries or self.clock() >= deadline:
                count += 1
                self.failures[source] = (count, self.clock() + 60 if count >= 3 else 0)
                raise ProviderError(source, message, retryable=retryable)
            self.sleeper(min(0.25 * 2 ** attempt, 2.0))

    def json(self, source, url, **kwargs):
        """功能：读取严格JSON；输入：请求参数；输出：对象或格式错误。"""
        response = self.get(source, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(source, "上游未返回合法JSON") from exc

    def close(self):
        """功能：释放连接；输入：无；输出：无。"""
        self.client.close()


class AKRunner:
    """AKShare子进程调用器，Windows/Linux均通过JSON协议硬超时结束进程。"""

    def __init__(self, settings, *, run=subprocess.run):
        """功能：配置隔离调用；输入：Settings和测试运行器；输出：调用器。"""
        self.timeout = settings.request_timeout
        self.run = run

    def call(self, function, **kwargs):
        """功能：硬超时运行白名单函数；输入：函数名、JSON参数；输出：原始行列表。"""
        source = f"akshare:{function}"
        request = json.dumps({"function": function, "kwargs": kwargs}, ensure_ascii=False)
        try:
            completed = self.run(
                [sys.executable, "-X", "utf8", str(Path(__file__).with_name("worker.py"))],
                input=request, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(source, f"AKShare子进程超过{self.timeout}秒已终止", retryable=True) from exc
        except OSError as exc:
            raise ProviderError(source, "无法启动AKShare子进程") from exc
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, TypeError) as exc:
            raise ProviderError(source, "AKShare子进程返回无效JSON") from exc
        if completed.returncode != 0 or not payload.get("ok"):
            raise ProviderError(source, str(payload.get("error", "AKShare调用失败"))[:400])
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ProviderError(source, "AKShare返回格式不符")
        return rows
