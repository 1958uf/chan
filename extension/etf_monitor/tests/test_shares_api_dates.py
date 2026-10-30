"""默认最新共同统计日、T+1发布及显式截止不回退的离线API回归。"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from etf_monitor.config import Settings
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.main import create_app
from etf_monitor.models import ETF, ShareRecord


@pytest.fixture
def client(tmp_path):
    """功能：创建两市同组真实质量mock；输入：临时目录；输出：已存日历的客户端。"""
    app = create_app(Settings(data_dir=tmp_path), DemoProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as connection:
        repo = app.state.repository
        with repo.connection() as db:
            db.execute("DELETE FROM catalogue")
        repo.sync_catalogue([ETF(code="510990", name="沪市测试", exchange="sh", group="测试"),
                             ETF(code="159990", name="深市测试", exchange="sz", group="测试")])
        days = [date(2025, 3, 25) + timedelta(days=i) for i in range(4)]
        repo.save_calendar(days, start=days[0], end=days[-1], source="mock-calendar", fetched_at=DEMO_NOW)
        yield connection


def put(client, code, days, quality="valid", source="mock-exchange"):
    """功能：保存指定成员已发布份额；输入：客户端、代码、日期及质量；输出：持久记录。"""
    client.app.state.repository.save_records({"shares": [ShareRecord(code=code, trade_date=date.fromisoformat(day),
        shares=100_000_000 + i * 1_000_000, source=source, fetched_at=DEMO_NOW, quality=quality)
        for i, day in enumerate(days)]}, DEMO_NOW)


def test_default_tplusone_uses_latest_common_preserves_requested_date(client):
    """功能：今天日历存在但份额仅发布到昨天仍展示昨天同日总量；输入：两市T+1；输出：日期和覆盖。"""
    for code in ("510990", "159990"):
        put(client, code, ["2025-03-25", "2025-03-26", "2025-03-27"])
    result = client.get("/api/shares/overview").json()
    assert result["as_of"] == result["requested_as_of"] == "2025-03-28"
    assert result["statistics_date"] == "2025-03-27" and result["date_selection"] == "latest_common"
    assert result["coverage"]["available_count"] == result["coverage"]["total_count"] == 2
    assert result["coverage"]["missing_markets"] == []
    assert result["groups"][0]["total_shares"] == 204_000_000
    assert {item["trade_date"] for item in result["items"]} == {"2025-03-27"}
    assert "请求截止日为2025-03-28" in result["notice"]
    detail = client.get("/api/shares/groups/测试").json()
    assert detail["statistics_date"] == "2025-03-27"
    exported = client.get("/api/shares/export?format=json").json()
    assert exported["statistics_date"] == "2025-03-27"


def test_markets_different_latest_use_common_day_not_sum_latest(client):
    """功能：沪市发布今天深市昨天时统一昨天；输入：分市不同最新日期；输出：共同统计日。"""
    put(client, "510990", ["2025-03-25", "2025-03-26", "2025-03-27", "2025-03-28"])
    put(client, "159990", ["2025-03-25", "2025-03-26", "2025-03-27"])
    result = client.get("/api/shares/overview").json()
    assert result["statistics_date"] == "2025-03-27"
    assert result["coverage"]["market_latest_dates"] == {"sh": "2025-03-28", "sz": "2025-03-27"}
    assert result["groups"][0]["total_shares"] == 204_000_000


def test_no_common_day_unifies_latest_and_reports_missing_market(client):
    """功能：无共同日期时统一最近发布日，缺市明确计缺失不填旧latest；输入：无交集；输出：partial分母。"""
    put(client, "510990", ["2025-03-27", "2025-03-28"])
    put(client, "159990", ["2025-03-25", "2025-03-26"])
    result = client.get("/api/shares/overview").json()
    assert result["statistics_date"] == "2025-03-28" and result["date_selection"] == "latest_available_partial"
    assert result["coverage"]["missing_markets"] == ["sz"]
    assert result["coverage"]["available_count"] == 1 and result["coverage"]["total_count"] == 2
    assert result["groups"][0]["total_shares"] == 101_000_000
    assert next(item for item in result["items"] if item["code"] == "159990")["shares"] is None
    assert "没有共同发布日" in result["notice"]


def test_missing_market_is_not_silently_removed_from_denominator(client):
    """功能：一市完全没记录仍保留缺市及成员分母；输入：仅沪市；输出：统一日和missing。"""
    put(client, "510990", ["2025-03-26", "2025-03-27"])
    result = client.get("/api/shares/overview").json()
    assert result["statistics_date"] == "2025-03-27" and result["coverage"]["missing_markets"] == ["sz"]
    assert result["coverage"]["market_latest_dates"]["sz"] is None
    assert result["coverage"]["total_count"] == 2


def test_explicit_asof_keeps_target_even_if_not_published(client):
    """功能：用户显式选今天不自动回退昨天；输入：仅昨天份额和显式截止；输出：缺失但原日期。"""
    for code in ("510990", "159990"):
        put(client, code, ["2025-03-26", "2025-03-27"])
    result = client.get("/api/shares/overview?as_of=2025-03-28").json()
    assert result["statistics_date"] == "2025-03-28" and result["date_selection"] == "explicit"
    assert result["coverage"]["available_count"] == 0
    assert all(item["shares"] is None for item in result["items"])
    historical = client.get("/api/shares/overview?as_of=2025-03-26").json()
    assert historical["statistics_date"] == "2025-03-26" and historical["coverage"]["available_count"] == 2


def test_unknown_today_calendar_does_not_erase_covered_published_day(client):
    """功能：日历未覆盖今天时仍允许共同已发布日而不猜今天；输入：覆盖到昨天；输出：有效历史统计日。"""
    for code in ("510990", "159990"):
        put(client, code, ["2025-03-26", "2025-03-27"])
    repo = client.app.state.repository
    with repo.connection() as db:
        db.execute("DELETE FROM calendar_coverage")
    repo.save_calendar([date(2025, 3, 25), date(2025, 3, 26), date(2025, 3, 27)],
        start=date(2025, 3, 25), end=date(2025, 3, 27), source="mock-calendar", fetched_at=DEMO_NOW)
    result = client.get("/api/shares/overview").json()
    assert result["statistics_date"] == "2025-03-27" and result["coverage"]["calendar_complete"]
    explicit = client.get("/api/shares/overview?as_of=2025-03-28").json()
    assert explicit["statistics_date"] is None and not explicit["coverage"]["calendar_complete"]


@pytest.mark.parametrize("quality", ["suspect", "partial", "missing", "error"])
def test_abnormal_recent_records_do_not_advance_published_day(client, quality):
    """功能：异常最新份额不可推动统计日；输入：有效昨天及无效今天；输出：仍取昨天。"""
    for code in ("510990", "159990"):
        put(client, code, ["2025-03-26", "2025-03-27"])
        put(client, code, ["2025-03-28"], quality=quality)
    result = client.get("/api/shares/overview").json()
    assert result["statistics_date"] == "2025-03-27"


def test_conflicting_sources_do_not_count_as_valid_published_day(client):
    """功能：同日多源冲突不冒充最新共同有效日期；输入：冲突份额；输出：昨日统一日。"""
    for code in ("510990", "159990"):
        put(client, code, ["2025-03-26", "2025-03-27"])
        put(client, code, ["2025-03-28"])
    record = ShareRecord(code="510990", trade_date=date(2025, 3, 28), shares=999_000_000,
                         source="conflicting-source", quality="valid", fetched_at=DEMO_NOW)
    client.app.state.repository.save_records({"shares": [record]}, DEMO_NOW)
    result = client.get("/api/shares/overview").json()
    assert result["statistics_date"] == "2025-03-27"
