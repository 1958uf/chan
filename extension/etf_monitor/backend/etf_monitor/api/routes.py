"""统一/api契约，分页上限、非敏感设置和CSV公式保护。"""
import csv
import io
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..models import ETF, HolderRecord

router = APIRouter(prefix="/api")
Code = Annotated[str, Query(pattern=r"^[0-9]{6}$")]
Limit = Annotated[int, Query(ge=1, le=1000)]
Offset = Annotated[int, Query(ge=0, le=100000)]
PUBLIC_SETTINGS = ("mode", "scheduler_enabled", "quote_interval", "intraday_enabled", "daily_update_hour", "daily_update_minute", "request_timeout", "max_retries",
                   "max_backfill_days", "alert_cooldown_seconds", "shares_alert_pct")


class ETFInput(ETF):
    """API观察标的：启用开关仅接受JSON布尔，不强制转换字符串。"""
    enabled: bool = Field(default=True, strict=True)


class TaskInput(BaseModel):
    """任务参数：仅接受预定义类别和六位文本代码。"""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["refresh", "backfill", "holders", "market", "calendar", "catalogue", "shares"]
    interval: Literal["day", "1m", "5m"] = "day"
    start: date | None = None
    end: date | None = None
    codes: list[Annotated[str, Field(pattern=r"^[0-9]{6}$")]] | None = Field(default=None, max_length=5000)
    group: str | None = Field(default=None, min_length=1, max_length=40)
    asset_class: str | None = Field(default=None, min_length=1, max_length=30)

    @field_validator("start", "end", mode="before")
    @classmethod
    def validate_date_input(cls, value):
        """功能：拒绝数值时间戳和非ISO日期；输入：原始日期；输出：日期或None。"""
        if value is None or isinstance(value, date):
            return value
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("日期必须是YYYY-MM-DD")
        return date.fromisoformat(value)


class HolderInput(BaseModel):
    """人工导入：保留报告期、公告日与来源，单批最多1000条。"""
    model_config = ConfigDict(extra="forbid")
    records: list[HolderRecord] = Field(min_length=1, max_length=1000)


class SettingsInput(BaseModel):
    """可调设置白名单，禁止目录、模式、来源URL和令牌。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    scheduler_enabled: bool | None = None
    intraday_enabled: bool | None = None
    daily_update_hour: int | None = Field(default=None, ge=16, le=23)
    daily_update_minute: int | None = Field(default=None, ge=0, le=59)
    quote_interval: int | None = Field(default=None, ge=15, le=3600)
    alert_cooldown_seconds: int | None = Field(default=None, ge=1, le=604800)
    shares_alert_pct: float | None = Field(default=None, gt=0, le=100)


def state(request):
    """功能：获取lifespan服务；输入：请求；输出：应用状态。"""
    return request.app.state


def date_range(start, end, today, max_days=3650):
    """功能：拒绝颠倒、未来和超长区间；输入：起止与当前日；输出：无或422。"""
    if start and end and (start > end or (end - start).days > max_days):
        raise HTTPException(422, "日期区间颠倒或超出允许范围")
    if (start and start > today) or (end and end > today):
        raise HTTPException(422, "日期不可晚于当前日期")


def find_etf(app_state, code):
    """功能：检查观察池标的；输入：状态与六位代码；输出：ETF或404。"""
    for etf in app_state.repository.etfs():
        if etf.code == code:
            return etf
    raise HTTPException(404, "ETF不在观察池中")


def analyse(app_state, etf, as_of=None, *, known_at=None, knowledge_mode="point_in_time"):
    """功能：分析指定业务与知识时点；输入：日期、修订知识边界、口径；输出：带覆盖元数据的分析。"""
    from ..analysis import analyse_etf
    cutoff = as_of or app_state.clock()
    day = cutoff.date() if isinstance(cutoff, datetime) else cutoff
    knowledge = known_at or (cutoff if isinstance(cutoff, datetime) else datetime.combine(day, time.max, ZoneInfo("Asia/Shanghai")))
    values = {kind: app_state.repository.records(kind, etf.code if kind != "market" else None,
                                                end=day, limit=1000, newest=True, known_at=knowledge,
                                                interval="day" if kind == "bars" else None)
              for kind in ("shares", "quotes", "bars", "navs", "market")}
    intervals = app_state.repository.calendar_coverage(knowledge)
    calendar = app_state.repository.calendar_days(end=day)
    # 无明确请求覆盖的旧缓存不能证明最新截止日；缺口存在时不能计算完整覆盖评分。
    start = min((record.trade_date for record in values["shares"]), default=day)
    complete = app_state.repository.calendar_covers(start, day, knowledge)
    result = analyse_etf(etf, values["shares"], values["quotes"], values["bars"], values["navs"], values["market"], cutoff,
                         calendar=calendar if complete else [], calendar_start=start if complete else None,
                         calendar_end=day if complete else None, knowledge_mode=knowledge_mode,
                         known_at=knowledge if knowledge_mode == "point_in_time" else None)
    result["calendar_coverage"].update(complete=complete, start=str(start), end=str(day), intervals=intervals)
    if not complete:
        result.update(coverage=0, score=None, label="证据不足", estimated_flow=None, flow_5d=None, flow_20d=None)
        if result.get("quality") not in ("missing", "suspect", "error", "demo"):
            result["quality"] = "partial"
        for indicator in result.get("indicators", []):
            indicator.update(value=None, points=None, state="unknown", explanation="交易日历请求覆盖不足，无法确认截止日及连续交易日；" + indicator.get("explanation", ""))
    return result


@router.get("/session")
def session(request: Request):
    """功能：向本机同源会话提供令牌；输入：请求；输出：CSRF令牌。"""
    return {"token": state(request).token}


@router.get("/health")
def health(request: Request):
    """功能：依据来源失败、实际数据日期和日历覆盖推导健康；输入：请求；输出：真实健康与原因。"""
    app_state = state(request)
    repo, now = app_state.repository, app_state.clock()
    mode = app_state.settings.mode
    cached = repo.documents("sources", limit=1000)
    latest = repo.record_health(now)
    intervals = repo.calendar_coverage(now)
    covered = repo.calendar_covers(now.date(), now.date(), now)
    # 盘后15:20之前给日频发布留出窗口；交易日由明确覆盖日历确定，绝不猜周末。
    daily_cutoff = now.date() if now.time() >= time(15, 20) else now.date() - timedelta(days=1)
    days = repo.calendar_days(end=daily_cutoff)
    expected = days[-1] if covered and days else None
    sources = {item["source"]: {**item, "last_actual_date": None, "actual_dates": [], "lag_trading_days": None,
                               "calendar_covered": covered, "derived_reasons": []} for item in cached}
    active_quotes = covered and repo.is_trading_day(now.date()) and (time(9, 30) <= now.time() <= time(11, 30) or time(13) <= now.time() <= time(15))
    aliases = {item["source"] for item in cached}
    health_rows = latest + [{**row, "source": row["kind"]} for row in latest if row["kind"] in aliases and row["source"] != row["kind"]]
    for row in health_rows:
        source = sources.setdefault(row["source"], {"source": row["source"], "status": "ok", "last_success": None,
                                                   "error": "", "last_actual_date": None, "actual_dates": [],
                                                   "lag_trading_days": None, "calendar_covered": covered, "derived_reasons": []})
        source["actual_dates"].append(row["day"])
        record = json.loads(row["payload"])
        reasons = source["derived_reasons"]
        if row["quality"] in ("partial", "stale", "suspect", "missing", "error", "demo"):
            reasons.append(f"{row['kind']} {row['code']}质量为{row['quality']}")
            if source["status"] == "ok":
                source["status"] = row["quality"]
        daily = row["kind"] in ("shares", "navs", "market") or row["kind"] == "bars" and row["interval"] == "day"
        if daily:
            if expected is None:
                reasons.append("日历覆盖不足，无法确认日频数据新鲜度")
                if source["status"] == "ok":
                    source["status"] = "partial"
            elif row["day"] < str(expected):
                lag = sum(str(day) > row["day"] for day in days)
                source["lag_trading_days"] = max(source["lag_trading_days"] or 0, lag)
                reasons.append(f"{row['kind']} {row['code']}业务日期{row['day']}落后预期{expected}")
                if source["status"] in ("ok", "partial"):
                    source["status"] = "stale"
        if row["kind"] == "quotes" and expected is not None and row["day"] < str(expected):
            reasons.append(f"{row['code']}行情业务日期落后预期交易日{expected}")
            if source["status"] in ("ok", "partial"):
                source["status"] = "stale"
        if row["kind"] == "quotes" and active_quotes:
            stamp = datetime.fromisoformat(record["quote_time"])
            if (now - stamp).total_seconds() > max(120, app_state.settings.quote_interval * 3):
                reasons.append(f"{row['code']}源行情时刻已过期")
                if source["status"] in ("ok", "partial"):
                    source["status"] = "stale"
    for source in sources.values():
        source["actual_dates"] = sorted(set(source["actual_dates"]))
        source["last_actual_date"] = max(source["actual_dates"], default=None)
        if source["status"] == "ok" and not source["actual_dates"] and source["source"] != "calendar":
            source["status"] = "partial"
            source["derived_reasons"].append("最近请求标记成功但没有可验证的已保存业务日期")
        source["derived_reasons"] = list(dict.fromkeys(source["derived_reasons"]))[:200]
        if source["status"] in ("empty", "partial", "stale", "error", "suspect", "missing") and not source["derived_reasons"]:
            source["derived_reasons"] = [source.get("message") or source.get("error") or "来源没有完整有效数据"]
    calendar_state = {"source": "calendar_coverage", "status": "ok" if covered else "partial",
                      "last_success": max((item["fetched_at"] for item in intervals), default=None), "error": "",
                      "last_actual_date": str(days[-1]) if days else None,
                      "calendar_covered": covered, "expected_trade_date": str(expected) if expected else None,
                      "derived_reasons": [] if covered else ["交易日历请求覆盖未延伸至当前日期，不能确认数据新鲜度"]}
    reasons = list(calendar_state["derived_reasons"])
    pool = [etf for etf in repo.etfs() if etf.enabled]
    for kind in ("shares", "navs", "bars"):
        present = {row["code"] for row in latest if row["kind"] == kind and (kind != "bars" or row["interval"] == "day")}
        missing = [etf.code for etf in pool if etf.code not in present]
        if missing:
            reasons.append(f"{kind}缺少{len(missing)}个启用标的：{','.join(missing[:20])}")
    source_list = list(sources.values()) + [calendar_state]
    failed = any(source["status"] != "ok" for source in source_list)
    if mode == "demo":
        status, notice = "demo", "演示样本健康不代表真实数据源在线或实时有效。"
    elif not latest and not cached:
        status, notice = "empty", "尚无真实采集数据；空库不代表数据源在线。"
    else:
        status = "degraded" if failed or reasons else "ok"
        notice = "存在失败、缺失、过期或日历覆盖不足，详情见sources/reasons。" if status != "ok" else "已校验本地真实来源及日频日期覆盖；不代表上游持续在线。"
    shares_pool = repo.catalogue(classification_status="confirmed", enabled=True, limit=5000)
    shares_cutoff = now.date() if now.hour * 60 + now.minute >= app_state.settings.daily_update_hour * 60 + app_state.settings.daily_update_minute else now.date() - timedelta(days=1)
    shares_days = repo.calendar_days(end=shares_cutoff)
    shares_expected = shares_days[-1] if covered and shares_days else None
    share_dates = repo.share_latest_dates([item.code for item in shares_pool], now.date())
    shares_missing = [item.code for item in shares_pool if shares_expected is None or share_dates.get(item.code) is None or share_dates[item.code] < shares_expected]
    shares_reasons = (["交易日历未知，份额预期日不可确认"] if shares_expected is None else [])
    if shares_missing:
        shares_reasons.append(f"预期日份额缺失或滞后{len(shares_missing)}个确认启用目录成员")
    if not shares_pool:
        shares_reasons.append("目录没有确认启用成员")
    shares_source_errors = [item for item in cached if (item["source"].startswith(("shares.", "sse:shares", "szse:shares"))) and item.get("status") in ("error", "partial")]
    shares_reasons.extend(item.get("error") or item.get("message") or "份额来源失败" for item in shares_source_errors)
    shares_health = {"status": "demo" if mode == "demo" else "degraded" if shares_reasons else "ok",
                     "expected_trade_date": str(shares_expected) if shares_expected else None,
                     "confirmed_enabled": len(shares_pool), "available_count": len(shares_pool) - len(shares_missing),
                     "missing_codes": shares_missing[:100], "reasons": shares_reasons,
                     "last_success": repo.document("metadata", "shares_last_success"),
                     "intraday_enabled": app_state.settings.intraday_enabled,
                     "daily_update_time": f"{app_state.settings.daily_update_hour:02}:{app_state.settings.daily_update_minute:02}"}
    return {"mode": mode, "status": status, "now": now.isoformat(), "sources": source_list,
            "shares_health": shares_health,
            "scheduler_enabled": app_state.settings.scheduler_enabled,
            "calendar_known": repo.is_trading_day(now.date()), "calendar_covered": covered,
            "expected_trade_date": str(expected) if expected else None, "reasons": reasons, "notice": notice}


@router.get("/etfs")
def etfs(request: Request, limit: Limit = 100, offset: Offset = 0):
    """功能：分页读观察池；输入：分页；输出：ETF列表。"""
    return {"items": state(request).repository.etfs()[offset:offset + limit]}


@router.post("/etfs")
def put_etf(request: Request, etf: ETFInput):
    """功能：创建或更新标的；输入：严格ETF契约；输出：保存后ETF。"""
    if not etf.code.isascii() or not ((etf.exchange == "sh" and etf.code.startswith(("5", "6"))) or
                                       (etf.exchange == "sz" and etf.code.startswith("1"))):
        raise HTTPException(422, "ETF代码与交易所不匹配")
    if etf.listed_on and etf.listed_on > state(request).clock().date():
        raise HTTPException(422, "上市日期不可在未来")
    if not etf.name.strip() or not etf.group.strip() or len(etf.tags) > 20 or any(not tag.strip() or len(tag) > 40 for tag in etf.tags):
        raise HTTPException(422, "名称、分类或标签非法")
    app_state = state(request)
    if len(app_state.repository.etfs()) >= 200 and all(item.code != etf.code for item in app_state.repository.etfs()):
        raise HTTPException(422, "观察池最多200个ETF")
    app_state.repository.put_etfs([etf])
    app_state.repository.set_catalogue_enabled(etf.code, etf.enabled)
    return etf


@router.get("/dashboard")
def dashboard(request: Request, as_of: date | None = None):
    """功能：生成分组看板；输入：截止日；输出：分析、市场和演示提示。"""
    app_state = state(request)
    date_range(as_of, None, app_state.clock().date())
    day = as_of or app_state.clock().date()
    items, groups = [], {}
    record_count = len(app_state.repository.etfs())
    if record_count > 200:
        raise HTTPException(422, "观察池超出系统处理上限")
    for etf in app_state.repository.etfs():
        if not etf.enabled:
            continue
        analysis = analyse(app_state, etf, as_of)
        items.append({**etf.model_dump(mode="json"), **analysis})
        group = groups.setdefault(etf.group, {"group": etf.group, "flow": None, "count": 0, "coverage": 0})
        group["count"] += 1
        flow = analysis.get("estimated_flow")
        if flow is not None:
            group["flow"] = (group["flow"] or 0) + flow
            group["coverage"] += 1
    return {"mode": app_state.settings.mode, "as_of": str(day), "etfs": items, "groups": list(groups.values()),
            "market": app_state.repository.records("market", end=day, limit=100, newest=True),
            "notice": "演示模式：固定虚构样本，非实时行情，不可用于交易" if app_state.settings.mode == "demo" else "份额为交易所日数据；估算净流入不代表实时申赎或机构身份。"}


@router.get("/etfs/{code}")
def etf_detail(request: Request, code: Annotated[str, Path(pattern=r"^[0-9]{6}$")], limit: Limit = 100, offset: Offset = 0):
    """功能：读标的完整来源与分析；输入：代码与分页；输出：明细。"""
    app_state = state(request)
    etf = find_etf(app_state, code)
    return {"etf": etf, "analysis": analyse(app_state, etf),
            **{kind: app_state.repository.records(kind, code, end=app_state.clock().date(), limit=limit, offset=offset, newest=True)
               for kind in ("shares", "quotes", "bars", "navs", "holders")}}


@router.get("/history")
def history(request: Request, group: str | None = Query(default=None, max_length=40), start: date | None = None,
            end: date | None = None, limit: Limit = 100, offset: Offset = 0,
            knowledge_mode: Literal["retrospective", "point_in_time"] = "retrospective", known_at: datetime | None = None):
    """功能：区分事后统计与当时已知历史；输入：范围、口径、知识时点、分页；输出：历史和口径说明。"""
    app_state = state(request)
    now = app_state.clock()
    date_range(start, end, now.date())
    if known_at is not None and (known_at.tzinfo is None or known_at > now):
        raise HTTPException(422, "known_at必须带时区且不可晚于当前时间")
    knowledge = known_at or now
    pool = {etf.code: etf for etf in app_state.repository.etfs() if group is None or etf.group == group}
    filtered = app_state.repository.records("shares", start=start, end=end or now.date(), limit=limit,
                                            offset=offset, newest=True, codes=list(pool), known_at=knowledge,
                                            day_known=knowledge_mode == "point_in_time")
    items, analysis_cache = [], {}
    for record in filtered:
        cutoff = (min(knowledge, datetime.combine(record.trade_date, time.max, ZoneInfo("Asia/Shanghai")))
                  if knowledge_mode == "point_in_time" else knowledge)
        key = (record.code, cutoff, record.trade_date)
        if key not in analysis_cache:
            business_cutoff = cutoff if knowledge_mode == "point_in_time" else record.trade_date
            analysis_cache[key] = analyse(app_state, pool[record.code], business_cutoff, known_at=cutoff, knowledge_mode=knowledge_mode)
        result = analysis_cache[key]
        row = next((row for row in result.get("history", []) if row["date"] == str(record.trade_date)), {})
        items.append({"date": str(record.trade_date), "code": record.code, "group": pool[record.code].group,
                      "shares": record.shares, "estimated_flow": row.get("estimated_flow"),
                      "delta_shares": row.get("delta_shares"), "delta_pct": row.get("delta_pct"),
                      "reason": row.get("reason"), "source": record.source,
                      "fetched_at": record.fetched_at.isoformat(), "quality": row.get("quality", record.quality),
                      "knowledge_mode": knowledge_mode, "known_at": cutoff.isoformat()})
    return {"items": items, "knowledge_mode": knowledge_mode, "known_at": knowledge.isoformat(),
            "notice": "事后历史统计：采用知识截止时已采集的历史及修订，不代表业务日当时已知，不能作为点时回测。" if knowledge_mode == "retrospective" else "当时已知历史：仅采用业务日收盘及指定知识截止之前已保存的版本，后补与未来修订不纳入。"}


@router.get("/holders")
def holders(request: Request, code: Code | None = None, limit: Limit = 100, offset: Offset = 0):
    """功能：分页读报告期持有人；输入：代码与分页；输出：来源完整记录。"""
    app_state = state(request)
    if code:
        find_etf(app_state, code)
    return {"items": app_state.repository.records("holders", code, limit=limit, offset=offset, newest=True)}


@router.post("/holders/import")
def import_holders(request: Request, body: HolderInput):
    """功能：原子导入持有人；输入：规范记录；输出：处理数量和修订数。"""
    app_state = state(request)
    today = app_state.clock().date()
    identities = set()
    for record in body.records:
        find_etf(app_state, record.code)
        if not record.code.isascii() or not record.holder.strip() or len(record.source) > 200 or (record.institution_group is not None and len(record.institution_group) > 80) or len(record.source_url) > 2048:
            raise HTTPException(422, "持有人代码、名称或来源字段非法")
        if app_state.settings.mode == "live" and record.quality == "demo":
            raise HTTPException(422, "真实模式禁止导入演示记录")
        if not record.source.strip() or record.report_date > today or (record.published_on and (record.published_on < record.report_date or record.published_on > today)):
            raise HTTPException(422, "来源为空或报告/公告日期非法")
        if record.source_url and not record.source_url.startswith(("https://", "http://")):
            raise HTTPException(422, "来源链接仅接受http/https")
        key = (record.code, record.report_date, record.holder, record.source)
        if key in identities:
            raise HTTPException(422, "同一批次含重复持有人业务键")
        identities.add(key)
    changed = app_state.repository.save_records({"holders": body.records}, app_state.clock())
    return {"ok": True, "count": len(body.records), "changed": changed}


@router.get("/alerts")
def alerts(request: Request, limit: Limit = 100, offset: Offset = 0):
    """功能：分页读取本地告警；输入：分页；输出：告警列表。"""
    return {"items": state(request).repository.alerts(limit, offset)}


@router.post("/alerts/{identifier}/ack")
def ack_alert(request: Request, identifier: str):
    """功能：幂等确认告警；输入：ID；输出：确认成功或404。"""
    if not state(request).repository.acknowledge(identifier):
        raise HTTPException(404, "告警不存在")
    return {"ok": True}


@router.get("/tasks")
def tasks(request: Request, limit: Limit = 100, offset: Offset = 0):
    """功能：读取任务及真实错误；输入：分页；输出：任务列表。"""
    return {"items": state(request).repository.documents("tasks", limit, offset)}


@router.post("/tasks")
def submit_task(request: Request, body: TaskInput):
    """功能：创建有限任务；输入：任务参数；输出：任务或422/429。"""
    try:
        return state(request).tasks.submit(body.kind, body.start, body.end, body.codes, interval=body.interval,
                                           group=body.group, asset_class=body.asset_class)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(429, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/tasks/{identifier}/cancel")
def cancel_task(request: Request, identifier: str):
    """功能：取消未完成任务；输入：任务ID；输出：成功或404。"""
    if not state(request).tasks.cancel(identifier):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.get("/settings")
def settings(request: Request):
    """功能：只读非敏感配置；输入：请求；输出：白名单参数。"""
    values = state(request).settings.model_dump(mode="json")
    return {key: values[key] for key in PUBLIC_SETTINGS}


@router.put("/settings")
def put_settings(request: Request, body: SettingsInput):
    """功能：原子更新白名单阈值；输入：可调设置；输出：非敏感配置。"""
    app_state = state(request)
    values = body.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(422, "配置不可设为null")
    if app_state.settings.mode == "demo" and values.get("scheduler_enabled"):
        raise HTTPException(422, "演示模式禁止启用真实调度")
    try:
        updated = app_state.settings.__class__.model_validate({**app_state.settings.model_dump(), **values})
    except ValidationError as exc:
        raise HTTPException(422, "配置超出范围") from exc
    with app_state.tasks.lock:
        app_state.repository.put_document("metadata", "settings", {key: getattr(updated, key) for key in SettingsInput.model_fields})
        app_state.settings = updated
        app_state.tasks.settings = updated
    return settings(request)


def csv_cell(value):
    """功能：阻止CSV公式执行；输入：单元格值；输出：安全文本或数值。"""
    if value is None:
        return ""
    if isinstance(value, str) and (value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


@router.get("/export")
def export(request: Request, format: Literal["csv", "json"] = "csv", code: Code | None = None,
           start: date | None = None, end: date | None = None, limit: Annotated[int, Query(ge=1, le=10000)] = 1000):
    """功能：有界下载原始份额；输入：格式、代码、日期、上限；输出：安全CSV或JSON。"""
    app_state = state(request)
    date_range(start, end, app_state.clock().date())
    if code:
        find_etf(app_state, code)
    records = [item.model_dump(mode="json") for item in app_state.repository.records("shares", code, start, end or app_state.clock().date(), limit)]
    headers = {"Content-Disposition": f'attachment; filename="etf-shares.{format}"', "X-Export-Limit": str(limit)}
    if format == "json":
        return Response(json.dumps({"items": records, "limit": limit}, ensure_ascii=False, allow_nan=False), media_type="application/json", headers=headers)
    buffer = io.StringIO(newline="")
    columns = ("code", "trade_date", "shares", "source", "fetched_at", "quality")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in records:
        writer.writerow({key: csv_cell(row.get(key)) for key in columns})
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
