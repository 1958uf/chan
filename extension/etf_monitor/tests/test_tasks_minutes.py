"""分钟任务契约：≤3ETF、≤7日、周期一致、真实失败不伪装样本。"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.main import create_app
from etf_monitor.providers.base import ProviderError


class MinuteProvider:
    """只实现分钟bars的固定mock，其他接口不得调用。"""
    def __init__(self, fail=False, wrong=False, future=False):
        """功能：设置响应边界；输入：故障开关；输出：mock。"""
        self.calls = []
        self.fail, self.wrong, self.future = fail, wrong, future

    def bars(self, etf, start, end, interval="day"):
        """功能：返回真实质量分钟样本；输入：标的和周期；输出：模型或来源异常。"""
        self.calls.append((etf.code, start, end, interval))
        if self.fail:
            raise ProviderError("mock-minute", "上游分钟采集失败")
        records = DemoProvider().bars(etf, start, end, interval)
        records = [record.model_copy(update={"source": "mock-minute", "quality": "valid", "fetched_at": DEMO_NOW}) for record in records]
        if self.wrong:
            records = [record.model_copy(update={"interval": "day"}) for record in records]
        if self.future:
            records = [record.model_copy(update={"time": DEMO_NOW + timedelta(minutes=1)}) for record in records[:1]]
        return records


def headers(client):
    """功能：读取本地安全会话；输入：客户端；输出：变更请求头。"""
    return {"Origin": "http://localhost:8765", "X-ETF-Token": client.get("/api/session").json()["token"]}


@pytest.mark.parametrize("interval", ["1m", "5m"])
def test_minute_task_api_real_mock_and_idempotent(tmp_path, interval):
    """功能：验证前端分钟请求与终态重读；输入：周期和mock；输出：契约及幂等断言。"""
    provider = MinuteProvider()
    app = create_app(Settings(data_dir=tmp_path), provider, lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as client:
        body = {"kind": "refresh", "codes": ["510050"], "start": "2025-03-28", "end": "2025-03-28", "interval": interval}
        response = client.post("/api/tasks", json=body, headers=headers(client))
        assert response.status_code == 200, response.text
        assert response.json()["interval"] == interval and response.json()["scope"] == "minute"
        app.state.tasks.pending.join()
        finished = client.get("/api/tasks").json()["items"][0]
        assert finished["status"] == "completed" and finished["count"] == (240 if interval == "1m" else 48)
        detail = client.get("/api/etfs/510050?limit=1000").json()
        assert len(detail["bars"]) == finished["count"]
        assert all(record["interval"] == interval and record["source"] == "mock-minute" for record in detail["bars"])
        assert detail["shares"] == []
        assert provider.calls == [("510050", DEMO_NOW.date(), DEMO_NOW.date(), interval)]
        repeated = client.post("/api/tasks", json=body, headers=headers(client))
        app.state.tasks.pending.join()
        assert app.state.repository.document("tasks", repeated.json()["id"])["changed"] == 0


def test_minute_task_limits_kinds_and_default_date(tmp_path):
    """功能：验证分钟输入限量且默认仅当日；输入：非法任务集合；输出：422与边界断言。"""
    app = create_app(Settings(data_dir=tmp_path), MinuteProvider(), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as client:
        valid = {"kind": "refresh", "codes": ["510050"], "start": "2025-03-28", "end": "2025-03-28", "interval": "1m"}
        for update in ({"interval": "15m"}, {"interval": None}, {"codes": [etf.code for etf in default_etfs()[:4]]},
                       {"codes": None}, {"start": "2025-03-21"}, {"kind": "market"}, {"kind": "holders"}, {"kind": "calendar"}):
            assert client.post("/api/tasks", json={**valid, **update}, headers=headers(client)).status_code == 422
        seven = client.post("/api/tasks", json={**valid, "codes": [etf.code for etf in default_etfs()[:3]], "start": "2025-03-22"}, headers=headers(client))
        assert seven.status_code == 200
        app.state.tasks.pending.join()
        omitted = client.post("/api/tasks", json={"kind": "backfill", "codes": ["510050"], "interval": "5m"}, headers=headers(client))
        assert omitted.status_code == 200
        assert omitted.json()["start"] == omitted.json()["end"] == "2025-03-28"
        app.state.tasks.pending.join()


@pytest.mark.parametrize("option,reason", [("fail", "采集失败"), ("wrong", "周期"), ("future", "尚未发生")])
def test_minute_task_failure_does_not_seed_or_commit(tmp_path, option, reason):
    """功能：真实失败、错周期、未来分钟不吞异常；输入：错误mock；输出：失败与空库断言。"""
    app = create_app(Settings(data_dir=tmp_path), MinuteProvider(**{option: True}), lambda: DEMO_NOW)
    with TestClient(app, base_url="http://localhost:8765") as client:
        response = client.post("/api/tasks", json={"kind": "refresh", "codes": ["510050"], "interval": "1m"}, headers=headers(client))
        app.state.tasks.pending.join()
        task = app.state.repository.document("tasks", response.json()["id"])
        assert task["status"] == "failed" and reason in task["message"]
        assert app.state.repository.records("bars") == []
        assert not (tmp_path / "demo.sqlite").exists()


def test_demo_minute_task_fixed_bounded_samples(tmp_path):
    """功能：演示分钟仅自有固定样本和独立库；输入：demo模式；输出：数量和质量断言。"""
    app = create_app(Settings(data_dir=tmp_path, mode="demo"))
    with TestClient(app, base_url="http://localhost:8765") as client:
        response = client.post("/api/tasks", json={"kind": "refresh", "codes": ["510050"], "interval": "5m"}, headers=headers(client))
        app.state.tasks.pending.join()
        task = app.state.repository.document("tasks", response.json()["id"])
        assert task["status"] == "completed" and task["count"] == 48
        records = app.state.repository.records("bars", "510050", interval="5m")
        assert len(records) == 48 and all(record.quality == "demo" for record in records)
        assert (tmp_path / "demo.sqlite").exists() and not (tmp_path / "live.sqlite").exists()


def test_demo_minute_bounds_determinism_and_lunch_gap():
    """功能：分钟样本有限、无午休或未来伪造；输入：固定周期；输出：严格样本断言。"""
    provider, etf = DemoProvider(), default_etfs()[0]
    for interval, expected in (("1m", 240), ("5m", 48)):
        rows = provider.bars(etf, DEMO_NOW.date(), DEMO_NOW.date(), interval)
        assert len(rows) == expected and rows == provider.bars(etf, DEMO_NOW.date(), DEMO_NOW.date(), interval)
        assert all(record.time <= DEMO_NOW and not (record.time.hour == 12) for record in rows)
    with pytest.raises(ValueError):
        provider.bars(etf, DEMO_NOW.date() - timedelta(days=7), DEMO_NOW.date(), "1m")
    with pytest.raises(ValueError):
        provider.bars(etf, DEMO_NOW.date(), DEMO_NOW.date(), "15m")
