"""日份额告警相邻交易日、断档和异常分类回归。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from etf_monitor.config import Settings
from etf_monitor.models import ETF, ShareRecord
from etf_monitor.services import TaskManager
from etf_monitor.storage import Repository


@pytest.mark.parametrize("previous_day,current,quality,expected", [
    (date(2026, 10, 27), 110, "valid", "share_change"),
    (date(2026, 10, 26), 110, "valid", None),
    (date(2026, 10, 27), 300, "valid", "share_anomaly"),
    (date(2026, 10, 27), 110, "partial", None),
])
def test_alerts_not_mislabeled_across_gaps(tmp_path, previous_day, current, quality, expected):
    """功能：有效相邻日才报日变化；输入：断档/异常/质量；输出：准确告警种类。"""
    now = datetime(2026, 10, 28, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    repo = Repository(tmp_path / "alert.sqlite")
    repo.initialize()
    etf = ETF(code="510050", name="测试ETF", group="测试", exchange="sh")
    days = [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]
    repo.save_calendar(days, start=days[0], end=days[-1], source="fixture", fetched_at=now)
    repo.save_records({"shares": [ShareRecord(code=etf.code, trade_date=previous_day, shares=100, source="fixture", fetched_at=now), ShareRecord(code=etf.code, trade_date=days[-1], shares=current, quality=quality, source="fixture", fetched_at=now)]}, now)
    manager = TaskManager(repo, object(), Settings(data_dir=tmp_path), lambda: now)
    manager.check_share_alerts([etf])
    alerts = repo.alerts()
    assert [item["kind"] for item in alerts] == ([] if expected is None else [expected])
