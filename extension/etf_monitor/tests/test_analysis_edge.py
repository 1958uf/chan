"""分析边界补充测试，固定时点保证拆分不污染价格评分与分钟日线隔离。"""
from datetime import datetime, timedelta
import json

from etf_monitor.analysis import analyse_etf
from test_analysis import ETF_A, TZ, dataset, analyse


def test_split_price_score_unknown():
    """功能：拆分不能误标价格暴跌；输入：末日拆分；输出：价格趋势未知。"""
    data = dataset()
    data[1][-1]["shares"] = data[1][-2]["shares"] * 2
    data[3][-1]["close"] = data[3][-2]["close"] / 2
    result = analyse(data)
    assert result["indicators"][2]["state"] == "unknown"


def test_minute_bars_same_stamp_not_daily_conflict():
    """功能：分钟与日线同时间保留独立；输入：15点分钟价格不同；输出：日评分有效。"""
    data = dataset()
    data[3].append({**data[3][-1], "interval": "1m", "close": 2.3})
    result = analyse(data)
    assert result["coverage"] == 100 and result["quality"] == "valid"


def test_nav_invalid_and_future_fetch_do_not_fill():
    """功能：未公布/无效NAV不替代；输入：未来采集NAV；输出：无流量。"""
    data = dataset()
    data[2][-1]["fetched_at"] = datetime.combine(data[0][-1] + timedelta(days=1), datetime.min.time(), TZ)
    assert analyse(data)["estimated_flow"] == 20
    assert analyse(data, knowledge_mode="point_in_time")["estimated_flow"] is None
    data[2][-1].pop("fetched_at")
    data[2][-1]["nav"] = float("nan")
    result = analyse(data)
    assert result["estimated_flow"] is None
    json.dumps(result, allow_nan=False)


def test_unusable_baseline_and_corrupt_markets():
    """功能：异常基线不能产生日差，市场缺点不能满分；输入：质量错误和市场断档；输出：未知。"""
    data = dataset()
    data[1][-2]["quality"] = "error"
    assert analyse(data)["estimated_flow"] is None
    data = dataset()
    data[4].pop(-3)
    assert analyse(data)["indicators"][4]["state"] == "unknown"


def test_iso_asof_and_intraday_quote_only():
    """功能：ISO时间和盘中快照有明确边界；输入：少量盘中行情；输出：无日证据、可用价格。"""
    quotes = [{"code": ETF_A.code, "quote_time": "2026-04-01T10:00:00+08:00", "price": 2}]
    result = analyse_etf(ETF_A, [], quotes, [], [], [], "2026-04-01T10:01:00+08:00")
    assert result["price"] == 2 and result["share_date"] is None
    assert result["coverage"] == 0 and result["premium_pct"] is None
