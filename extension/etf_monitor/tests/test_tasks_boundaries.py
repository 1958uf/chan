"""任务外部边界：有效空、契约失败、源健康与模式隔离。"""
import threading
import time
from datetime import timedelta

import pytest

from etf_monitor.config import Settings, default_etfs
from etf_monitor.demo import DEMO_NOW, DemoProvider
from etf_monitor.providers.base import ProviderError
from etf_monitor.services import TaskManager
from etf_monitor.storage import Repository


def execute(tmp_path, provider, kind="market", mode="live"):
    """功能：执行独立边界任务；输入：目录和mock；输出：终态与仓储。"""
    repo = Repository(tmp_path / "boundary.sqlite")
    repo.initialize()
    repo.put_etfs(default_etfs()[:1])
    service = TaskManager(repo, provider, Settings(data_dir=tmp_path, mode=mode), lambda: DEMO_NOW)
    service.start()
    try:
        task = service.submit(kind)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            task = repo.document("tasks", task["id"])
            if task["status"] not in ("pending", "running"):
                return task, repo
            threading.Event().wait(.01)
        raise AssertionError("任务未完成")
    finally:
        service.close()


def test_provider_explicit_empty_preserves_source_message(tmp_path):
    """功能：确认ProviderError empty不是error；输入：有效空mock；输出：健康断言。"""
    class EmptyProvider:
        """显式有效空源。"""
        def market(self, start, end):
            """功能：返回明确有效空；输入：区间；输出：empty异常。"""
            raise ProviderError("upstream", "节假日没有有效记录", status="empty")

    task, repo = execute(tmp_path, EmptyProvider())
    assert task["status"] == "empty"
    assert repo.document("sources", "upstream")["status"] == "empty"
    assert "节假日" in repo.document("sources", "upstream")["message"]
    assert repo.alerts() == []


@pytest.mark.parametrize("response", [None, {}, "wrong"])
def test_provider_non_list_is_visible_failure(tmp_path, response):
    """功能：确认错误契约不能伪装成空列表；输入：非法响应；输出：失败断言。"""
    class WrongProvider:
        """错误响应mock。"""
        def market(self, start, end):
            """功能：返回非法响应；输入：区间；输出：参数值。"""
            return response

    task, repo = execute(tmp_path, WrongProvider())
    assert task["status"] == "failed"
    assert "非列表" in task["message"]
    assert repo.alerts()


def test_live_rejects_demo_records(tmp_path):
    """功能：真实任务不得导入demo；输入：演示provider注入；输出：失败且空库。"""
    task, repo = execute(tmp_path, DemoProvider())
    assert task["status"] == "failed"
    assert "演示" in task["message"]
    assert repo.records("market") == []


def test_calendar_out_of_range_is_visible_failure(tmp_path):
    """功能：拒绝区间外交易日；输入：错误日历mock；输出：无污染断言。"""
    class CalendarProvider:
        """错误日历源。"""
        def calendar(self, start, end):
            """功能：返回未来交易日；输入：区间；输出：未来日期。"""
            return [end + timedelta(days=1)]

    task, repo = execute(tmp_path, CalendarProvider(), "calendar")
    assert task["status"] == "failed"
    assert repo.calendar_days() == []


def test_scheduler_quotes_only_worker_plan(tmp_path):
    """功能：验证盘中计划只有报价；输入：演示mock与内部scope；输出：断言。"""
    repo = Repository(tmp_path / "quotes.sqlite")
    repo.initialize()
    repo.put_etfs(default_etfs()[:1])
    service = TaskManager(repo, DemoProvider(), Settings(data_dir=tmp_path, mode="demo"), lambda: DEMO_NOW)
    service.start()
    try:
        task = service.submit("refresh", quotes_only=True)
        service.pending.join()
        assert repo.document("tasks", task["id"])["status"] == "completed"
        assert repo.records("quotes") and repo.records("shares") == []
    finally:
        service.close()
