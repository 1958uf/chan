"""仓储测试：临时库、事务、唯一键与数据修订。"""
from datetime import timedelta

import pytest

from etf_monitor.config import default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.storage import Repository


def repository(tmp_path):
    """功能：构造测试库；输入：临时目录；输出：初始化仓储。"""
    repo = Repository(tmp_path / "unit.sqlite")
    repo.initialize()
    return repo


def test_initialize_wal_and_constructor_no_write(tmp_path):
    """功能：验证惰性创建及WAL；输入：临时目录；输出：断言。"""
    repo = Repository(tmp_path / "nested" / "unit.sqlite")
    assert not repo.path.exists()
    repo.initialize()
    with repo.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    repo.put_etfs(default_etfs()[:2])
    repo.put_etfs(default_etfs()[:1])
    assert len(repo.etfs()) == 2


def test_idempotence_revision_and_source_isolation(tmp_path):
    """功能：验证重试幂等和同业务修订审计；输入：临时库；输出：断言。"""
    repo = repository(tmp_path)
    provider = DemoProvider()
    records = provider.shares(DEMO_NOW.date(), DEMO_NOW.date(), default_etfs()[:1])
    assert repo.save_records({"shares": records}, DEMO_NOW) == 1
    assert repo.save_records({"shares": records}, DEMO_NOW) == 0
    retried = records[0].model_copy(update={"fetched_at": DEMO_NOW + timedelta(hours=1)})
    assert repo.save_records({"shares": [retried]}, DEMO_NOW) == 0
    corrected = records[0].model_copy(update={"shares": records[0].shares + 1})
    assert repo.save_records({"shares": [corrected]}, DEMO_NOW) == 1
    assert repo.revision_count() == 1
    other = records[0].model_copy(update={"source": "second-source"})
    repo.save_records({"shares": [other]}, DEMO_NOW)
    assert len(repo.records("shares")) == 2
    assert len(repo.records("shares", records[0].code, DEMO_NOW.date(), DEMO_NOW.date(), limit=1)) == 1
    assert repo.records("shares", codes=[]) == []
    assert len(repo.records("shares", codes=[records[0].code])) == 2
    with pytest.raises(ValueError):
        repo.records("unknown")
    with pytest.raises(ValueError):
        repo.records("shares", limit=10001)
    with pytest.raises(ValueError):
        repo.records("shares", offset=-1)


def test_atomic_validation_and_sql_rollback(tmp_path):
    """功能：验证批次全校验与SQL失败回滚；输入：临时库；输出：断言。"""
    repo = repository(tmp_path)
    provider, etf = DemoProvider(), default_etfs()[0]
    valid = provider.shares(DEMO_NOW.date(), DEMO_NOW.date(), [etf])
    with pytest.raises(ValueError):
        repo.save_records({"shares": valid + [{"code": "bad"}]}, DEMO_NOW)
    assert repo.records("shares") == []
    with repo.connection() as db:
        db.execute("CREATE TRIGGER reject_nav BEFORE INSERT ON records WHEN NEW.kind='navs' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
    with pytest.raises(Exception, match="test rollback"):
        repo.save_records({"shares": valid, "navs": provider.navs(etf, DEMO_NOW.date(), DEMO_NOW.date())}, DEMO_NOW)
    assert repo.records("shares") == []


def test_all_record_identities_calendar_and_documents(tmp_path):
    """功能：验证所有唯一键和受控文档表；输入：临时库；输出：断言。"""
    repo = repository(tmp_path)
    provider, etf = DemoProvider(), default_etfs()[0]
    day = DEMO_NOW.date()
    batches = {"shares": provider.shares(day, day, [etf]), "bars": provider.bars(etf, day, day),
               "quotes": provider.quotes([etf]), "navs": provider.navs(etf, day, day),
               "holders": provider.holders(etf), "market": provider.market(day, day)}
    assert repo.save_records(batches, DEMO_NOW) == 7
    assert repo.save_records(batches, DEMO_NOW) == 0
    repo.save_calendar([day, day])
    assert repo.is_trading_day(day)
    assert not repo.is_trading_day(day + timedelta(days=1))
    repo.put_document("metadata", "x", {"ok": True})
    assert repo.document("metadata", "x") == {"ok": True}
    assert repo.document("metadata", "missing") is None
    assert repo.documents("metadata") == [{"ok": True}]
    for operation in (lambda: repo.put_document("records", "x", {}), lambda: repo.document("records", "x"), lambda: repo.documents("records")):
        with pytest.raises(ValueError):
            operation()


def test_alert_cooldown_ack_and_restart(tmp_path):
    """功能：验证告警冷却持久化及幂等确认；输入：临时库；输出：断言。"""
    repo = repository(tmp_path)
    alert = {"id": "a", "created_at": DEMO_NOW.isoformat(), "acknowledged": False}
    assert repo.emit_alert(alert, "same", 60)
    assert not repo.emit_alert({**alert, "id": "b"}, "same", 60)
    later = {**alert, "id": "c", "created_at": (DEMO_NOW + timedelta(seconds=60)).isoformat()}
    assert repo.emit_alert(later, "same", 60)
    assert repo.acknowledge("a")
    assert repo.acknowledge("a")
    assert not repo.acknowledge("unknown")
    reopened = Repository(repo.path)
    assert len(reopened.alerts()) == 2
    assert reopened.alerts()[1]["acknowledged"]
