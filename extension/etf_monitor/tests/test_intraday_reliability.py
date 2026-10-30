"""盘中陈旧/独立线索与固定权重回归。"""
from datetime import datetime

from test_analysis import analyse, dataset, TZ


def test_fixed_weights_do_not_amplify_missing_indicators():
    """功能：未知权重不重新分配；输入：只有份额趋势；输出：不被放大为满分。"""
    data = dataset()
    data[2].clear()
    data[3].clear()
    data[4].clear()
    result = analyse(data)
    points = [item["points"] for item in result["indicators"] if item["points"] is not None]
    assert result["score"] == 50 + sum((point - 50) * .2 for point in points)
    assert result["coverage"] < 100


def test_same_day_old_quote_is_stale():
    """功能：同一天旧行情不能冒充实时；输入：盘中一小时前行情；输出：陈旧。"""
    data = dataset()
    now = datetime.combine(data[0][-1], datetime.min.time(), TZ).replace(hour=10)
    # 显式构造行情快照，数据集只提供日份额、净值、日线及市场数据。
    from etf_monitor.analysis import analyse_etf
    from test_analysis import ETF_A
    quote = {"code": ETF_A.code, "source": "fixture", "fetched_at": now, "quality": "valid", "quote_time": now.replace(hour=9), "price": 2.0, "amount": 100}
    result = analyse_etf(ETF_A, data[1], [quote], data[3], data[2], [], now,
                         calendar=data[0], calendar_start=data[0][0], calendar_end=now.date())
    assert result["quality"] == "stale"
    assert result["quote_age_seconds"] == 3600
    assert result["intraday_indicators"] == []


def test_intraday_evidence_kept_separate_from_daily_score():
    """功能：盘中辅助不改日评分；输入：有效盘中快照；输出：独立线索与未知日分。"""
    from etf_monitor.analysis import analyse_etf
    from test_analysis import ETF_A
    data = dataset()
    now = datetime.combine(data[0][-1], datetime.min.time(), TZ).replace(hour=10)
    quote = {"code": ETF_A.code, "source": "fixture", "fetched_at": now, "quality": "valid", "quote_time": now, "price": 2.0, "previous_close": 1.9, "amount": 100}
    bars = [dict(row, high=row["close"] + .1, low=row["close"] - .1) for row in data[3]]
    result = analyse_etf(ETF_A, data[1], [quote], bars, data[2], data[4], now,
                         calendar=data[0], calendar_start=data[0][0], calendar_end=now.date())
    assert result["score"] is None
    assert result["session"] == "intraday"
    assert len(result["intraday_indicators"]) >= 1
