"""日历实际覆盖与事后/PIT已知时点P1回归。"""
from datetime import datetime, timedelta

import pytest

from etf_monitor.analysis import analyse_etf
from test_analysis import dataset, analyse, ETF_A, TZ


def test_expired_calendar_cannot_score_valid_100():
    """功能：过期日历末交易日不能冒认当前边界；输入：旧日历+当前as_of；输出：unknown。"""
    data = dataset()
    result = analyse(data, as_of=data[0][-1] + timedelta(days=7),
                     calendar_start=data[0][0], calendar_end=data[0][-1])
    assert result["calendar_coverage"]["status"] == "unknown"
    assert result["coverage"] == 0 and result["score"] is None
    assert result["quality"] != "valid"
    assert result["estimated_flow"] is None
    assert all(i["state"] == "unknown" for i in result["indicators"])


def test_weekend_coverage_explicit_range_not_last_trade():
    """功能：周末靠已核验日历覆盖范围确定；输入：周五末日、周末截止；输出：可用/未知。"""
    data = dataset(28)
    last = data[0][-1]
    while last.weekday() != 4:
        data = dataset(len(data[0]) - 1)
        last = data[0][-1]
    weekend = last + timedelta(days=1)
    assert analyse(data, as_of=weekend)["calendar_coverage"]["status"] == "unknown"
    result = analyse(data, as_of=weekend, calendar_start=data[0][0], calendar_end=weekend)
    assert result["calendar_coverage"]["status"] == "valid"
    assert result["coverage"] == 100
    assert result["flow_5d"] == 100


def test_calendar_dict_metadata_supported_and_wrong_range_unknown():
    """功能：字典日历携范围、不合法范围降级；输入：元信息；输出：明确状态。"""
    data = dataset()
    result = analyse(data, calendar={"days": data[0], "start": data[0][0], "end": data[0][-1]})
    assert result["calendar_coverage"]["status"] == "valid"
    result = analyse(data, calendar_start=data[0][-1], calendar_end=data[0][0])
    assert result["calendar_coverage"]["status"] == "unknown"


def test_retrospective_backfill_not_empty_and_pit_empty():
    """功能：后补历史与时点回测分开；输入：采集晚于历史业务日；输出：事后完整、PIT未知。"""
    data = dataset()
    later = datetime.combine(data[0][-1] + timedelta(days=10), datetime.min.time(), TZ)
    for rows in data[1:]:
        for row in rows:
            row["fetched_at"] = later
    result = analyse(data)
    assert result["latest_shares"] == 1290 and result["flow_20d"] == 400
    assert result["knowledge_mode"] == "retrospective" and result["known_at"] is None
    assert "后补数据" in result["notice"]
    pit = analyse(data, knowledge_mode="point_in_time")
    assert pit["latest_shares"] is None and pit["price"] is None
    assert pit["knowledge_mode"] == "point_in_time" and pit["known_at"] is not None


def test_known_at_strict_and_missing_fetch_not_pit_evidence():
    """功能：PIT仅接受明确known_at前已采集；输入：不同采集时间/缺时间；输出：严格过滤。"""
    data = dataset()
    known = datetime(2026, 3, 15, tzinfo=TZ)
    data[1][-1]["fetched_at"] = known + timedelta(days=1)
    assert analyse(data, knowledge_mode="point_in_time", known_at=known)["latest_shares"] == 1280
    data[1][-1].pop("fetched_at")
    assert analyse(data, knowledge_mode="point_in_time", known_at=known)["latest_shares"] == 1280
    assert analyse(data)["latest_shares"] == 1290


def test_intraday_daily_score_not_pretend_current_signal():
    """功能：盘中不冒用昨日日频规则分；输入：完整历史及10点截止；输出：当日五指标未知。"""
    data = dataset()
    cutoff = datetime.combine(data[0][-1], datetime.min.time(), TZ).replace(hour=10)
    result = analyse(data, as_of=cutoff, calendar_start=data[0][0], calendar_end=data[0][-1])
    assert result["latest_shares"] == 1280
    assert result["history"][-1]["date"] == data[0][-2].isoformat()
    assert result["score"] is None and result["coverage"] == 0
    assert all(item["state"] == "unknown" and "盘中" in item["explanation"] for item in result["indicators"])
    assert result["session"] == "intraday" and result["indicator_as_of"] < data[0][-1].isoformat()
    assert "不显示当日评分" in result["notice"]


@pytest.mark.parametrize("kwargs", [{"knowledge_mode": "bad"}, {"known_at": "2026-04-01"},
    {"knowledge_mode": "point_in_time", "known_at": "2030-01-01"}])
def test_knowledge_mode_invalid_rejected(kwargs):
    """功能：错误分析语义不能默默接受；输入：无效模式；输出：ValueError。"""
    with pytest.raises(ValueError):
        analyse_etf(ETF_A, [], [], [], [], [], "2026-04-01", **kwargs)
