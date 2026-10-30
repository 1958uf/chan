"""纯份额任务分市安全提交、取消恢复和持久化日更的离线回归。"""
import threading
import time
from datetime import timedelta

import pytest

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_DAYS, DEMO_NOW, DemoProvider
from etf_monitor.models import ETF
from etf_monitor.services import TaskManager
from etf_monitor.storage import Repository


class PureProvider(DemoProvider):
    """仅日历、目录和份额允许调用的确定性源。"""
    def __init__(self):
        """功能：初始化调用跟踪；输入：无；输出：源实例。"""
        super().__init__()
        self.calls = []
        self.broken = None
        self.bump = 0
        self.entered, self.release = threading.Event(), threading.Event()
        self.block = None

    def calendar(self, start, end):
        """功能：返回固定日历；输入：区间；输出：日期列表并记录调用。"""
        self.calls.append(("calendar", start, end))
        return super().calendar(start, end)

    def catalogue(self, as_of, exchange=None):
        """功能：返回逐市目录；输入：日期/市场；输出：固定目录或错误。"""
        self.calls.append(("catalogue", exchange))
        if exchange == self.broken:
            raise RuntimeError("目录分市失败")
        return super().catalogue(as_of, exchange)

    def shares(self, start, end, etfs):
        """功能：逐市返回份额或可控阻塞/失败；输入：短窗和同市成员；输出：份额。"""
        exchange = etfs[0].exchange
        assert len({item.exchange for item in etfs}) == 1
        assert (end - start).days <= 6
        self.calls.append(("shares", exchange, start, end, [item.code for item in etfs]))
        if exchange == self.block:
            self.entered.set()
            self.release.wait(3)
        if exchange == self.broken:
            raise RuntimeError("份额分市失败")
        return [item.model_copy(update={"shares": item.shares + self.bump}) for item in super().shares(start, end, etfs)]

    def quotes(self, *args):
        """功能：禁止报价调用；输入：任意；输出：断言失败。"""
        raise AssertionError("纯份额不能采报价")

    bars = navs = market = quotes


def manager(tmp_path, provider=None, **kwargs):
    """功能：创建目录而非18观察池服务；输入：目录和源；输出：服务。"""
    repo = Repository(tmp_path / "shares.sqlite")
    repo.initialize()
    repo.put_etfs(default_etfs()[:1])
    repo.sync_catalogue([ETF(code="510999", name="目录沪市", group="独立", exchange="sh"),
                         ETF(code="159999", name="目录深市", group="独立", exchange="sz"),
                         ETF(code="159998", name="候选", group="独立", exchange="sz", classification_status="candidate"),
                         ETF(code="510998", name="禁用", group="独立", exchange="sh", enabled=False)])
    return TaskManager(repo, provider or PureProvider(), Settings(data_dir=tmp_path, mode="demo"), lambda: DEMO_NOW, **kwargs)


def wait(service, task):
    """功能：有界等待任务终态；输入：服务和任务；输出：持久任务。"""
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        current = service.repository.document("tasks", task["id"])
        if current["status"] not in ("pending", "running"):
            return current
        threading.Event().wait(.01)
    raise AssertionError("任务超出等待预算")


def test_shares_uses_catalogue_confirmed_enabled_short_windows_only(tmp_path):
    """功能：验证全目录份额计划、分类筛选和短窗口；输入：独立目录；输出：纯采集断言。"""
    service = manager(tmp_path)
    service.start()
    try:
        result = wait(service, service.submit("shares", group="独立"))
        assert result["status"] == "completed", result
        assert result["codes"] == ["159999", "510999"]
        assert {item.code for item in service.repository.records("shares")} == {"159999", "510999"}
        assert service.repository.records("navs") == service.repository.records("quotes") == []
        assert service.provider.calls[0][0] == "calendar"
        calls = [item for item in service.provider.calls if item[0] == "shares"]
        assert len(calls) > 2 and all((item[3] - item[2]).days <= 6 for item in calls)
    finally:
        service.close()


@pytest.mark.parametrize("broken", ["sh", "sz"])
def test_market_failure_keeps_success_and_retry_revisions(tmp_path, broken):
    """功能：验证两方向分市失败保留成功及重试接受修订；输入：故障市场；输出：partial与审计。"""
    provider = PureProvider()
    provider.broken = broken
    service = manager(tmp_path, provider)
    service.start()
    try:
        result = wait(service, service.submit("shares", start=DEMO_NOW.date() - timedelta(days=2), group="独立"))
        assert result["status"] == "partial"
        assert all(item["exchange"] == broken for item in result["errors"])
        assert {item.code for item in service.repository.records("shares")} == ({"510999"} if broken == "sz" else {"159999"})
        provider.broken, provider.bump = None, 1000
        retry = wait(service, service.submit("shares", start=DEMO_NOW.date() - timedelta(days=2), group="独立"))
        assert retry["status"] == "completed" and service.repository.revision_count() > 0
    finally:
        service.close()


@pytest.mark.parametrize("interrupt", ["cancel", "timeout"])
def test_interrupt_retains_committed_market_and_does_not_commit_late_market(tmp_path, interrupt):
    """功能：取消或超时保留已提交沪市并拒绝迟到深市；输入：阻塞源；输出：安全提交边界。"""
    provider = PureProvider()
    provider.block = "sz"
    service = manager(tmp_path, provider, task_timeout=.8 if interrupt == "timeout" else 3)
    service.start()
    try:
        task = service.submit("shares", start=DEMO_NOW.date(), group="独立")
        assert provider.entered.wait(2)
        if interrupt == "cancel":
            service.cancel(task["id"])
        result = wait(service, task)
        assert result["status"] == ("timeout" if interrupt == "timeout" else "cancelled")
        assert {item.code for item in service.repository.records("shares")} == {"510999"}
        provider.release.set()
        service.pending.join()
        assert {item.code for item in service.repository.records("shares")} == {"510999"}
    finally:
        provider.release.set()
        service.close()


def test_incremental_overlaps_recent_and_duplicates_are_idempotent(tmp_path):
    """功能：验证仅最近回补和未完成任务去重；输入：已有历史；输出：日期及任务ID断言。"""
    service = manager(tmp_path)
    service.start()
    first = service.submit("shares", group="独立")
    assert service.submit("shares", group="独立")["id"] == first["id"]
    try:
        assert wait(service, first)["status"] == "completed"
        second = service.submit("shares", group="独立")
        assert second["start"] == str(DEMO_NOW.date() - timedelta(days=7))
        assert wait(service, second)["status"] == "completed"
        assert service.repository.revision_count() == 0
    finally:
        service.close()


def test_unknown_calendar_fails_closed_and_no_fake_weekday(tmp_path):
    """功能：日历失败停止份额且不猜工作日；输入：失败日历；输出：无份额调用。"""
    service = manager(tmp_path)
    def bad_calendar(start, end):
        """功能：模拟日历不可用；输入：日期；输出：源异常。"""
        raise RuntimeError("日历源失败")
    service.provider.calendar = bad_calendar
    service.start()
    try:
        result = wait(service, service.submit("shares", group="独立"))
        assert result["status"] == "failed" and "日历未闭环" in result["message"]
        assert not service.repository.records("shares")
        assert not service.provider.calls
    finally:
        service.close()


def test_catalogue_task_commits_each_market_and_never_activates_watchpool(tmp_path):
    """功能：目录发现逐市隔离且不扩充观察池；输入：深市失败；输出：沪市发现保留。"""
    service = manager(tmp_path)
    service.provider.broken = "sz"
    service.start()
    try:
        result = wait(service, service.submit("catalogue"))
        assert result["status"] == "partial" and result["errors"][0]["exchange"] == "sz"
        assert len(service.repository.etfs()) == 1
        assert service.repository.catalogue_summary()["total"] > 5
        assert all(item[0] == "catalogue" for item in service.provider.calls)
    finally:
        service.close()


@pytest.mark.parametrize("args", [{"group": "missing"}, {"codes": ["159998"]}, {"codes": ["510998"]},
                                 {"interval": "1m"}, {"codes": []}, {"codes": ["159999", "159999"]}])
def test_shares_rejects_unconfirmed_disabled_and_bad_scopes(tmp_path, args):
    """功能：拒绝候选、禁用和非法周期；输入：错误筛选；输出：参数错误。"""
    service = manager(tmp_path)
    with pytest.raises(ValueError):
        service.submit("shares", **args)


def test_scheduler_default_intraday_off_and_unknown_calendar_loop(tmp_path):
    """功能：验证默认不采盘中并先补真实日历；输入：固定10点时钟；输出：日历任务非行情。"""
    service = manager(tmp_path)
    service.settings.mode, service.settings.scheduler_enabled = "live", True
    service.clock = lambda: DEMO_NOW.replace(hour=10)
    assert service.schedule_once()
    task = service.repository.documents("tasks")[0]
    assert task["kind"] == "calendar"
    assert not service.settings.intraday_enabled
    assert not service.schedule_once()


def test_daily_1817_persists_success_after_commit_restart_and_nextday_verify(tmp_path):
    """功能：验证日更时刻、重启成功去重与次日有限核对；输入：真实质量mock；输出：持久标记。"""
    service = manager(tmp_path)
    provider = service.provider
    original = provider.shares
    def live_shares(start, end, etfs):
        """功能：提供离线真实质量记录；输入：日期与ETF；输出：有效份额模型。"""
        return [item.model_copy(update={"quality": "valid", "source": "mock-exchange"}) for item in original(start, end, etfs)]
    provider.shares = live_shares
    service.settings.mode, service.settings.scheduler_enabled = "live", False
    service.start()
    service.settings.scheduler_enabled = True
    now = DEMO_NOW.replace(hour=18, minute=16)
    service.clock = lambda: now
    service.repository.save_calendar(DEMO_DAYS, start=now.date() - timedelta(days=40), end=now.date() + timedelta(days=1), source="mock-calendar", fetched_at=now)
    # 标记当天目录已成功，专门验证纯份额日更而非目录采集。
    key = f"daily:{now.date()}:{now.date()}:catalogue"
    service.repository.put_document("metadata", "schedule_success:" + key, {"date": str(now.date())})
    assert not service.schedule_once()
    now = now.replace(minute=17)
    assert service.schedule_once()
    task = service.repository.documents("tasks")[0]
    assert task["kind"] == "shares" and not service.repository.document("metadata", "schedule_success:" + task["schedule_key"])
    service.settings.scheduler_enabled = False
    try:
        assert wait(service, task)["status"] == "completed"
        assert service.repository.document("metadata", "schedule_success:" + task["schedule_key"])
    finally:
        service.close()
    restarted = TaskManager(service.repository, provider, service.settings, lambda: now)
    restarted.settings.scheduler_enabled = True
    assert not restarted.schedule_once()
    now = (now + timedelta(days=1)).replace(hour=10)
    assert restarted.schedule_once()
    assert restarted.repository.documents("tasks")[0]["schedule_key"].startswith("verify:")
