"""纯分析入口：所有评分为可解释规则分，不是概率或机构身份推断。"""
from datetime import date, datetime, time
from math import isfinite
from statistics import mean
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
GOOD = {"valid", "partial", "demo"}


def _finite(value):
    """功能：过滤非有限数值；输入：任意值；输出：有限float或None。"""
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _date(value):
    """功能：解析业务日期；输入：日期对象/ISO/八位字符；输出：date。"""
    if isinstance(value, datetime):
        return value.astimezone(TZ).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def _time(value):
    """功能：规范交易时区；输入：datetime/ISO；输出：上海时间datetime。"""
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)


def _rows(records, code, field, cutoff, *, metric=False, known_at=None):
    """功能：去未来、他标的和冲突记录；输入：模型/字典与截止时刻；输出：排序记录、异常标志。"""
    grouped = {}
    invalid = False
    for record in records:
        try:
            row = record.model_dump() if hasattr(record, "model_dump") else dict(record)
            if not metric and row.get("code") != code:
                continue
            stamp = _time(row[field]) if field in {"time", "quote_time"} else _date(row[field])
            if (isinstance(stamp, datetime) and stamp > cutoff) or (not isinstance(stamp, datetime) and stamp > cutoff.date()):
                continue
            if known_at is not None and (not row.get("fetched_at") or _time(row["fetched_at"]) > known_at):
                continue
            row[field] = stamp
            key = ((stamp, row.get("metric")) if metric else
                   (stamp, row.get("interval", "day")) if field == "time" else stamp)
            previous = grouped.get(key)
            if previous is not None:
                fields = {k: v for k, v in row.items() if k not in {"fetched_at", "source"}}
                previous_fields = {k: v for k, v in previous.items() if k not in {"fetched_at", "source"}}
                if fields != previous_fields:
                    row["quality"] = "suspect"
                    invalid = True
            grouped[key] = row
        except (ValueError, TypeError, KeyError):
            invalid = True
    return [grouped[key] for key in sorted(grouped)], invalid


def _usable(row, field, *, positive=False):
    """功能：判断指标证据可用性；输入：行和数值字段；输出：有限值或None。"""
    if not row or row.get("quality", "valid") not in GOOD:
        return None
    value = _finite(row.get(field))
    return value if value is not None and (value > 0 if positive else value >= 0) else None


def _indicator(name, value, points, explanation):
    """功能：组装解释性指标；输入：名称、观测值、规则分和说明；输出：JSON安全字典。"""
    points = _finite(points)
    state = "unknown" if points is None else "positive" if points >= 65 else "negative" if points <= 35 else "neutral"
    return {"name": name, "value": _finite(value), "state": state, "points": points,
            "explanation": explanation, "weight": 0.2}


def _points(value, multiplier=10):
    """功能：对称线性规则评分；输入：变化百分比/倍数及倍率；输出：0至100分。"""
    return min(100.0, max(0.0, 50.0 + value * multiplier)) if value is not None else None


def known_holders(holders, as_of):
    """功能：筛选历史当时已公告持有人；输入：持有人列表和截止日期；输出：可用记录列表。"""
    cutoff = _date(as_of)
    result = []
    for record in holders:
        row = record.model_dump() if hasattr(record, "model_dump") else dict(record)
        try:
            published = row.get("published_on")
            if published is not None and _date(row["report_date"]) <= _date(published) <= cutoff and row.get("quality", "valid") in GOOD:
                result.append(record)
        except (ValueError, TypeError, KeyError):
            continue
    return result


def analyse_etf(etf, shares, quotes, bars, navs, market, as_of, *, calendar=None,
                calendar_start=None, calendar_end=None, knowledge_mode="retrospective", known_at=None):
    """功能：计算ETF份额/准确NAV估计流量及五指标；输入：记录、截止时间和真实日历；输出：JSON安全分析。

    份额与成交量为份、金额为元、NAV为元/份。估计流量=相邻交易日份额差×当日单位净值，
    不是实测申赎或机构交易；没有日历、同日NAV、连续基线或存在拆分疑点时不计算。
    日期型as_of代表当日收盘后，datetime保留盘中边界；历史滚动严格要求完整5/20个交易日。
    calendar_start/end是采集覆盖范围，不能用最后交易日当覆盖结束日；缺结束元数据仅当日是明确交易日时可用。
    retrospective默认按业务日期事后分析已回填数据；point_in_time按known_at过滤采集时间，
    known_at默认as_of且不能晚于as_of；该模式只表达本地采集已知，不伪造上游历史公告时刻。
    """
    cutoff = (_time(as_of) if isinstance(as_of, datetime) or isinstance(as_of, str) and "T" in as_of
              else datetime.combine(_date(as_of), time.max, TZ))
    if knowledge_mode not in {"retrospective", "point_in_time"}:
        raise ValueError("knowledge_mode只能为retrospective/point_in_time")
    if knowledge_mode == "retrospective" and known_at is not None:
        raise ValueError("known_at仅用于point_in_time模式")
    knowledge_cutoff = None
    if knowledge_mode == "point_in_time":
        knowledge_cutoff = (_time(known_at) if isinstance(known_at, datetime) or isinstance(known_at, str) and "T" in known_at
                            else datetime.combine(_date(known_at), time.max, TZ)) if known_at is not None else cutoff
        if knowledge_cutoff > cutoff:
            raise ValueError("point_in_time的known_at不能晚于as_of")
    code = etf.code if hasattr(etf, "code") else etf["code"]
    share_rows, bad_s = _rows(shares, code, "trade_date", cutoff, known_at=knowledge_cutoff)
    quote_rows, bad_q = _rows(quotes, code, "quote_time", cutoff, known_at=knowledge_cutoff)
    bar_rows, bad_b = _rows(bars, code, "time", cutoff, known_at=knowledge_cutoff)
    nav_rows, bad_n = _rows(navs, code, "trade_date", cutoff, known_at=knowledge_cutoff)
    market_rows, bad_m = _rows(market, code, "trade_date", cutoff, metric=True, known_at=knowledge_cutoff)
    # 未收盘不使用当日日频数据，防止未完成日线/日份额产生前视。
    intraday = cutoff.time() < time(15)
    daily_cutoff = cutoff.date() if not intraday else date.fromordinal(cutoff.date().toordinal() - 1)
    share_rows = [r for r in share_rows if r["trade_date"] <= daily_cutoff]
    nav_rows = [r for r in nav_rows if r["trade_date"] <= daily_cutoff]
    market_rows = [r for r in market_rows if r["trade_date"] <= daily_cutoff]
    daily_bars = [r for r in bar_rows if r.get("interval", "day") == "day" and r["time"].date() <= daily_cutoff]
    try:
        if isinstance(calendar, dict):
            calendar_start = calendar_start or calendar.get("start")
            calendar_end = calendar_end or calendar.get("end")
            calendar = calendar.get("days", [])
        all_days = sorted({_date(d) for d in calendar or []})
        days = [d for d in all_days if d <= daily_cutoff]
        covered_start = _date(calendar_start) if calendar_start is not None else min(all_days) if all_days else None
        covered_end = _date(calendar_end) if calendar_end is not None else None
        calendar_covered = bool(days and covered_start is not None and covered_start <= daily_cutoff
                                and (covered_end is not None and covered_end >= daily_cutoff
                                     or covered_end is None and daily_cutoff in all_days))
        if covered_start and covered_end and (covered_start > covered_end or any(not covered_start <= d <= covered_end for d in all_days)):
            calendar_covered = False
    except (ValueError, TypeError):
        days, covered_start, covered_end, calendar_covered = [], None, None, False
    indexes = {d: i for i, d in enumerate(days)}
    nav_map = {r["trade_date"]: r for r in nav_rows}
    bar_map = {r["time"].date(): r for r in daily_bars}
    history = []
    previous = None
    for row in share_rows:
        day = row["trade_date"]
        quantity = _usable(row, "shares")
        nav = _usable(nav_map.get(day), "nav", positive=True)
        old_quantity = _usable(previous, "shares")
        reason = None
        delta = pct = flow = None
        quality = row.get("quality", "valid")
        if quantity is None:
            reason, quality = "份额缺失或源质量不可用", "suspect"
        elif previous is None:
            reason = "缺少前一交易日基线"
        elif not days:
            reason = "未提供真实交易日历，不能证明相邻交易日"
        elif not calendar_covered:
            reason = "日历覆盖结束未知或未覆盖as_of，不能将末交易日当作今日边界"
        elif day not in indexes or previous["trade_date"] not in indexes:
            reason = "日历未覆盖份额日期"
        elif indexes[day] - indexes[previous["trade_date"]] != 1:
            reason = "交易日份额断档，不将跨期变化冒充日流量"
        elif old_quantity is None or old_quantity <= 0:
            reason = "基线份额为零或质量不可用"
        else:
            ratio = quantity / old_quantity
            old_nav = _usable(nav_map.get(previous["trade_date"]), "nav", positive=True)
            old_price = _usable(bar_map.get(previous["trade_date"]), "close", positive=True)
            new_price = _usable(bar_map.get(day), "close", positive=True)
            inverse = (old_nav is not None and nav is not None and abs(ratio * nav / old_nav - 1) <= 0.08
                       or old_price is not None and new_price is not None and abs(ratio * new_price / old_price - 1) <= 0.08)
            if ratio >= 1.5 or ratio <= 2 / 3:
                quality = "suspect"
                reason = "份额与NAV/未复权价格反向同比例变化，疑似拆分" if inverse else "份额异常跃迁，需核验拆分/合并或源单位"
            else:
                delta = _finite(quantity - old_quantity)
                pct = _finite((ratio - 1) * 100)
                if nav is None:
                    reason = "缺少同日有效单位净值，不用收盘价/前日NAV替代"
                else:
                    flow = _finite(delta * nav) if delta is not None else None
                    if flow is None:
                        reason, quality = "数值溢出", "suspect"
        if reason and quality not in {"suspect", "error", "missing", "stale"}:
            quality = "partial" if quality != "demo" else "demo"
        history.append({"date": day.isoformat(), "code": code, "shares": quantity,
                        "delta_shares": delta, "delta_pct": pct, "nav": nav,
                        "estimated_flow": flow, "quality": quality, "reason": reason})
        previous = row
    latest = history[-1] if history else None
    stale = bool(latest and days and _date(latest["date"]) < days[-1])

    def rolling(count):
        """功能：严格连续交易日滚动流量；输入：窗口长度；输出：完整流量和或None。"""
        if not calendar_covered or stale or len(history) < count or not days:
            return None
        window = history[-count:]
        expected = days[max(0, indexes.get(_date(window[-1]["date"]), -1) - count + 1):indexes.get(_date(window[-1]["date"]), -1) + 1]
        if len(expected) != count or [r["date"] for r in window] != [d.isoformat() for d in expected]:
            return None
        if any(r["estimated_flow"] is None or r["quality"] not in GOOD for r in window):
            return None
        return _finite(sum(r["estimated_flow"] for r in window))

    flow5, flow20 = rolling(5), rolling(20)
    share_trend = None
    if not stale and len(history) >= 6 and all(r["delta_pct"] is not None and r["quality"] in GOOD for r in history[-5:]):
        baseline = history[-6]["shares"]
        if baseline and latest["shares"] is not None:
            share_trend = _finite((latest["shares"] / baseline - 1) * 100)
    flow_strength = None
    if flow5 is not None and len(history) >= 6:
        baseline = history[-6]["shares"]
        baseline_nav = history[-6]["nav"]
        if baseline and baseline_nav:
            flow_strength = _finite(flow5 / (baseline * baseline_nav) * 100)
    price_trend = None
    if len(daily_bars) >= 21:
        last_price = _usable(daily_bars[-1], "close", positive=True)
        baseline_price = _usable(daily_bars[-21], "close", positive=True)
        price_days = [r["time"].date() for r in daily_bars[-21:]]
        split_dates = {_date(r["date"]) for r in history if r["quality"] == "suspect"}
        if calendar_covered and days and price_days == days[-21:] and not split_dates.intersection(price_days) and last_price and baseline_price:
            price_trend = _finite((last_price / baseline_price - 1) * 100)
    liquidity = None
    if calendar_covered and len(daily_bars) >= 25 and days and [r["time"].date() for r in daily_bars[-25:]] == days[-25:]:
        values = [_usable(r, "amount") for r in daily_bars[-25:]]
        if all(v is not None for v in values) and mean(values[:20]) > 0:
            liquidity = _finite(mean(values[-5:]) / mean(values[:20]))
    market_value = None
    by_metric = {name: [r for r in market_rows if r.get("metric") == name] for name in ("turnover", "margin")}
    turnover, margin = by_metric["turnover"], by_metric["margin"]
    if calendar_covered and len(turnover) >= 21 and len(margin) >= 6 and days:
        turn_values = [_usable(r, "value") for r in turnover[-21:]]
        old_margin, new_margin = _usable(margin[-6], "value"), _usable(margin[-1], "value")
        if ([r["trade_date"] for r in turnover[-21:]] == days[-21:]
                and [r["trade_date"] for r in margin[-6:]] == days[-6:]
                and all(v is not None for v in turn_values) and mean(turn_values[:-1]) > 0 and old_margin and new_margin is not None):
            market_value = _finite(((turn_values[-1] / mean(turn_values[:-1]) - 1) * 100
                                    + (new_margin / old_margin - 1) * 100) / 2)
    indicators = [
        _indicator("份额趋势", share_trend, _points(share_trend), "5交易日份额变化%；50+变化%×10，限制0~100；断档/异常为未知，不代表机构买卖。"),
        _indicator("NAV估计流量", flow_strength, _points(flow_strength), "5日Σ(份额差×同日NAV)/窗口前规模%；50+变化%×10。缺NAV不替代。"),
        _indicator("价格趋势", price_trend, _points(price_trend, 3), "20交易日未复权收盘涨跌%；50+涨跌%×3，不保证未来收益。"),
        _indicator("ETF流动性", liquidity, _points(None if liquidity is None else liquidity - 1, 30), "近5日均成交额/前20日均成交额；50+(倍数−1)×30。活跃不等于净买入。"),
        _indicator("市场环境", market_value, _points(market_value, 2), "市场成交额相对前20日变化%与5日融资余额变化%的均值；50+均值×2，非ETF直接资金。"),
    ]
    if intraday:
        # 当前接口五指标全部为已完成日频证据，盘中不得把昨日规则分冒认当日信号。
        indicators = [_indicator(indicator["name"], None, None,
                      "盘中不生成当日评分；可查看已完成日频历史。" + indicator["explanation"])
                      for indicator in indicators]
    known = [r["points"] for r in indicators if r["points"] is not None]
    coverage = len(known) / 5 * 100
    # 未知指标保留固定权重并回到中性50，不把剩余证据重新放大为满权重。
    score = _finite(50 + sum((value - 50) * 0.2 for value in known)) if known else None
    label = "证据不足" if coverage < 60 else "偏强" if score >= 65 else "偏弱" if score <= 35 else "中性"
    quote = quote_rows[-1] if quote_rows else None
    quote_price = _usable(quote, "price", positive=True)
    fallback = daily_bars[-1] if daily_bars else None
    price = quote_price if quote_price is not None else _usable(fallback, "close", positive=True)
    premium = None
    if quote_price is not None:
        iopv = _usable(quote, "iopv", positive=True)
        if iopv:
            premium = _finite((quote_price / iopv - 1) * 100)
    qualities = [r.get("quality", "valid") for r in share_rows + quote_rows + daily_bars + nav_rows + market_rows]
    active_session = time(9, 30) <= cutoff.time() <= time(11, 30) or time(13) <= cutoff.time() < time(15)
    quote_age_seconds = (cutoff - quote["quote_time"]).total_seconds() if quote else None
    quote_stale = bool(quote and (quote.get("quality") == "stale"
                       or quote["quote_time"].date() < (days[-1] if days else daily_cutoff)
                       or active_session and (quote_age_seconds is None or quote_age_seconds > 120)))
    price_stale = bool(quote_price is None and fallback and
                       fallback["time"].date() < (days[-1] if days else daily_cutoff))
    if quote_stale:
        premium = None
    quality = ("missing" if not history and price is None else "suspect" if any((bad_s, bad_q, bad_b, bad_n, bad_m)) or latest and latest["quality"] == "suspect"
               else "stale" if stale or quote_stale or price_stale
               else "demo" if "demo" in qualities else "partial" if coverage < 100 else "valid")
    intraday_indicators = []
    if calendar_covered and not quote_stale and quote_price is not None:
        clean_bars = [row for row in daily_bars[-60:] if _usable(row, "high", positive=True) is not None and _usable(row, "low", positive=True) is not None]
        if len(clean_bars) >= 20:
            high, low = max(row["high"] for row in clean_bars), min(row["low"] for row in clean_bars)
            position = _finite((quote_price - low) / (high - low) * 100) if high > low else None
            intraday_indicators.append(_indicator("盘中价格位置", position, None if position is None else max(0, min(100, 100 - position)), "当前价在已完成历史区间的位置；低位仅是位置线索，不代表已申购。"))
        current_amount = _usable(quote, "amount")
        reference_amounts = [_usable(row, "amount") for row in daily_bars[-20:]]
        elapsed = min(240, max(0, (cutoff.hour * 60 + cutoff.minute - 570)))
        if cutoff.time() >= time(13):
            elapsed = min(240, max(0, cutoff.hour * 60 + cutoff.minute - 660))
        if elapsed > 0 and len(reference_amounts) == 20 and all(value is not None for value in reference_amounts) and mean(reference_amounts) > 0:
            # 当前缺同时间历史快照，用线性进度估算只作辅助，不进入主评分。
            ratio = current_amount / (mean(reference_amounts) * elapsed / 240) if current_amount is not None else None
            prior = _usable(quote, "previous_close", positive=True)
            direction = _finite((quote_price / prior - 1) * 100) if prior else None
            points = _points(direction, min(10, ratio * 3)) if ratio is not None else None
            item = _indicator("盘中量价线索（估算）", ratio, points, "累计成交额与日均额×线性交易进度比较；非同时间历史基线，明确估算，不纳入日评分。")
            item["quality"], item["direction_pct"] = "partial", direction
            intraday_indicators.append(item)
    return {"latest_shares": latest["shares"] if latest else None,
            "share_date": latest["date"] if latest else None,
            "delta_shares": latest["delta_shares"] if latest and not stale else None,
            "delta_pct": latest["delta_pct"] if latest and not stale else None,
            "estimated_flow": latest["estimated_flow"] if latest and not stale else None,
            "flow_5d": flow5, "flow_20d": flow20, "price": price,
            "quote_time": quote["quote_time"].isoformat() if quote_price is not None else None,
            "price_time": (quote["quote_time"].isoformat() if quote_price is not None else fallback["time"].isoformat() if price is not None else None),
            "premium_pct": premium, "quality": quality, "score": score,
            "coverage": coverage, "label": label, "indicators": indicators, "intraday_indicators": intraday_indicators,
            "quote_age_seconds": quote_age_seconds, "history": history,
            "indicator_as_of": daily_cutoff.isoformat(),
            "session": "intraday" if intraday else "completed_daily",
            "knowledge_mode": knowledge_mode,
            "known_at": knowledge_cutoff.isoformat() if knowledge_cutoff is not None else None,
            "calendar_coverage": {"status": "valid" if calendar_covered else "unknown",
                                  "start": covered_start.isoformat() if covered_start else None,
                                  "end": covered_end.isoformat() if covered_end else None},
            "notice": ("规则评分不是概率、投资建议或机构身份识别；流量为日份额×准确NAV估计，非盘中实测申赎。"
                       + ("盘中五项日频指标未知，不显示当日评分；份额/流量仅是已完成历史日数据。" if intraday else "")
                       + ("事后历史分析包含后补数据，不代表当时已知。" if knowledge_mode == "retrospective"
                          else "时点分析仅使用known_at前本地已采集数据。"))}
