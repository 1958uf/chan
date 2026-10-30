"""REST契约和本地安全测试：临时库、固定时钟、无网络。"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.main import create_app, local_host, safe_origin
from etf_monitor.api.routes import csv_cell


@pytest.fixture
def client(tmp_path):
    """功能：提供lifespan测试客户端；输入：临时目录；输出：本机客户端。"""
    app = create_app(Settings(data_dir=tmp_path, token="test-secret"), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://127.0.0.1:8765") as connection:
        yield connection


def auth(client):
    """功能：获得本地变更头；输入：客户端；输出：Origin和token。"""
    return {"Origin": "http://127.0.0.1:8765", "X-ETF-Token": client.get("/api/session").json()["token"]}


def test_lifespan_import_no_write_and_live_never_seed(tmp_path):
    """功能：验证创建无I/O与live不演示；输入：临时目录；输出：断言。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    assert not (tmp_path / "live.sqlite").exists()
    with TestClient(app, base_url="http://localhost:8765") as connection:
        assert (tmp_path / "live.sqlite").exists()
        assert not (tmp_path / "demo.sqlite").exists()
        assert connection.get("/api/health").json()["status"] == "empty"
        assert app.state.repository.records("shares") == []
        assert connection.get("/api/dashboard").json()["mode"] == "live"


def test_security_all_mutations_and_origins(client):
    """功能：验证token、Origin、Host与会话安全；输入：客户端；输出：拒绝断言。"""
    for method, url in (("post", "/api/etfs"), ("post", "/api/holders/import"), ("post", "/api/tasks"),
                        ("post", "/api/tasks/missing/cancel"), ("post", "/api/alerts/missing/ack"), ("put", "/api/settings")):
        assert getattr(client, method)(url, json={}).status_code == 403
        assert getattr(client, method)(url, json={}, headers={"Origin": "http://127.0.0.1:8765", "X-ETF-Token": "bad"}).status_code == 403
        assert getattr(client, method)(url, json={}, headers={"Origin": "https://evil.example", "X-ETF-Token": "test-secret"}).status_code == 403
    assert client.get("/api/session", headers={"Origin": "null"}).status_code == 403
    assert client.get("/docs", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/docs").status_code == 200
    assert client.get("/api/session").headers["Cache-Control"] == "no-store"
    assert not local_host("192.168.1.10")
    assert not safe_origin("http://localhost:8765/path", client.app.state.settings)
    assert not safe_origin("http://user@localhost:8765", client.app.state.settings)
    assert not safe_origin("http://127.0.0.1:9999", client.app.state.settings)
    assert not safe_origin("http://localhost:bad", client.app.state.settings)


def test_non_local_session_docs_and_mutation_rejected(tmp_path):
    """功能：验证非本机来源不能获得token或写入；输入：mock客户端地址；输出：403。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765", client=("192.168.1.5", 50000)) as connection:
        assert connection.get("/api/session").status_code == 403
        assert connection.get("/openapi.json").status_code == 403
        assert connection.post("/api/tasks", json={"kind": "market"}, headers={"Origin": "http://localhost:8765", "X-ETF-Token": app.state.token}).status_code == 403


def test_etf_validation_pagination_and_detail(client):
    """功能：验证ETF严格校验、分页和完整明细；输入：客户端；输出：断言。"""
    assert len(client.get("/api/etfs?limit=2").json()["items"]) == 2
    assert client.get("/api/etfs?limit=1001").status_code == 422
    assert client.get("/api/etfs?offset=-1").status_code == 422
    assert client.get("/api/etfs/123456").status_code == 404
    assert client.get("/api/etfs/bad").status_code == 422
    value = default_etfs()[0].model_dump(mode="json")
    value["name"] = "更新ETF名称"
    assert client.post("/api/etfs", json=value, headers=auth(client)).status_code == 200
    detail = client.get("/api/etfs/510050").json()
    assert detail["etf"]["name"] == value["name"]
    assert all(key in detail for key in ("analysis", "shares", "quotes", "bars", "navs", "holders"))
    for update in ({"code": "51005"}, {"code": 510050}, {"exchange": "sz"}, {"listed_on": "2030-01-01"},
                   {"name": " "}, {"group": " "}, {"enabled": "yes"}, {"tags": ["x"] * 21}, {"tags": [""]}, {"extra": "bad"}):
        assert client.post("/api/etfs", json={**value, **update}, headers=auth(client)).status_code == 422


def test_settings_safe_persistent_and_bounds(client):
    """功能：验证配置白名单和严格范围；输入：客户端；输出：断言。"""
    current = client.get("/api/settings").json()
    assert "token" not in current and "data_dir" not in current and "allowed_origins" not in current
    assert client.put("/api/settings", json={"shares_alert_pct": 3.0, "quote_interval": 60}, headers=auth(client)).status_code == 200
    assert client.app.state.repository.document("metadata", "settings")["quote_interval"] == 60
    for value in ({"data_dir": "other"}, {"token": "bad"}, {"mode": "demo"}, {"allowed_origins": []},
                  {"quote_interval": 14}, {"quote_interval": "60"}, {"shares_alert_pct": 0},
                  {"alert_cooldown_seconds": 0}, {"scheduler_enabled": "yes"}, {"quote_interval": None}):
        assert client.put("/api/settings", json=value, headers=auth(client)).status_code == 422


def test_holders_atomic_import_source_dates_and_idempotence(client):
    """功能：验证持有人导入及原子拒绝；输入：固定样本；输出：断言。"""
    record = DemoProvider().holders(default_etfs()[0])[0].model_dump(mode="json")
    record["source"] = "人工公告核对"
    record["quality"] = "valid"
    response = client.post("/api/holders/import", json={"records": [record]}, headers=auth(client))
    assert response.json()["changed"] == 1
    assert client.post("/api/holders/import", json={"records": [record]}, headers=auth(client)).json()["changed"] == 0
    assert client.get("/api/holders?code=510050").json()["items"][0]["published_on"] == "2025-03-20"
    assert client.get("/api/holders?code=bad").status_code == 422
    assert client.get("/api/holders?code=123456").status_code == 404
    for update in ({"published_on": "2024-12-01"}, {"published_on": "2030-01-01"}, {"report_date": "2030-01-01"},
                   {"source": " "}, {"ratio_pct": 101}, {"source_url": "javascript:alert(1)"}):
        body = {"records": [record, {**record, **update}]}
        assert client.post("/api/holders/import", json=body, headers=auth(client)).status_code == 422
    assert len(client.get("/api/holders").json()["items"]) == 1
    assert client.post("/api/holders/import", json={"records": [record, record]}, headers=auth(client)).status_code == 422


def test_dashboard_history_export_csv_protection(client):
    """功能：验证完整来源、历史与CSV公式安全；输入：固定样本；输出：断言。"""
    etf = default_etfs()[0]
    provider = DemoProvider()
    shares = provider.shares(DEMO_NOW.date() - timedelta(days=7), DEMO_NOW.date(), [etf])
    shares[0] = shares[0].model_copy(update={"source": " =HYPERLINK(\"evil\")"})
    client.app.state.repository.save_records({"shares": shares, "navs": provider.navs(etf, DEMO_NOW.date() - timedelta(days=7), DEMO_NOW.date())}, DEMO_NOW)
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["groups"] and dashboard["notice"]
    history = client.get("/api/history?group=上证50&limit=2").json()["items"]
    assert len(history) == 2 and history[0]["source"] and history[0]["date"]
    assert client.get("/api/history?start=2025-03-28&end=2025-03-01").status_code == 422
    assert client.get("/api/dashboard?as_of=2030-01-01").status_code == 422
    assert client.get("/api/export?format=unknown").status_code == 422
    assert client.get("/api/export?limit=10001").status_code == 422
    response = client.get("/api/export?format=csv&code=510050")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert "' =HYPERLINK" in response.text
    exported = client.get("/api/export?format=json&code=510050&limit=2").json()
    assert len(exported["items"]) == 2 and exported["limit"] == 2
    for value in ("=1", "+1", "-1", "@foo", "\tformula", "\rformula", "\nformula", "  =1"):
        assert csv_cell(value).startswith("'")
    assert csv_cell(None) == "" and csv_cell(-2) == -2 and csv_cell("510050") == "510050"


def test_tasks_alert_endpoints_errors_and_dates(client):
    """功能：验证任务、取消及告警确认契约；输入：客户端；输出：断言。"""
    assert client.get("/api/tasks").json() == {"items": []}
    for value in ({"kind": "unknown"}, {"kind": "market", "start": "2025-03-28", "end": "2025-03-01"},
                  {"kind": "holders", "codes": ["bad"]}, {"kind": "holders", "codes": ["123456"]},
                  {"kind": "market", "extra": 1}):
        assert client.post("/api/tasks", json=value, headers=auth(client)).status_code == 422
    response = client.post("/api/tasks", json={"kind": "calendar", "start": "2025-03-01", "end": "2025-03-28"}, headers=auth(client))
    assert response.status_code == 200, response.text
    assert client.post(f'/api/tasks/{response.json()["id"]}/cancel', headers=auth(client)).json() == {"ok": True}
    assert client.post("/api/tasks/missing/cancel", headers=auth(client)).status_code == 404
    client.app.state.tasks.alert("510050", "test", "warning", "测试", "消息")
    alert = client.get("/api/alerts").json()["items"][0]
    assert client.post(f'/api/alerts/{alert["id"]}/ack', headers=auth(client)).json() == {"ok": True}
    assert client.get("/api/alerts").json()["items"][0]["acknowledged"]
    assert client.post("/api/alerts/missing/ack", headers=auth(client)).status_code == 404
