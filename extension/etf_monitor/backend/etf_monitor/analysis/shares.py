"""纯份额统计：同日存量、同可比成员变化，不依赖NAV、价格或持有人数据。

所有份额数值单位为份，百分比单位为%；未知值保留None。份额变化不是资金流，
大比例跳变只提示疑似拆分，不能在没有公告的情况下自动复权或确认申赎。
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Iterable


NOTICE = "份额为交易所日终存量，不等同资金净流入或机构持有；不使用NAV、行情及持有人报告。候选不计入已确认总体；覆盖率不代表全市场完整性。"
_GOOD = {"valid", "demo"}


def _get(value, key, default=None):
    """功能：兼容模型和字典；输入：记录、字段、默认值；输出：字段值。"""
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _date(value) -> date:
    """功能：规范纯统计日期；输入：date或ISO文本；输出：date。"""
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _alive(etf, day: date | None) -> bool:
    """功能：只按真实上市/退出日期筛选在册成员；输入：ETF和统计日；输出：当日是否在册。

    enabled仅控制当前观察/后续采集，不能代表历史退出或删除已有历史。
    """
    if day is None:
        return False
    listed, exited = _get(etf, "listed_on"), _get(etf, "delisted_on")
    return (not listed or _date(listed) <= day) and (not exited or day < _date(exited))


def _calendar(calendar: Iterable, as_of: date) -> list[date]:
    """功能：去重排序真实交易日历；输入：日历和截止日；输出：已知交易日，绝不猜工作日。"""
    return sorted({_date(day) for day in calendar if _date(day) <= as_of})


def _baseline(days: list[date], target: date | None, period: str) -> date | None:
    """功能：对齐日/周/月基线；输入：真实交易日及周期；输出：上一交易日或前自然周期末。"""
    if target is None:
        return None
    boundary = target if period == "day" else (target - timedelta(days=target.weekday())
                                               if period == "week" else target.replace(day=1))
    index = bisect_right(days, boundary - timedelta(days=1)) - 1
    if index < 0:
        return None
    candidate = days[index]
    if period == "week" and candidate < boundary - timedelta(days=7):
        return None
    if period == "month":
        previous_month = (boundary - timedelta(days=1)).replace(day=1)
        if candidate < previous_month:
            return None
    return candidate


def _index_records(records: Iterable) -> dict:
    """功能：构建日份额索引并标记冲突；输入：纯份额记录；输出：代码/日期索引。"""
    result = {}
    for record in records:
        code, day = _get(record, "code"), _date(_get(record, "trade_date"))
        shares = _get(record, "shares")
        valid_number = isinstance(shares, (int, float)) and not isinstance(shares, bool) and isfinite(shares) and shares >= 0
        entry = {"shares": float(shares) if valid_number else None,
                 "quality": _get(record, "quality", "valid") if valid_number else "suspect",
                 "source": _get(record, "source", ""), "conflict": False}
        key = (code, day)
        old = result.get(key)
        if old:
            if old["shares"] != entry["shares"] or old["quality"] != entry["quality"]:
                entry.update(quality="suspect", conflict=True)
            elif old["conflict"]:
                entry.update(quality="suspect", conflict=True)
        result[key] = entry
    return result


def _jump(previous: float, current: float) -> bool:
    """功能：保守标记疑似份额拆分/合并；输入：相邻正份额；输出：两倍以上跳变提示。"""
    return previous > 0 and current > 0 and (current / previous >= 2 or current / previous <= 0.5)


def _compare(code: str, index: dict, days: list[date], baseline: date | None,
             target: date | None) -> tuple[float | None, float | None, str, str]:
    """功能：核对首尾及路径异常；输入：代码、索引、交易日窗口；输出：变化、百分比、质量、原因。"""
    if target is None or baseline is None:
        return None, None, "partial", "交易日历不足，无法确定可比基线"
    first, last = index.get((code, baseline)), index.get((code, target))
    if not first or not last:
        return None, None, "partial", "基线日份额缺失" if last else "统计日份额缺失"
    window = days[bisect_right(days, baseline) - 1:bisect_right(days, target)]
    previous = None
    gap = False
    demo = False
    for day in window:
        row = index.get((code, day))
        if not row:
            gap = True
            previous = None
            continue
        if row["quality"] not in _GOOD or row["shares"] is None:
            return None, None, "suspect" if row["quality"] == "suspect" else "partial", "窗口包含冲突或非有效份额"
        demo = demo or row["quality"] == "demo"
        if previous is not None and _jump(previous, row["shares"]):
            return None, None, "suspect", "相邻份额两倍及以上跳变，疑似拆分/合并或大额申赎，未复权"
        previous = row["shares"]
    if gap:
        return None, None, "partial", "可比窗口存在交易日断档，不能核验连续份额变动"
    difference = last["shares"] - first["shares"]
    percentage = difference / first["shares"] * 100 if first["shares"] > 0 else None
    return difference, percentage, "demo" if demo else "valid", "基线份额为零，百分比不可计算" if percentage is None else ""


def _streak(code: str, index: dict, days: list[date], target: date | None) -> tuple[int, int]:
    """功能：计算连续交易日增减次数；输入：日份额索引；输出：连续增加、减少交易日数。"""
    if target is None:
        return 0, 0
    increase = decrease = 0
    end = bisect_right(days, target) - 1
    sign = None
    for position in range(end, 0, -1):
        now, previous = index.get((code, days[position])), index.get((code, days[position - 1]))
        if not now or not previous or now["quality"] not in _GOOD or previous["quality"] not in _GOOD:
            break
        if _jump(previous["shares"], now["shares"]):
            break
        delta = now["shares"] - previous["shares"]
        direction = 1 if delta > 0 else -1 if delta < 0 else 0
        if not direction or sign is not None and direction != sign:
            break
        sign = direction
        increase += int(direction > 0)
        decrease += int(direction < 0)
    return increase, decrease


def _item(etf, index: dict, days: list[date], target: date | None, baseline: date | None) -> dict:
    """功能：生成单产品纯份额行；输入：ETF和对齐时间；输出：同日存量、周期变化与质量。"""
    code = _get(etf, "code")
    row = index.get((code, target)) if target else None
    delta, pct, quality, reason = _compare(code, index, days, baseline, target)
    if row is None:
        quality, reason = "missing", "统计日没有份额记录，未使用不同日期latest补齐"
    elif row["quality"] not in _GOOD:
        quality = "suspect" if row["quality"] == "suspect" else "partial"
        reason = "统计日份额质量非有效，不能计入可比总体"
    elif baseline and not _alive(etf, baseline):
        delta, pct, quality, reason = None, None, "partial", "新上市或新纳入成员，基线不在册，单列而不计入可比变化"
    position = bisect_right(days, target) - 1 if target else -1
    windows = {}
    for length in (5, 20):
        day = days[position - length] if position >= length else None
        change, percent, window_quality, window_reason = _compare(code, index, days, day, target)
        if day and not _alive(etf, day):
            change, percent, window_quality, window_reason = None, None, "partial", "上市不足指定交易日窗口"
        windows.update({f"delta_{length}d": change, f"delta_{length}d_pct": percent,
                        f"quality_{length}d": window_quality, f"reason_{length}d": window_reason})
    membership_days = [day for day in days if _alive(etf, day)]
    increase, decrease = _streak(code, index, membership_days, target)
    return {"code": code, "name": _get(etf, "name"), "group": _get(etf, "group"),
            "asset_class": _get(etf, "asset_class", "宽基"),
            "shares": row["shares"] if row and row["quality"] in _GOOD else None,
            "trade_date": target.isoformat() if target else None,
            "baseline_date": baseline.isoformat() if baseline else None,
            "delta_shares": delta, "delta_pct": pct, **windows,
            "increase_streak": increase, "decrease_streak": decrease,
            "quality": quality, "reason": reason, "source": row["source"] if row else None,
            "classification_status": _get(etf, "classification_status", "confirmed"),
            "new_member": bool(baseline and not _alive(etf, baseline)),
            "_baseline_shares": index.get((code, baseline), {}).get("shares")}


def _group(key: tuple, items: list[dict], target: date | None, exited_count: int) -> dict:
    """功能：用已确认同日与可比成员聚合；输入：分组行；输出：存量、变化与真实分母。"""
    confirmed = [item for item in items if item["classification_status"] == "confirmed"]
    available = [item for item in confirmed if item["shares"] is not None]
    comparable = [item for item in confirmed if item["delta_shares"] is not None and item["quality"] in _GOOD]
    total = len(confirmed)
    denominator = sum(item["_baseline_shares"] for item in comparable)
    delta = sum(item["delta_shares"] for item in comparable) if comparable else None
    if not available:
        quality = "suspect" if any(item["quality"] == "suspect" for item in confirmed) else "missing"
    elif any(item["quality"] == "suspect" for item in confirmed):
        quality = "suspect"
    elif len(comparable) != total or len(available) != total:
        quality = "partial"
    elif any(item["quality"] == "demo" for item in confirmed):
        quality = "demo"
    else:
        quality = "valid"
    return {"group": key[1], "asset_class": key[0],
            "total_shares": sum(item["shares"] for item in available) if available else None,
            "delta_shares": delta, "delta_pct": delta / denominator * 100 if delta is not None and denominator > 0 else None,
            "increased": sum(item["delta_shares"] > 0 for item in comparable),
            "decreased": sum(item["delta_shares"] < 0 for item in comparable),
            "unchanged": sum(item["delta_shares"] == 0 for item in comparable),
            "missing_count": total - len(available),
            "candidate_count": sum(item["classification_status"] == "candidate" for item in items),
            "unclassified_count": sum(item["classification_status"] == "unclassified" for item in items),
            "total_count": total, "available_count": len(available), "comparable_count": len(comparable),
            "new_count": sum(item["new_member"] for item in confirmed), "exited_count": exited_count,
            "coverage_pct": len(comparable) / total * 100 if total else None,
            "availability_pct": len(available) / total * 100 if total else None,
            "trade_date": target.isoformat() if target else None, "quality": quality}


def _overview(etfs: list, index: dict, days: list[date], as_of: date, period: str) -> dict:
    """功能：复用已索引资料生成快照；输入：规范数据和周期；输出：契约字典。"""
    target = days[-1] if days else None
    baseline = _baseline(days, target, period)
    members = [etf for etf in etfs if _alive(etf, target or as_of)]
    items = [_item(etf, index, days, target, baseline) for etf in members]
    grouped = defaultdict(list)
    exits = defaultdict(int)
    for etf in etfs:
        if baseline and _alive(etf, baseline) and not _alive(etf, target) and _get(etf, "classification_status", "confirmed") == "confirmed":
            exits[(_get(etf, "asset_class", "宽基"), _get(etf, "group"))] += 1
    for item in items:
        grouped[(item["asset_class"], item["group"])].append(item)
    groups = [_group(key, grouped[key], target, exits[key]) for key in sorted(set(grouped) | set(exits))]
    total = sum(group["total_count"] for group in groups)
    comparable = sum(group["comparable_count"] for group in groups)
    available = sum(group["available_count"] for group in groups)
    coverage = {"total_count": total, "available_count": available, "comparable_count": comparable,
                "candidate_count": sum(group["candidate_count"] for group in groups),
                "unclassified_count": sum(group["unclassified_count"] for group in groups),
                "coverage_pct": comparable / total * 100 if total else None,
                "availability_pct": available / total * 100 if total else None,
                "trade_date": target.isoformat() if target else None,
                "baseline_date": baseline.isoformat() if baseline else None,
                "calendar_available": bool(days)}
    for item in items:
        item.pop("_baseline_shares")
    notice = NOTICE + (" 缺少真实交易日历，未推算统计日及变化。" if not days else "")
    return {"as_of": as_of.isoformat(), "period": period, "items": items,
            "groups": groups, "coverage": coverage, "notice": notice}


def share_overview(etfs, records, calendar, as_of, period="day") -> dict:
    """功能：纯份额概览；输入：ETF、ShareRecord、真实交易日历、截止日及day/week/month；输出：契约字典。

    统计日统一取日历中不晚于截止日的最后交易日，缺记录不沿用旧值。
    5/20日采用真实交易日偏移，不采用自然日；周月使用上周期末存量比较。
    当前观察过滤enabled=False，历史查询请使用share_history，停用不抹除历史。
    """
    if period not in {"day", "week", "month"}:
        raise ValueError("period只能day/week/month")
    as_of = _date(as_of)
    active = [etf for etf in etfs if _get(etf, "enabled", True)]
    return _overview(active, _index_records(records), _calendar(calendar, as_of), as_of, period)


def share_history(etfs, records, calendar, start, end, frequency="day") -> list[dict]:
    """功能：纯份额期末存量历史；输入：ETF、份额、真实日历、范围和频率；输出：逐期分组行。

    周/月以范围内最后交易日作为期末（末期可未结束），绝不累加日存量。
    基线允许在start之前，因此调用方应传入覆盖前周期及20交易日的份额和日历。
    历史忽略当前enabled开关，只按listed_on/delisted_on确定真实在册日期和退出。
    """
    if frequency not in {"day", "week", "month"}:
        raise ValueError("frequency只能day/week/month")
    start, end = _date(start), _date(end)
    if start > end:
        raise ValueError("start不能晚于end")
    etfs, index, days = list(etfs), _index_records(records), _calendar(calendar, end)
    endpoints = {}
    for day in days:
        if start <= day <= end:
            key = day if frequency == "day" else ((day.isocalendar().year, day.isocalendar().week)
                                                   if frequency == "week" else (day.year, day.month))
            endpoints[key] = day
    result = []
    for target in sorted(endpoints.values()):
        snapshot = _overview(etfs, index, days[:bisect_right(days, target)], target, frequency)
        for group in snapshot["groups"]:
            result.append({"date": target.isoformat(), **group,
                           "baseline_date": snapshot["coverage"]["baseline_date"]})
    return result
