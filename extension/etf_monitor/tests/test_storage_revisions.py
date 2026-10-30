"""独立审查回归：知识时点修订与交易日历覆盖事务。"""
from datetime import timedelta

import pytest

from etf_monitor.config import default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.storage import Repository


def test_known_at_selects_original_then_each_revision(tmp_path):
    """功能：历史知识时点恢复旧版本；输入：多次修订样本；输出：不泄漏未来修订断言。"""
    repo = Repository(tmp_path / "audit.sqlite")
    repo.initialize()
    original = DemoProvider().shares(DEMO_NOW.date(), DEMO_NOW.date(), default_etfs()[:1])[0]
    original = original.model_copy(update={"quality": "valid"})
    first, second, third = DEMO_NOW, DEMO_NOW + timedelta(days=1), DEMO_NOW + timedelta(days=2)
    repo.save_records({"shares": [original]}, first)
    # 修订源可能继续给出旧fetched_at，必须用本地提交时刻防止向过去泄漏。
    corrected = original.model_copy(update={"shares": original.shares + 100})
    repo.save_records({"shares": [corrected]}, second)
    final = original.model_copy(update={"shares": original.shares + 200})
    repo.save_records({"shares": [final]}, third)
    assert repo.records("shares", known_at=first - timedelta(seconds=1)) == []
    assert repo.records("shares", known_at=first)[0].shares == original.shares
    assert repo.records("shares", known_at=second - timedelta(seconds=1))[0].shares == original.shares
    assert repo.records("shares", known_at=second)[0].shares == corrected.shares
    assert repo.records("shares", known_at=third)[0].shares == final.shares
    assert repo.records("shares", known_at=third, day_known=True)[0].shares == original.shares
    assert repo.records("shares")[0].shares == final.shares
    assert repo.revision_count() == 2
    with pytest.raises(ValueError):
        repo.records("shares", known_at=first.replace(tzinfo=None))
    reopened = Repository(repo.path)
    reopened.initialize()
    assert reopened.records("shares", known_at=first)[0].shares == original.shares


def test_backfilled_original_not_known_before_local_save(tmp_path):
    """功能：旧采集时刻不能伪造本地已知；输入：后补样本；输出：PIT严格过滤断言。"""
    repo = Repository(tmp_path / "backfill.sqlite")
    repo.initialize()
    record = DemoProvider().shares(DEMO_NOW.date(), DEMO_NOW.date(), default_etfs()[:1])[0]
    record = record.model_copy(update={"quality": "valid"})
    saved = DEMO_NOW + timedelta(days=7)
    repo.save_records({"shares": [record]}, saved)
    assert repo.records("shares", known_at=DEMO_NOW) == []
    assert repo.records("shares", known_at=saved)[0] == record


def test_calendar_coverage_gaps_weekend_and_atomic_rollback(tmp_path):
    """功能：覆盖以请求区间而非最后交易日证明；输入：周末和覆盖缺口；输出：原子断言。"""
    repo = Repository(tmp_path / "calendar.sqlite")
    repo.initialize()
    day = DEMO_NOW.date()
    repo.save_calendar([day])
    assert not repo.calendar_covers(day, day)
    repo.save_calendar([day], start=day, end=day + timedelta(days=2), source="exchange", fetched_at=DEMO_NOW)
    assert repo.calendar_covers(day, day + timedelta(days=2))
    assert not repo.calendar_covers(day, day + timedelta(days=3))
    assert not repo.calendar_covers(day, day, known_at=DEMO_NOW - timedelta(seconds=1))
    repo.save_calendar([], start=day + timedelta(days=4), end=day + timedelta(days=5), source="exchange", fetched_at=DEMO_NOW)
    assert not repo.calendar_covers(day, day + timedelta(days=5))
    repo.save_calendar([], start=day + timedelta(days=3), end=day + timedelta(days=3), source="exchange", fetched_at=DEMO_NOW)
    assert repo.calendar_covers(day, day + timedelta(days=5))
    with pytest.raises(ValueError):
        repo.save_calendar([day], start=day, end=day, source="exchange")
    with repo.connection() as db:
        db.execute("CREATE TRIGGER reject_cover BEFORE INSERT ON calendar_coverage BEGIN SELECT RAISE(ABORT,'coverage failure'); END")
    records = DemoProvider().shares(day, day, default_etfs()[:1])
    with pytest.raises(Exception, match="coverage failure"):
        repo.save_records({"shares": records}, DEMO_NOW, calendar=[day], calendar_request=(day, day, "other"))
    assert repo.records("shares") == []
