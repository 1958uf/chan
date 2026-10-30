"""新份额API真实demo集成、分类安全、限量导出与参数验证。"""
import pytest
from fastapi.testclient import TestClient

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.main import create_app


@pytest.fixture
def client(tmp_path):
    """功能：提供不联网demo API；输入：临时目录；输出：生命周期客户端。"""
    app = create_app(Settings(data_dir=tmp_path, mode="demo", token="shares-secret"))
    with TestClient(app, base_url="http://127.0.0.1:8765") as connection:
        yield connection


def auth():
    """功能：构造本机同源变更头；输入：无；输出：安全头。"""
    return {"Origin": "http://127.0.0.1:8765", "X-ETF-Token": "shares-secret"}


def test_catalogue_paging_filter_coverage_and_independent_pool(client):
    """功能：检查目录超出旧18池、分页与候选提示；输入：demo；输出：目录契约。"""
    result = client.get("/api/catalogue?limit=5000").json()
    assert result["total"] > len(client.get("/api/etfs").json()["items"])
    assert result["coverage"]["sources"] and result["coverage"]["candidate"] > 0
    page = client.get("/api/catalogue?limit=2&offset=2").json()
    assert len(page["items"]) == 2 and page["total"] == result["total"]
    assert client.get("/api/catalogue?q=510999").json()["items"][0]["code"] == "510999"
    assert all(item["classification_status"] == "candidate" for item in client.get("/api/catalogue?classification_status=candidate").json()["items"])
    assert client.get("/api/catalogue?limit=5001").status_code == 422
    assert client.get("/api/catalogue?offset=-1").status_code == 422


def test_classify_security_manual_preserved_and_enabled_state(client):
    """功能：验证人工确认token/Origin与自动同步保护；输入：分类变更；输出：安全和保护断言。"""
    body = {"code": "159999", "group": "人工核对", "asset_class": "主题", "tracking_index": "人工指数", "enabled": False}
    assert client.post("/api/catalogue/classify", json=body).status_code == 403
    assert client.post("/api/catalogue/classify", json=body, headers={**auth(), "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/catalogue/classify", json=body, headers={**auth(), "X-ETF-Token": "bad"}).status_code == 403
    response = client.post("/api/catalogue/classify", json=body, headers=auth())
    assert response.status_code == 200 and response.json()["manual_classification"]
    client.app.state.repository.sync_catalogue(DemoProvider().catalogue(DEMO_NOW.date()))
    item = client.get("/api/catalogue?q=159999").json()["items"][0]
    assert item["group"] == "人工核对" and not item["enabled"] and item["classification_status"] == "confirmed"
    assert not any(item["code"] == "159999" for item in client.get("/api/etfs").json()["items"])
    assert client.post("/api/catalogue/classify", json={**body, "code": "000000"}, headers=auth()).status_code == 404
    for update in ({"group": " "}, {"classification_status": "candidate"}, {"asset_class": "错误"}, {"enabled": "yes"}, {"enabled": None}, {"extra": "bad"}):
        assert client.post("/api/catalogue/classify", json={**body, **update}, headers=auth()).status_code == 422


def test_overview_group_history_contracts_only_shares_no_nav(client):
    """功能：真实共享计算接入并不查询NAV/报价；输入：demo与禁止非shares查询；输出：全部契约。"""
    repo = client.app.state.repository
    original = repo.records
    def shares_only(kind, *args, **kwargs):
        """功能：拒绝额外数据依赖；输入：记录类别；输出：纯份额记录。"""
        assert kind == "shares"
        return original(kind, *args, **kwargs)
    repo.records = shares_only
    overview = client.get("/api/shares/overview").json()
    assert all(key in overview for key in ("as_of", "items", "groups", "coverage", "notice", "mode"))
    assert overview["mode"] == "demo" and "演示" in overview["notice"]
    assert any(item["code"] == "510999" for item in overview["items"])
    assert not any(item["code"] == "510998" for item in overview["items"])
    detail = client.get("/api/shares/groups/沪深300").json()
    assert detail["group"]["group"] == "沪深300" and detail["items"]
    for frequency in ("day", "week", "month"):
        result = client.get(f"/api/shares/history?frequency={frequency}&group=沪深300&start=2025-03-01&end=2025-03-28").json()
        assert result["frequency"] == frequency and result["mode"] == "demo" and result["items"]
    assert client.get("/api/shares/history?code=510999").json()["items"]
    assert client.get("/api/shares/groups/不存在").status_code == 404
    assert client.get("/api/shares/history?code=000000").status_code == 404


@pytest.mark.parametrize("path", ["/api/shares/overview?as_of=2030-01-01", "/api/shares/overview?period=bad",
    "/api/shares/history?start=2025-03-28&end=2025-03-01", "/api/shares/history?frequency=year",
    "/api/shares/history?code=bad", "/api/shares/history?limit=10001", "/api/shares/export?format=bad",
    "/api/shares/export?limit=5001", "/api/shares/overview?group=" ])
def test_invalid_shares_parameters_rejected(client, path):
    """功能：验证日期周期、代码、分页边界；输入：非法URL；输出：422。"""
    assert client.get(path).status_code == 422


def test_export_safe_csv_formula_and_json_limited(client):
    """功能：名称/分组/来源公式防护与限量下载；输入：恶意目录文本；输出：无可执行CSV和截断提示。"""
    item = default_etfs()[0].model_copy(update={"name": " =HYPERLINK(恶意)", "group": "@恶意", "catalogue_source": "demo-test"})
    client.app.state.repository.sync_catalogue([item])
    response = client.get("/api/shares/export?group=@恶意")
    assert response.status_code == 200 and "attachment" in response.headers["Content-Disposition"]
    assert "' =HYPERLINK" in response.text and "'@恶意" in response.text
    result = client.get("/api/shares/export?format=json&limit=2").json()
    assert len(result["items"]) == 2 and result["truncated"] and result["total"] > 2
    assert result["mode"] == "demo"


def test_empty_live_shares_reports_unknown_calendar(tmp_path):
    """功能：空真实库份额API不假成功、提示日历闭环；输入：不采集live；输出：质量缺失。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as connection:
        result = connection.get("/api/shares/overview").json()
        assert result["mode"] == "live" and not result["coverage"]["calendar_complete"]
        assert all(item["quality"] in ("missing", "partial") for item in result["items"])
        assert "交易日历覆盖不足" in result["notice"]


def test_demo_multiclass_confirmed_samples_and_candidate_denominators(client):
    """功能：多资产自有虚构确认成员可展示且候选不混确认分母；输入：demo看板；输出：来源质量和准确总量。"""
    catalogue = client.get("/api/catalogue?limit=5000").json()["items"]
    confirmed_assets = {item["asset_class"] for item in catalogue if item["enabled"] and item["classification_status"] == "confirmed"}
    assert {"宽基", "行业", "主题", "商品", "债券", "跨境"}.issubset(confirmed_assets)
    samples = [item for item in catalogue if "演示虚构" in item["name"]]
    assert len(samples) == 5 and all(item["catalogue_source"].startswith("demo") and item["tracking_index"] for item in samples)
    assert any(item["classification_status"] == "candidate" for item in catalogue)
    result = client.get("/api/shares/overview").json()
    confirmed = [item for item in result["items"] if item["classification_status"] == "confirmed"]
    assert result["coverage"]["total_count"] == len(confirmed)
    assert result["coverage"]["candidate_count"] == sum(item["classification_status"] == "candidate" for item in result["items"])
    assert sum(group["total_count"] for group in result["groups"]) == len(confirmed)
    for asset in ("行业", "主题", "商品", "债券", "跨境"):
        group = next(group for group in result["groups"] if group["asset_class"] == asset and group["total_count"])
        assert group["available_count"] >= 1 and group["comparable_count"] >= 1 and group["quality"] == "demo"
        assert group["total_shares"] > 0
    assert all(item["quality"] == "demo" and item["source"].startswith("demo") for item in result["items"] if "演示虚构" in item["name"])


def test_demo_catalogue_v2_migrates_existing_seed_without_overwriting_manual(tmp_path):
    """功能：旧demo升级补入多资产样本且保留人工分类和禁用；输入：v1标记库；输出：幂等升级。"""
    from etf_monitor.demo import seed_demo
    from etf_monitor.storage import Repository
    repo = Repository(tmp_path / "demo.sqlite")
    repo.initialize()
    assert seed_demo(repo, default_etfs())
    repo.classify_catalogue("510999", group="用户组", asset_class="主题", enabled=False)
    with repo.connection() as db:
        db.execute("DELETE FROM metadata WHERE key='demo_catalogue_v2'")
        for code in ("510990", "510991", "510992", "510993", "159990"):
            db.execute("DELETE FROM catalogue WHERE code=?", (code,))
            db.execute("DELETE FROM records WHERE kind='shares' AND code=?", (code,))
    assert not seed_demo(repo, default_etfs())
    samples = repo.catalogue(q="演示虚构", limit=5000)
    assert len(samples) == 5 and all(repo.records("shares", code=item.code) for item in samples)
    saved = repo.catalogue(q="510999")[0]
    assert saved.group == "用户组" and saved.manual_classification and not saved.enabled
    assert repo.document("metadata", "demo_catalogue_v2")
    assert not seed_demo(repo, default_etfs())
    assert repo.revision_count() == 0


def test_history_includes_disabled_members_without_enabling_current_overview(client, monkeypatch):
    """功能：禁用成员仍保留历史且不恢复当前采集/看板；输入：禁用demo成员；输出：历史成员完整传递。"""
    from etf_monitor.analysis import shares
    original = shares.share_history
    seen = []
    def capture_members(etfs, records, calendar, start, end, frequency="day"):
        """功能：记录历史计算接收的成员；输入：共享历史契约参数；输出：真实计算结果。"""
        seen.extend(etfs)
        return original(etfs, records, calendar, start, end, frequency=frequency)
    monkeypatch.setattr(shares, "share_history", capture_members)
    response = client.get("/api/shares/history?code=510998&start=2025-03-01&end=2025-03-28")
    assert response.status_code == 200, response.text
    assert len(seen) == 1 and seen[0].code == "510998" and not seen[0].enabled
    seen.clear()
    assert client.get("/api/shares/history?group=沪深300").status_code == 200
    assert any(item.code == "510998" and not item.enabled for item in seen)
    assert not any(item["code"] == "510998" for item in client.get("/api/shares/overview").json()["items"])
    assert not client.app.state.repository.catalogue(q="510998")[0].enabled


def test_shares_health_tracks_only_confirmed_enabled_dates_and_default_schedule(client):
    """功能：额外份额健康不以NAV缺失判份额失败；输入：完整demo；输出：目录分母和发布时刻。"""
    result = client.get("/api/health").json()["shares_health"]
    assert result["status"] == "demo" and result["confirmed_enabled"] > 18
    assert result["intraday_enabled"] is False and result["daily_update_time"] == "18:17"
    assert result["expected_trade_date"]


def test_new_task_api_kind_group_codes_and_mutation_protection(client):
    """功能：验证两新增任务及分类选择、token保护；输入：新任务JSON；输出：已选目录成员。"""
    assert client.post("/api/tasks", json={"kind": "shares"}).status_code == 403
    response = client.post("/api/tasks", json={"kind": "shares", "group": "沪深300"}, headers=auth())
    assert response.status_code == 200 and "510999" in response.json()["codes"]
    assert "510998" not in response.json()["codes"]
    assert client.post("/api/tasks", json={"kind": "catalogue"}, headers=auth()).status_code == 200
    assert client.post("/api/tasks", json={"kind": "shares", "codes": ["159999"]}, headers=auth()).status_code == 422
    assert client.post("/api/tasks", json={"kind": "refresh", "group": "沪深300"}, headers=auth()).status_code == 422
