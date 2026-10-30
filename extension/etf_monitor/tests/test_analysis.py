"""纯分析测试：固定交易日、单位与时钟，不联网。"""
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pytest

from etf_monitor.analysis import analyse_etf, known_holders, _finite, _date, _time
from etf_monitor.models import ETF

TZ = ZoneInfo("Asia/Shanghai")
ETF_A = ETF(code="510300", name="沪深300ETF", exchange="sh", group="宽基")
DAY = date(2026, 4, 1)
STAMP = datetime(2026, 3, 1, tzinfo=TZ)


def dataset(count=30):
    """功能：生成固定全证据样本；输入：天数；输出：日历和5类原始字典列表。"""
    days = [DAY + timedelta(days=i) for i in range(45) if (DAY + timedelta(days=i)).weekday() < 5][:count]
    shares, navs, bars, market = [], [], [], []
    for i, day in enumerate(days):
        common = {"code": ETF_A.code, "source": "test", "fetched_at": STAMP, "quality": "valid"}
        shares.append({**common, "trade_date": day, "shares": 1000 + i * 10})
        navs.append({**common, "trade_date": day, "nav": 2})
        bars.append({**common, "time": datetime.combine(day, datetime.min.time(), TZ).replace(hour=15),
                     "interval": "day", "close": 2 + i / 100, "amount": 10000 + i * 100})
        market.extend({"source": "test", "fetched_at": STAMP, "quality": "valid", "trade_date": day,
                       "metric": metric, "value": value} for metric, value in
                      (("turnover", 1e10 + i * 1e8), ("margin", 1e12 + i * 1e9)))
    return days, shares, navs, bars, market


def analyse(data, **kwargs):
    """功能：调用固定样本分析；输入：数据及覆盖参数；输出：结果。"""
    days, shares, navs, bars, market = data
    return analyse_etf(ETF_A, shares, kwargs.pop("quotes", []), bars, navs, market,
                       kwargs.pop("as_of", days[-1]), calendar=kwargs.pop("calendar", days), **kwargs)


def test_complete_formula_and_explainability():
    """功能：验证准确NAV公式及五指标；输入：完整样本；输出：全部证据覆盖断言。"""
    result = analyse(dataset())
    assert result["latest_shares"] == 1290
    assert result["delta_shares"] == 10
    assert result["estimated_flow"] == 20
    assert result["flow_5d"] == 100
    assert result["flow_20d"] == 400
    assert result["coverage"] == 100
    assert 0 <= result["score"] <= 100
    assert result["quality"] == "valid"
    assert len(result["indicators"]) == 5
    assert all(i["explanation"] and i["state"] != "unknown" for i in result["indicators"])
    assert "不是概率" in result["notice"]
    json.dumps(result, allow_nan=False)


def test_empty_json_unknown():
    """功能：验证无数据不填零；输入：空列表；输出：未知和可序列化。"""
    result = analyse_etf(ETF_A, [], [], [], [], [], DAY)
    assert result["quality"] == "missing"
    assert result["score"] is None and result["coverage"] == 0
    assert result["latest_shares"] is None
    assert result["flow_5d"] is None
    assert result["label"] == "证据不足"
    assert all(i["state"] == "unknown" for i in result["indicators"])
    json.dumps(result, allow_nan=False)


def test_no_calendar_and_no_nav_do_not_substitute_price():
    """功能：缺日历/NAV拒绝伪日流量；输入：价格和不完整记录；输出：None。"""
    data = dataset()
    result = analyse(data, calendar=[])
    assert result["delta_shares"] is None and result["estimated_flow"] is None
    assert "日历" in result["history"][-1]["reason"]
    data[2].pop()
    result = analyse(data)
    assert result["delta_shares"] == 10 and result["estimated_flow"] is None
    assert result["flow_5d"] is None
    assert "同日" in result["history"][-1]["reason"]


def test_missing_session_and_stale():
    """功能：检查断档与陈旧份额；输入：缺中间/末日份额；输出：无滚动伪流量。"""
    data = dataset()
    data[1].pop(-2)
    result = analyse(data)
    assert result["estimated_flow"] is None
    assert "断档" in result["history"][-1]["reason"]
    data = dataset()
    data[1].pop()
    result = analyse(data)
    assert result["quality"] == "stale"
    assert result["flow_5d"] is None and result["delta_pct"] is None


def test_weekend_is_not_gap():
    """功能：休市不算断档；输入：周五周一真实日历；输出：可用流量。"""
    data = dataset(6)
    assert analyse(data)["flow_5d"] == 100


@pytest.mark.parametrize("reverse_nav", [True, False])
def test_split_and_unexplained_scale(reverse_nav):
    """功能：识别拆分与异常单位跃迁；输入：翻倍份额及反向NAV；输出：suspect。"""
    data = dataset()
    data[1][-1]["shares"] = data[1][-2]["shares"] * 2
    if reverse_nav:
        data[2][-1]["nav"] = 1
    result = analyse(data)
    assert result["quality"] == "suspect"
    assert result["estimated_flow"] is None and result["delta_pct"] is None
    assert "拆分" in result["history"][-1]["reason"] or "跃迁" in result["history"][-1]["reason"]


def test_split_via_price_and_zero_baseline():
    """功能：未复权价格检测拆分并拒绝零基线；输入：价格减半；输出：未知。"""
    data = dataset()
    data[1][-1]["shares"] = data[1][-2]["shares"] * 2
    data[3][-1]["close"] = data[3][-2]["close"] / 2
    assert "疑似拆分" in analyse(data)["history"][-1]["reason"]
    data = dataset()
    data[1][-2]["shares"] = 0
    assert "基线" in analyse(data)["history"][-1]["reason"]


@pytest.mark.parametrize("field,value", [("shares", float("nan")), ("shares", float("inf")), ("shares", -5), ("quality", "suspect"), ("quality", "missing")])
def test_bad_share_never_nan(field, value):
    """功能：过滤无效份额；输入：非有限值/异常质量；输出：JSON安全未知。"""
    data = dataset()
    data[1][-1][field] = value
    result = analyse(data)
    assert result["latest_shares"] is None and result["estimated_flow"] is None
    assert result["quality"] == "suspect"
    json.dumps(result, allow_nan=False)


def test_future_records_and_foreign_code_ignored():
    """功能：保证时点过滤；输入：未来NAV/报价和其他ETF；输出：原始样本不变。"""
    data = dataset()
    cutoff = data[0][-1]
    data[1].append({**data[1][-1], "trade_date": cutoff + timedelta(days=1), "shares": 999999})
    data[1].append({**data[1][-2], "code": "159919", "shares": 999999})
    data[2].append({**data[2][-1], "trade_date": cutoff + timedelta(days=1), "nav": 900})
    quotes = [{"code": ETF_A.code, "quote_time": datetime.combine(cutoff + timedelta(days=1), datetime.min.time(), TZ), "price": 999}]
    assert analyse(data, quotes=quotes)["latest_shares"] == 1290
    assert analyse(data, quotes=quotes)["price"] == pytest.approx(2.29)


def test_future_fetch_and_intraday_daily_filter():
    """功能：不使用尚未获得记录及未收盘日线；输入：盘中截止时刻；输出：前日份额。"""
    data = dataset()
    as_of = datetime.combine(data[0][-1], datetime.min.time(), TZ).replace(hour=10)
    result = analyse(data, as_of=as_of)
    assert result["latest_shares"] == 1280
    assert len(result["history"]) == 29
    data[1][-1]["fetched_at"] = as_of + timedelta(days=1)
    assert analyse(data)["latest_shares"] == 1290  # 默认事后分析允许回填。
    assert analyse(data, knowledge_mode="point_in_time")["latest_shares"] == 1280


def test_quote_premium_is_iopv_not_stale_nav():
    """功能：溢价必须同时点IOPV；输入：快照/NAV；输出：正确比例或未知。"""
    data = dataset()
    stamp = datetime.combine(data[0][-1], datetime.min.time(), TZ).replace(hour=14)
    quotes = [{"code": ETF_A.code, "quote_time": stamp, "price": 3, "iopv": 2.5, "premium_pct": 999, "quality": "valid"}]
    result = analyse(data, quotes=quotes)
    assert result["price"] == 3
    assert result["premium_pct"] == pytest.approx(20)
    assert "+08:00" in result["quote_time"]
    quotes[0].pop("iopv")
    assert analyse(data, quotes=quotes)["premium_pct"] is None
    quotes[0]["quality"] = "stale"
    assert analyse(data, quotes=quotes)["quality"] == "stale"


def test_duplicate_conflicts_and_malformed_rows():
    """功能：同日冲突不做证据；输入：矛盾、非法字段；输出：suspect。"""
    data = dataset()
    data[1].append({**data[1][-1], "shares": 1300})
    data[1].append({"code": ETF_A.code, "trade_date": "不是日期"})
    assert analyse(data)["quality"] == "suspect"
    assert analyse(data)["estimated_flow"] is None


def test_calendar_boundary_and_short_windows():
    """功能：短窗口/覆盖不全不计算滚动；输入：少日历；输出：未知。"""
    data = dataset(3)
    assert analyse(data)["flow_5d"] is None
    assert analyse(data, calendar=data[0][:-1])["estimated_flow"] is None
    assert "日历" in analyse(data, calendar=data[0][:-1])["history"][-1]["reason"]
    assert analyse(data, calendar=["invalid"])["estimated_flow"] is None


def test_demo_quality_and_models_input():
    """功能：模型与字典均可输入；输入：demo模型；输出：明确demo。"""
    from etf_monitor.models import ShareRecord
    data = dataset()
    data[1][0]["quality"] = "demo"
    data[1][0] = ShareRecord(**data[1][0])
    assert analyse(data)["quality"] == "demo"
    assert analyse_etf(ETF_A.model_dump(), [], [], [], [], [], "20260401")["coverage"] == 0


def test_known_holders_publication_gate():
    """功能：未知公告不用于历史；输入：持有人报告与公告；输出：仅截止前已公告。"""
    rows = [{"report_date": "2026-03-31", "published_on": d} for d in (None, "2026-04-15", "2026-05-01", "2026-03-01", "bad")]
    assert known_holders(rows, "2026-04-20") == [rows[1]]
    from etf_monitor.models import HolderRecord
    holder = HolderRecord(code=ETF_A.code, holder="机构A", report_date=date(2026, 3, 31), published_on=date(2026, 4, 15), source="test", fetched_at=STAMP)
    assert known_holders([holder], "2026-04-20") == [holder]


@pytest.mark.parametrize("value,expected", [(None, None), ("bad", None), (float("inf"), None), ("3", 3)])
def test_normalization(value, expected):
    """功能：校验纯函数数值边界；输入：原值；输出：有限或未知。"""
    assert _finite(value) == expected
    assert _date("20260401") == DAY
    assert _date(datetime(2026, 4, 1)) == DAY
    assert _time("2026-04-01T01:00:00Z").hour == 9
    assert _time(datetime(2026, 4, 1)).tzinfo == TZ


def test_negative_signals_and_zero_market_liquidity():
    """功能：负趋势与零分母不误判；输入：连续下行及零成交额；输出：偏弱或未知。"""
    data = dataset()
    for i, row in enumerate(data[1]):
        row["shares"] = 2000 - i * 20
    for i, row in enumerate(data[3]):
        row["close"] = 4 - i * .05
        row["amount"] = 10000 - i * 200
    result = analyse(data)
    assert result["delta_shares"] == -20 and result["estimated_flow"] == -40
    assert result["indicators"][0]["state"] == "negative"
    for row in data[3]:
        row["amount"] = 0
    for row in data[4]:
        row["value"] = 0
    result = analyse(data)
    assert result["indicators"][3]["state"] == "unknown"
    assert result["indicators"][4]["state"] == "unknown"
