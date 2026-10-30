"""任务服务固定时钟和mock provider测试，严禁联网。"""
import threading
import time
from datetime import date, timedelta

import pytest

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.services import TaskManager
from etf_monitor.storage import Repository


def manager(tmp_path, provider=None, **kwargs):
    """功能：组装临时任务服务；输入：目录和mock；输出：服务。"""
    repository = Repository(tmp_path / "tasks.sqlite")
    repository.initialize()
    repository.put_etfs(default_etfs()[:1])
    return TaskManager(repository, provider or DemoProvider(), Settings(data_dir=tmp_path, mode="demo"), lambda: DEMO_NOW, **kwargs)


def wait_task(service, identifier, statuses=("completed", "partial", "empty", "failed", "timeout", "cancelled")):
    """功能：有界等待测试任务；输入：服务与ID；输出：终态任务。"""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = service.repository.document("tasks", identifier)
        if task["status"] in statuses:
            return task
        threading.Event().wait(.01)
    raise AssertionError("任务未在5秒内完成")


def test_refresh_backfill_holders_market_calendar(tmp_path):
    """功能：验证五种采集计划和幂等；输入：临时库；输出：断言。"""
    service = manager(tmp_path)
    service.start()
    try:
        for kind in ("refresh", "backfill", "holders", "market", "calendar"):
            task = service.submit(kind, DEMO_NOW.date() - timedelta(days=7), DEMO_NOW.date())
            finished = wait_task(service, task["id"])
            assert finished["status"] == "completed", finished
            assert finished["progress"] == 100
        assert service.repository.is_trading_day(DEMO_NOW.date())
        assert service.repository.records("holders")
        count = len(service.repository.records("shares"))
        wait_task(service, service.submit("refresh")["id"])
        wait_task(service, service.submit("refresh")["id"])
        assert len(service.repository.records("shares")) >= count
        assert service.repository.revision_count() == 0
    finally:
        service.close()


def test_input_queue_cancel_and_recovery(tmp_path):
    """功能：验证队列边界、取消与进程恢复；输入：临时库；输出：断言。"""
    service = manager(tmp_path, queue_size=1)
    for kwargs in ({"kind": "bad"}, {"kind": "market", "start": DEMO_NOW.date(), "end": date(2025, 3, 1)},
                   {"kind": "market", "end": date(2030, 1, 1)}, {"kind": "market", "start": date(2000, 1, 1)},
                   {"kind": "holders", "codes": ["123456"]}, {"kind": "holders", "codes": []},
                   {"kind": "holders", "codes": ["510050", "510050"]}):
        with pytest.raises(ValueError):
            service.submit(**kwargs)
    task = service.submit("market")
    with pytest.raises(OverflowError):
        service.submit("market")
    assert service.cancel(task["id"])
    assert service.cancel(task["id"])
    assert not service.cancel("unknown")
    service.start()
    service.close()
    with pytest.raises(RuntimeError):
        service.submit("market")
    service.repository.put_document("tasks", "interrupted", {"id": "interrupted", "status": "running"})
    restarted = TaskManager(service.repository, DemoProvider(), service.settings, lambda: DEMO_NOW)
    restarted.start()
    try:
        assert restarted.repository.document("tasks", "interrupted")["status"] == "failed"
    finally:
        restarted.close()


class BrokenProvider(DemoProvider):
    """确定性失败源，验证真实错误可见。"""

    def shares(self, start, end, etfs):
        """功能：模拟接口失败；输入：请求参数；输出：抛真实异常。"""
        raise RuntimeError("交易所接口故障")

    def holders(self, etf):
        """功能：模拟有效空结果；输入：ETF；输出：空列表。"""
        return []

    def market(self, start, end):
        """功能：模拟所有请求失败；输入：日期；输出：抛异常。"""
        raise RuntimeError("市场数据拒绝请求")


def test_partial_failed_empty_health_and_dedup(tmp_path):
    """功能：验证部分失败、全部失败与有效空；输入：故障mock；输出：断言。"""
    service = manager(tmp_path, BrokenProvider())
    service.start()
    try:
        assert wait_task(service, service.submit("refresh")["id"])["status"] == "partial"
        assert wait_task(service, service.submit("market")["id"])["status"] == "failed"
        assert wait_task(service, service.submit("holders")["id"])["status"] == "empty"
        assert service.repository.document("sources", "shares")["error"]
        alert_count = len(service.repository.alerts())
        wait_task(service, service.submit("market")["id"])
        assert len(service.repository.alerts()) == alert_count
    finally:
        service.close()


class BlockingProvider(DemoProvider):
    """可控阻塞用于验证互斥和立即可见取消。"""

    def __init__(self):
        """功能：初始化阻塞事件；输入：无；输出：mock。"""
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def market(self, start, end):
        """功能：有界阻塞采集；输入：日期；输出：释放后的样本。"""
        self.calls += 1
        self.entered.set()
        self.release.wait(5)
        return super().market(start, end)


def test_cancel_running_never_commits_and_serialization(tmp_path):
    """功能：验证取消不提交且不重入provider；输入：阻塞mock；输出：断言。"""
    provider = BlockingProvider()
    service = manager(tmp_path, provider)
    service.start()
    try:
        first = service.submit("market")
        assert provider.entered.wait(2)
        second = service.submit("market")
        assert service.cancel(first["id"])
        assert wait_task(service, first["id"])["status"] == "cancelled"
        assert provider.calls == 1
        assert service.repository.records("market") == []
        provider.release.set()
        assert wait_task(service, second["id"])["status"] == "completed"
    finally:
        provider.release.set()
        service.close()


def test_timeout_visible_before_blocked_provider_returns(tmp_path):
    """功能：验证超时状态即时可见；输入：阻塞mock与短预算；输出：无写库断言。"""
    provider = BlockingProvider()
    service = manager(tmp_path, provider, task_timeout=.05)
    service.start()
    try:
        task = service.submit("market")
        assert provider.entered.wait(2)
        assert wait_task(service, task["id"])["status"] == "timeout"
        assert service.repository.records("market") == []
        provider.release.set()
    finally:
        provider.release.set()
        service.close()


def test_calendar_schedule_default_off_weekend_and_market_hours(tmp_path):
    """功能：验证默认off与真实日历门控；输入：固定时钟；输出：队列断言。"""
    service = manager(tmp_path)
    now = DEMO_NOW.replace(hour=10)
    service.clock = lambda: now
    service.repository.save_calendar([now.date()], start=now.date() - timedelta(days=40),
                                     end=now.date() + timedelta(days=1), source="mock-calendar", fetched_at=now)
    assert not service.schedule_once()
    service.settings.scheduler_enabled = True
    service.settings.mode = "live"
    service.settings.intraday_enabled = True
    assert service.schedule_once()
    scheduled = next(iter(service.cancel_events))
    assert service.repository.document("tasks", scheduled)["scope"] == "quotes"
    assert not service.schedule_once()
    service.cancel(next(iter(service.cancel_events)))
    service.cancel_events.clear()
    # 次日上午允许独立核对；此处只验证周末午间不触发盘中采集。
    now = (now + timedelta(days=1)).replace(hour=12)
    assert not service.schedule_once()
    now -= timedelta(days=1)
    now = now.replace(hour=12)
    assert not service.schedule_once()
    service.settings.mode = "demo"
    assert not service.schedule_once()
    service.close()


def test_share_threshold_alert(tmp_path):
    """功能：验证同源份额阈值与冷却去重；输入：固定记录；输出：告警断言。"""
    service = manager(tmp_path)
    etf = service.repository.etfs()[0]
    values = DemoProvider().shares(date(2025, 3, 27), date(2025, 3, 28), [etf])
    values[1] = values[1].model_copy(update={"shares": values[0].shares * 1.1})
    service.repository.save_records({"shares": values}, DEMO_NOW)
    service.repository.save_calendar([value.trade_date for value in values], start=values[0].trade_date,
                                     end=values[-1].trade_date, source="fixture", fetched_at=DEMO_NOW)
    service.check_share_alerts([etf])
    service.check_share_alerts([etf])
    assert len(service.repository.alerts()) == 1
    assert service.repository.alerts()[0]["code"] == etf.code
