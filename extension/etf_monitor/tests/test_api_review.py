"""独立审查回归：日历闭环、后补历史双口径及最新市场窗口。"""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.main import create_app
from etf_monitor.models import MarketRecord


def test_fresh_refresh_and_backfill_automatically_cover_calendar(tmp_path):
    """功能：新库无需手动日历即可完整分析；输入：无网络mock；输出：覆盖与流量断言。"""
    for kind in ("refresh", "backfill"):
        app = create_app(Settings(data_dir=tmp_path / kind), DemoProvider(), lambda: DEMO_NOW)
        with TestClient(app, base_url="http://localhost:8765"):
            app.state.settings.mode = "demo"  # 仅测试注入源允许demo，无自动seed。
            app.state.tasks.settings.mode = "demo"
            task = app.state.tasks.submit(kind, date(2025, 2, 17), DEMO_NOW.date(), codes=["510050"])
            app.state.tasks.pending.join()
            assert app.state.repository.document("tasks", task["id"])["status"] == "completed"
            assert app.state.repository.calendar_covers(date(2025, 2, 17), DEMO_NOW.date())
            from etf_monitor.api.routes import analyse
            result = analyse(app.state, default_etfs()[0])
            assert result["calendar_coverage"]["complete"]
            assert result["estimated_flow"] is not None
            assert result["flow_20d"] is not None


def test_stale_calendar_cannot_claim_valid_full_coverage(tmp_path):
    """功能：3月28日旧日历不能证明4月4日完整；输入：旧演示库与新时钟；输出：unknown断言。"""
    now = DEMO_NOW + timedelta(days=7)
    app = create_app(Settings(data_dir=tmp_path, mode="demo"), clock=lambda: now)
    with TestClient(app, base_url="http://localhost:8765") as client:
        data = client.get("/api/dashboard").json()["etfs"][0]
        assert not data["calendar_coverage"]["complete"]
        assert data["coverage"] == 0 and data["score"] is None
        assert data["quality"] != "valid"
        assert data["estimated_flow"] is None and data["flow_20d"] is None
        assert all(item["state"] == "unknown" for item in data["indicators"])


def test_retrospective_history_recovers_backfill_and_pit_excludes_it(tmp_path):
    """功能：后补历史事后可统计而PIT不泄漏；输入：旧业务日当前采集记录；输出：双口径断言。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as client:
        etf, provider = default_etfs()[0], DemoProvider()
        start, end = date(2025, 3, 24), date(2025, 3, 27)
        shares = [record.model_copy(update={"quality": "valid", "fetched_at": DEMO_NOW}) for record in provider.shares(start, end, [etf])]
        navs = [record.model_copy(update={"quality": "valid", "fetched_at": DEMO_NOW}) for record in provider.navs(etf, start, end)]
        app.state.repository.save_records({"shares": shares, "navs": navs}, DEMO_NOW,
                                          calendar=provider.calendar(start, end), calendar_request=(start, end, "mock-calendar"))
        query = "/api/history?group=上证50&start=2025-03-24&end=2025-03-27"
        retrospective = client.get(query).json()
        assert retrospective["knowledge_mode"] == "retrospective"
        assert "事后" in retrospective["notice"]
        assert retrospective["items"][0]["shares"] == shares[-1].shares
        assert retrospective["items"][0]["estimated_flow"] is not None
        assert client.get(query + "&knowledge_mode=point_in_time").json()["items"] == []
        assert client.get(query + "&known_at=2025-03-28T15:10:00").status_code == 422
        assert client.get(query + "&known_at=2030-01-01T00:00:00%2B08:00").status_code == 422
        assert client.get(query + "&knowledge_mode=invalid").status_code == 422


def test_historical_dashboard_uses_original_revision(tmp_path):
    """功能：历史看板选择旧版本非未来修订；输入：原份额与次日修订；输出：PIT断言。"""
    now = DEMO_NOW + timedelta(days=1)
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: now)
    with TestClient(app, base_url="http://localhost:8765") as client:
        original = DemoProvider().shares(DEMO_NOW.date(), DEMO_NOW.date(), default_etfs()[:1])[0]
        original = original.model_copy(update={"quality": "valid"})
        app.state.repository.save_records({"shares": [original]}, DEMO_NOW)
        revised = original.model_copy(update={"shares": original.shares + 1_000_000})
        app.state.repository.save_records({"shares": [revised]}, now)
        historical = client.get("/api/dashboard?as_of=2025-03-28").json()["etfs"]
        record = next(item for item in historical if item["code"] == original.code)
        assert record["latest_shares"] == original.shares
        current = client.get("/api/dashboard").json()["etfs"]
        assert next(item for item in current if item["code"] == original.code)["latest_shares"] == revised.shares
        history = client.get("/api/history?group=上证50&start=2025-03-28&end=2025-03-28&knowledge_mode=point_in_time").json()
        assert history["items"][0]["shares"] == original.shares


def test_dashboard_market_keeps_latest_fifty_of_sixty_days(tmp_path):
    """功能：市场窗口优先最新而非最早50日；输入：60天双指标；输出：日期范围断言。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as client:
        start = DEMO_NOW.date() - timedelta(days=59)
        records = [MarketRecord(trade_date=start + timedelta(days=index), metric=metric,
                                value=1000 + index, source="mock-market", fetched_at=DEMO_NOW)
                   for index in range(60) for metric in ("turnover", "margin")]
        app.state.repository.save_records({"market": records}, DEMO_NOW)
        market = client.get("/api/dashboard").json()["market"]
        assert len(market) == 100
        assert market[0]["trade_date"] == DEMO_NOW.date().isoformat()
        assert min(row["trade_date"] for row in market) == (start + timedelta(days=10)).isoformat()
