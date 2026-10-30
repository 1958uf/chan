"""健康推导与日线分页隔离审查回归，固定时钟、禁联网。"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.main import create_app


def fill_daily(app, now):
    """功能：填充一个标的完整真实质量mock；输入：应用与时钟；输出：旧记录批次。"""
    etf, provider = default_etfs()[0], DemoProvider()
    app.state.repository.put_etfs([item.model_copy(update={"enabled": item.code == etf.code}) for item in default_etfs()])
    start, end = date(2025, 2, 17), DEMO_NOW.date()
    batches = {"shares": provider.shares(start, end, [etf]), "navs": provider.navs(etf, start, end),
               "bars": provider.bars(etf, start, end), "market": provider.market(start, end)}
    batches = {kind: [record.model_copy(update={"quality": "valid", "source": "mock-live"}) for record in records]
               for kind, records in batches.items()}
    app.state.repository.save_records(batches, now, calendar=provider.calendar(start, end),
                                      calendar_request=(start, now.date(), "mock-calendar"))
    return batches


@pytest.mark.parametrize("status", ["empty", "partial", "stale", "error"])
def test_live_source_incomplete_status_never_online_ok(tmp_path, status):
    """功能：完整日数据也不能覆盖来源失败或空结果；输入：状态mock；输出：degraded断言。"""
    now = DEMO_NOW.replace(hour=16)
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: now)
    with TestClient(app, base_url="http://localhost:8765") as client:
        fill_daily(app, now)
        app.state.repository.put_document("sources", "failing-upstream", {"source": "failing-upstream", "status": status,
                                          "last_success": None, "error": "故障" if status == "error" else "", "message": "源结果不完整"})
        health = client.get("/api/health").json()
        assert health["status"] == "degraded"
        source = next(item for item in health["sources"] if item["source"] == "failing-upstream")
        assert source["status"] == status and source["derived_reasons"]


def test_health_stale_actual_date_even_recent_fetch(tmp_path):
    """功能：最近请求成功不掩盖业务日滞后；输入：次交易日时钟与旧日期；输出：lag断言。"""
    now = DEMO_NOW.replace(hour=16) + timedelta(days=3)
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: now)
    with TestClient(app, base_url="http://localhost:8765") as client:
        fill_daily(app, now)
        app.state.repository.save_calendar([now.date()], start=now.date(), end=now.date(), source="mock-calendar", fetched_at=now)
        health = client.get("/api/health").json()
        assert health["status"] == "degraded" and health["calendar_covered"]
        source = next(item for item in health["sources"] if item["source"] == "mock-live")
        assert source["status"] == "stale"
        assert source["last_actual_date"] == str(DEMO_NOW.date())
        assert source["lag_trading_days"] >= 1
        assert health["expected_trade_date"] == str(now.date())


def test_health_known_holiday_and_missing_calendar(tmp_path):
    """功能：已覆盖非交易日接受前交易日，无日历不能ok；输入：周末固定时钟；输出：断言。"""
    now = DEMO_NOW.replace(hour=16) + timedelta(days=1)
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: now)
    with TestClient(app, base_url="http://localhost:8765") as client:
        fill_daily(app, now)
        healthy = client.get("/api/health").json()
        assert healthy["status"] == "ok", healthy
        assert healthy["expected_trade_date"] == "2025-03-28" and not healthy["calendar_known"]
        with app.state.repository.connection() as db:
            db.execute("DELETE FROM calendar_coverage")
        unknown = client.get("/api/health").json()
        assert unknown["status"] == "degraded" and not unknown["calendar_covered"]
        assert unknown["reasons"]


def test_demo_health_is_not_real_source_online(tmp_path):
    """功能：demo健康明确非在线ok；输入：演示模式；输出：状态和警示断言。"""
    app = create_app(Settings(data_dir=tmp_path, mode="demo"))
    with TestClient(app, base_url="http://localhost:8765") as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "demo" and health["status"] == "demo"
        assert "不代表真实" in health["notice"]


def test_analysis_daily_bars_not_truncated_by_thousand_minute_rows(tmp_path):
    """功能：SQL先过滤日线再分页；输入：30日线和1100分钟线；输出：价格指标正常。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as client:
        batches = fill_daily(app, DEMO_NOW)
        base = batches["bars"][-1]
        minute = [base.model_copy(update={"interval": "1m", "time": DEMO_NOW - timedelta(minutes=i), "fetched_at": DEMO_NOW})
                  for i in range(1100)]
        app.state.repository.save_records({"bars": minute}, DEMO_NOW)
        repo = app.state.repository
        assert len(repo.records("bars", "510050", limit=1000, newest=True, known_at=DEMO_NOW, interval="day")) == len(batches["bars"])
        result = next(item for item in client.get("/api/dashboard").json()["etfs"] if item["code"] == "510050")
        indicator = next(item for item in result["indicators"] if item["name"] == "价格趋势")
        assert indicator["state"] != "unknown"


def test_health_intraday_quote_time_and_success_without_records(tmp_path):
    """功能：盘中按源时刻判旧报价且无记录不ok；输入：固定时钟和源成功标记；输出：断言。"""
    now = DEMO_NOW.replace(hour=10)
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: now)
    with TestClient(app, base_url="http://localhost:8765") as client:
        fill_daily(app, now)
        quote = DemoProvider().quotes(default_etfs()[:1])[0].model_copy(update={"quality": "valid", "source": "quote-source",
                          "quote_time": now - timedelta(minutes=10), "fetched_at": now})
        app.state.repository.save_records({"quotes": [quote]}, now)
        app.state.repository.put_document("sources", "quotes", {"source": "quotes", "status": "ok", "last_success": now.isoformat(), "error": ""})
        app.state.repository.put_document("sources", "unverified", {"source": "unverified", "status": "ok", "last_success": now.isoformat(), "error": ""})
        sources = client.get("/api/health").json()["sources"]
        assert next(item for item in sources if item["source"] == "quote-source")["status"] == "stale"
        assert next(item for item in sources if item["source"] == "quotes")["status"] == "stale"
        assert next(item for item in sources if item["source"] == "unverified")["status"] == "partial"
