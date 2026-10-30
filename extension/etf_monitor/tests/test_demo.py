"""演示模式隔离、确定性与完整字段测试。"""
import pytest
from fastapi.testclient import TestClient

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider, seed_demo
from etf_monitor.main import create_app
from etf_monitor.storage import Repository


def test_deterministic_demo_provider_and_seed(tmp_path):
    """功能：验证自有样本稳定与重复seed无修订；输入：临时库；输出：断言。"""
    repository = Repository(tmp_path / "demo.sqlite")
    repository.initialize()
    etfs = default_etfs()[:2]
    assert seed_demo(repository, etfs)
    records = repository.records("shares")
    assert records and all(item.quality == "demo" and item.source == "demo-fixed-v1" for item in records)
    assert not seed_demo(repository, etfs)
    assert repository.revision_count() == 0
    assert records == repository.records("shares")
    bad = Repository(tmp_path / "live.sqlite")
    bad.initialize()
    with pytest.raises(ValueError, match="demo.sqlite"):
        seed_demo(bad, etfs)
    assert DemoProvider().quotes(etfs) == DemoProvider().quotes(etfs)


def test_demo_app_fixed_clock_and_live_database_isolation(tmp_path):
    """功能：验证mode显式切换不污染真实库；输入：临时目录；输出：断言。"""
    demo = create_app(Settings(data_dir=tmp_path, mode="demo", scheduler_enabled=True))
    with TestClient(demo, base_url="http://localhost:8765") as connection:
        health = connection.get("/api/health").json()
        assert health["mode"] == "demo" and health["now"] == DEMO_NOW.isoformat()
        assert not health["scheduler_enabled"]
        dashboard = connection.get("/api/dashboard").json()
        assert "演示" in dashboard["notice"]
        assert dashboard["etfs"] and dashboard["market"]
        detail = connection.get("/api/etfs/510050").json()
        for kind in ("shares", "quotes", "bars", "navs", "holders"):
            assert detail[kind]
            assert detail[kind][0]["source"] and detail[kind][0]["fetched_at"]
        token = connection.get("/api/session").json()["token"]
        assert connection.put("/api/settings", json={"scheduler_enabled": True}, headers={"Origin": "http://localhost:8765", "X-ETF-Token": token}).status_code == 422
    live = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(live, base_url="http://localhost:8765") as connection:
        assert live.state.repository.records("shares") == []
        assert connection.get("/api/dashboard").json()["mode"] == "live"
    assert (tmp_path / "demo.sqlite").exists() and (tmp_path / "live.sqlite").exists()
