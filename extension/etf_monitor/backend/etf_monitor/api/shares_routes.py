"""独立目录与纯份额接口：不依赖NAV、报价或旧观察池，沿用应用统一安全中间件。"""
import csv
import io
import json
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .routes import csv_cell, date_range, state

shares_router = APIRouter(prefix="/api")
Period = Literal["day", "week", "month"]
Asset = Annotated[str, Query(min_length=1, max_length=30)]
Group = Annotated[str, Query(min_length=1, max_length=40)]
Code = Annotated[str, Query(pattern=r"^[0-9]{6}$")]


class ClassificationInput(BaseModel):
    """人工确认契约：字段白名单、严格开关，分类确认不改变观察池。"""
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{6}$")
    group: str = Field(min_length=1, max_length=40)
    asset_class: Literal["宽基", "行业", "主题", "风格", "债券", "商品", "跨境", "货币", "未分类"]
    tracking_index: str | None = Field(default=None, max_length=100)
    classification_status: Literal["confirmed"] = "confirmed"
    enabled: bool | None = Field(default=None, strict=True)

    @field_validator("group", "tracking_index")
    @classmethod
    def validate_text(cls, value):
        """功能：拒绝空白分类文本；输入：分类或指数名称；输出：已去边界空白文本。"""
        if value is not None and not value.strip():
            raise ValueError("分类或指数名称不能全为空白")
        return value.strip() if value else value


def pool(app_state, *, asset_class=None, group=None, code=None, include_disabled=False):
    """功能：读取目录含候选及可选禁用历史成员；输入：目录筛选和历史开关；输出：规范ETF列表。"""
    items = app_state.repository.catalogue(asset_class=asset_class, group=group,
                                          enabled=None if include_disabled else True, limit=5000)
    if code:
        items = [item for item in items if item.code == code]
        if not items:
            raise HTTPException(404, "ETF不在目录中" if include_disabled else "ETF不在启用目录中")
    return items


def load_data(app_state, etfs, start, end):
    """功能：有界分页加载纯份额和真实日历；输入：目录及日期区间；输出：记录、完整覆盖日历和说明。"""
    repository = app_state.repository
    records, offset, maximum = [], 0, 500000
    codes = [item.code for item in etfs]
    while codes:
        batch = repository.records("shares", codes=codes, start=start, end=end, limit=10000, offset=offset)
        records.extend(batch)
        if len(batch) < 10000:
            break
        offset += 10000
        if offset >= maximum:
            raise HTTPException(422, "份额查询超过50万记录预算，请缩小日期区间或按类别/代码筛选")
    required_start = min((item.trade_date for item in records), default=end)
    complete = repository.calendar_covers(required_start, end)
    calendar = repository.calendar_days(start=start, end=end, limit=10000) if complete else []
    notice = ("演示模式：固定虚构目录与份额样本，非真实全市场数据，不可用于交易。" if app_state.settings.mode == "demo"
              else "交易所日份额，采用本地已保存修订的事后统计；不代表实时申赎、资金流或机构身份。")
    if not complete:
        notice += " 交易日历覆盖不足，不能猜测工作日或认定数据齐备，请提交calendar或shares任务闭环。"
    return records, calendar, notice, complete


def published_dates(etfs, records, calendar):
    """功能：按确认在册成员求各市有效发布日；输入：目录、份额、已知日历；输出：交易所到日期集合，不混候选或异常记录。"""
    confirmed = {item.code: item for item in etfs if item.classification_status == "confirmed"}
    markets = {item.exchange: set() for item in confirmed.values()}
    days, versions = set(calendar), {}
    for record in records:
        item = confirmed.get(record.code)
        if item is None or record.trade_date not in days:
            continue
        if (item.listed_on and record.trade_date < item.listed_on) or (item.delisted_on and record.trade_date >= item.delisted_on):
            continue
        versions.setdefault((item.exchange, record.code, record.trade_date), []).append(record)
    for (exchange, _, trade_date), values in versions.items():
        if all(value.quality in ("valid", "demo") for value in values) and len({value.shares for value in values}) == 1:
            markets[exchange].add(trade_date)
    return markets


def build_overview(app_state, as_of, period, asset_class=None, group=None):
    """功能：默认选择最新共同发布日，显式截止不回退；输入：业务日、周期与分类；输出：保留请求日期的统一统计日看板。"""
    from ..analysis.shares import share_overview
    day = as_of or app_state.clock().date()
    date_range(day, None, app_state.clock().date())
    etfs = pool(app_state, asset_class=asset_class, group=group)
    # 20交易日和上一自然月期末均需足够回看，绝不只取成员各自latest。
    start = day - timedelta(days=65)
    records, calendar, notice, complete = load_data(app_state, etfs, start, day)
    known_days = app_state.repository.calendar_days(start=start, end=day, limit=10000)
    markets = published_dates(etfs, records, known_days)
    actual, selection = day, "explicit" if as_of is not None else "no_published_data"
    if as_of is None:
        common = set.intersection(*markets.values()) if markets else set()
        available = set.union(*markets.values()) if markets else set()
        if common or available:
            actual = max(common or available)
            selection = "latest_common" if common else "latest_available_partial"
            required_start = min((item.trade_date for item in records if item.trade_date <= actual), default=actual)
            complete = app_state.repository.calendar_covers(required_start, actual)
            calendar = [value for value in known_days if value <= actual] if complete else []
            # 日历只需覆盖选定统计日；当日尚未发布或日历尚未延伸，不抹掉已确认历史。
            notice = ("演示模式：固定虚构目录与份额样本，非真实全市场数据，不可用于交易。" if app_state.settings.mode == "demo"
                      else "交易所日份额，采用本地已保存修订的事后统计；不代表实时申赎、资金流或机构身份。")
            notice += f" 默认统计日为{actual}，请求截止日为{day}；" + ("采用所选市场共同有效发布日，不混各市不同日期latest。" if common else "所选市场没有共同发布日，统一采用最近有效发布日，缺市成员计入缺失覆盖。")
            if not complete:
                notice += " 选定统计日前日历覆盖不足，无法确认统计日与变化。"
    result = share_overview(etfs, records, calendar, actual, period=period)
    trade_date = result.get("coverage", {}).get("trade_date")
    result.update(as_of=str(day), requested_as_of=str(day), statistics_date=trade_date,
                  date_selection=selection, mode=app_state.settings.mode)
    result["notice"] = notice + " " + str(result.get("notice", ""))
    coverage = result.setdefault("coverage", {})
    coverage.update(calendar_complete=complete, requested_date=str(day), date_selection=selection,
                    market_latest_dates={exchange: str(max(values)) if values else None for exchange, values in markets.items()},
                    missing_markets=[exchange for exchange, values in markets.items() if trade_date is None or date.fromisoformat(trade_date) not in values])
    return result


@shares_router.get("/catalogue")
def catalogue(request: Request, asset_class: Asset | None = None, group: Group | None = None,
              classification_status: Literal["confirmed", "candidate", "unclassified"] | None = None,
              q: Annotated[str, Query(max_length=100)] | None = None,
              limit: Annotated[int, Query(ge=1, le=5000)] = 100,
              offset: Annotated[int, Query(ge=0, le=100000)] = 0):
    """功能：检索全市场独立目录；输入：分类、关键词、≤5000分页；输出：成员、总数及来源覆盖。"""
    repository = state(request).repository
    filters = dict(asset_class=asset_class, group=group, classification_status=classification_status, q=q)
    return {"items": repository.catalogue(**filters, limit=limit, offset=offset),
            **repository.catalogue_summary(**filters)}


@shares_router.post("/catalogue/classify")
def classify(request: Request, body: ClassificationInput):
    """功能：人工确认并保留后续同步优先级；输入：同源令牌保护分类；输出：更新成员或404。"""
    values = body.model_dump(exclude_unset=True)
    if "enabled" in values and values["enabled"] is None:
        raise HTTPException(422, "启用开关不可为null")
    values.pop("code")
    item = state(request).repository.classify_catalogue(body.code, **values)
    if item is None:
        raise HTTPException(404, "ETF尚未在目录发现")
    return item


@shares_router.get("/shares/overview")
def overview(request: Request, as_of: date | None = None, period: Period = "day",
             asset_class: Asset | None = None, group: Group | None = None):
    """功能：查询同日可比纯份额看板；输入：截止日和周期分类；输出：产品、分组、覆盖及模式。"""
    return build_overview(state(request), as_of, period, asset_class, group)


@shares_router.get("/shares/groups/{group}")
def group_detail(request: Request, group: Annotated[str, Path(min_length=1, max_length=40)],
                 as_of: date | None = None, period: Period = "day"):
    """功能：展示分类成员含候选覆盖；输入：类别、业务日和周期；输出：分组摘要和全目录成员。"""
    app_state = state(request)
    if not app_state.repository.catalogue(group=group, limit=1):
        raise HTTPException(404, "目录分类不存在")
    result = build_overview(app_state, as_of, period, group=group)
    summary = next((item for item in result.get("groups", []) if item["group"] == group), None)
    return {"group": summary, "items": result["items"], "mode": result["mode"], "notice": result["notice"],
            "as_of": result["as_of"], "requested_as_of": result["requested_as_of"],
            "statistics_date": result["statistics_date"], "date_selection": result["date_selection"], "coverage": result["coverage"]}


@shares_router.get("/shares/history")
def history(request: Request, start: date | None = None, end: date | None = None,
            frequency: Period = "day", group: Group | None = None, code: Code | None = None,
            limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
            offset: Annotated[int, Query(ge=0, le=100000)] = 0):
    """功能：查询日周月期末存量历史；输入：范围、分类/代码和有界分页；输出：频率、质量与历史行。"""
    from ..analysis.shares import share_history
    app_state = state(request)
    right = end or app_state.clock().date()
    left = start or right - timedelta(days=40)
    date_range(left, right, app_state.clock().date())
    # 禁用表示停止后续采集，不能抹掉已采集成员的历史；上市/退市边界由纯计算契约处理。
    etfs = pool(app_state, group=group, code=code, include_disabled=True)
    records, calendar, notice, complete = load_data(app_state, etfs, left - timedelta(days=65), right)
    period_count = sum(left <= day <= right for day in calendar)
    if period_count * len({item.group for item in etfs}) > 100000:
        raise HTTPException(422, "历史分组计算超过10万组日预算，请缩小日期范围或按group/code筛选")
    items = share_history(etfs, records, calendar, left, right, frequency=frequency)
    return {"items": items[offset:offset + limit], "total": len(items), "frequency": frequency,
            "mode": app_state.settings.mode, "notice": notice, "calendar_complete": complete}


@shares_router.get("/shares/export")
def shares_export(request: Request, format: Literal["csv", "json"] = "csv", as_of: date | None = None,
                  period: Period = "day", group: Group | None = None,
                  limit: Annotated[int, Query(ge=1, le=5000)] = 5000):
    """功能：有界下载纯份额看板并防CSV公式注入；输入：周期、分类及格式；输出：下载响应。"""
    result = build_overview(state(request), as_of, period, group=group)
    total = len(result["items"])
    result["items"] = result["items"][:limit]
    result.update(limit=limit, total=total, truncated=total > limit)
    headers = {"Content-Disposition": f'attachment; filename="etf-shares-overview.{format}"',
               "X-Export-Limit": str(limit), "X-Export-Truncated": str(total > limit).lower()}
    if format == "json":
        return Response(json.dumps(result, ensure_ascii=False, allow_nan=False, default=str), media_type="application/json", headers=headers)
    columns = ("code", "name", "group", "asset_class", "shares", "trade_date", "delta_shares", "delta_pct",
               "delta_5d", "delta_20d", "increase_streak", "decrease_streak", "quality", "reason", "source", "classification_status")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for item in result["items"]:
        writer.writerow({key: csv_cell(item.get(key)) for key in columns})
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
