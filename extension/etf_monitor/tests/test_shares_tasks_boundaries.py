"""纯份额任务异常响应、失败退避及重启恢复边界。"""
from datetime import timedelta

import pytest

from etf_monitor.demo import DEMO_DAYS, DEMO_NOW
from etf_monitor.services import TaskManager
from test_shares_tasks_mainline import PureProvider, manager, wait


@pytest.mark.parametrize("fault", ["duplicate", "foreign", "future", "nontrade", "missing", "empty", "invalid"])
def test_invalid_market_response_visible_and_no_cross_market_loss(tmp_path, fault):
    """功能：故障市异常返回不可标记成功，另一市成功保留；输入：故障类型；输出：错误隔离。"""
    provider = PureProvider()
    original = provider.shares
    def faulty(start, end, etfs):
        """功能：注入单市契约异常；输入：短窗成员；输出：错误记录或正常列表。"""
        values = original(start, end, etfs)
        if etfs[0].exchange == "sz":
            return values
        if fault == "duplicate":
            return values + values[:1]
        if fault == "foreign":
            return [values[0].model_copy(update={"code": "159999"})]
        if fault == "future":
            return [values[0].model_copy(update={"fetched_at": DEMO_NOW + timedelta(days=1)})]
        if fault == "nontrade":
            return [values[0].model_copy(update={"trade_date": start})]
        if fault == "missing":
            return values[-1:]
        if fault == "empty":
            return []
        return None
    provider.shares = faulty
    service = manager(tmp_path, provider)
    service.start()
    try:
        result = wait(service, service.submit("shares", start=DEMO_NOW.date() - timedelta(days=5), group="独立"))
        assert result["status"] == "partial" and result["errors"]
        assert service.repository.document("sources", "shares.sh")["status"] == "error"
        records = service.repository.records("shares")
        assert any(item.code == "159999" for item in records)
        assert not service.repository.document("metadata", "shares_last_success")
        if fault != "missing":
            assert not any(item.code == "510999" for item in records)
    finally:
        service.close()


def test_failed_scheduled_shares_retry_backoff_bounded_and_restart_persistent(tmp_path):
    """功能：失败不写成功日期、15分钟退避最多3次且重启保留；输入：两市失败mock；输出：持久预算。"""
    provider = PureProvider()
    def broken(start, end, etfs):
        """功能：模拟两市采集失败；输入：短窗；输出：异常。"""
        raise RuntimeError("所有交易所暂不可用")
    provider.shares = broken
    service = manager(tmp_path, provider)
    service.settings.mode = "live"
    now = DEMO_NOW.replace(hour=18, minute=17)
    service.clock = lambda: now
    service.repository.save_calendar(DEMO_DAYS, start=now.date() - timedelta(days=40), end=now.date(), source="mock-calendar", fetched_at=now)
    catalogue_key = f"daily:{now.date()}:{now.date()}:catalogue"
    service.repository.put_document("metadata", "schedule_success:" + catalogue_key, {"date": str(now.date())})
    service.start()
    service.settings.scheduler_enabled = True
    try:
        assert service.schedule_once()
        task = service.repository.documents("tasks")[0]
        assert wait(service, task)["status"] == "failed"
        key = task["schedule_key"]
        assert not service.repository.document("metadata", "schedule_success:" + key)
        assert not service.schedule_once()
        for _ in range(2):
            now += timedelta(minutes=15)
            assert service.schedule_once()
            assert wait(service, service.repository.documents("tasks")[0])["status"] == "failed"
        now += timedelta(minutes=15)
        assert not service.schedule_once()
        assert service.repository.document("metadata", "schedule_attempt:" + key)["attempts"] == 3
    finally:
        service.close()
    restarted = TaskManager(service.repository, provider, service.settings, lambda: now)
    assert not restarted.schedule_once()
    # 自动预算耗尽不阻止用户手工显式重试。
    assert restarted.submit("shares")["status"] == "pending"


def test_restart_interrupted_partial_commit_keeps_data_without_success(tmp_path):
    """功能：重启将中断任务失败并保留早已提交的数据；输入：模拟中断持久库；输出：恢复与重试。"""
    service = manager(tmp_path)
    etf = next(item for item in service.repository.catalogue(limit=5000) if item.code == "510999")
    service.repository.save_records({"shares": service.provider.shares(DEMO_NOW.date(), DEMO_NOW.date(), [etf])}, DEMO_NOW)
    service.repository.put_document("tasks", "interrupted-shares", {"id": "interrupted-shares", "kind": "shares", "status": "running"})
    service.start()
    try:
        assert service.repository.document("tasks", "interrupted-shares")["status"] == "failed"
        assert service.repository.records("shares")
        assert not service.repository.document("metadata", "shares_last_success")
        result = wait(service, service.submit("shares", start=DEMO_NOW.date(), group="独立"))
        assert result["status"] == "completed"
        assert service.repository.document("metadata", "shares_last_success")["date"] == str(DEMO_NOW.date())
    finally:
        service.close()


def test_new_member_listing_does_not_require_prelisting_records(tmp_path):
    """功能：新成员只要求上市后的交易日，不误判历史缺失；输入：本日上市产品；输出：日更成功。"""
    service = manager(tmp_path)
    item = next(item for item in service.repository.catalogue(limit=5000) if item.code == "510999")
    service.repository.sync_catalogue([item.model_copy(update={"listed_on": DEMO_NOW.date()})])
    original = service.provider.shares
    def listed_only(start, end, etfs):
        """功能：只返回上市后份额；输入：窗口成员；输出：真实上市范围样本。"""
        values = original(start, end, etfs)
        return [record for record in values if record.code != "510999" or record.trade_date >= DEMO_NOW.date()]
    service.provider.shares = listed_only
    service.start()
    try:
        result = wait(service, service.submit("shares", group="独立"))
        assert result["status"] == "completed", result
    finally:
        service.close()


def test_execute_rechecks_disabled_catalogue_member(tmp_path):
    """功能：任务入队后禁用成员仍不可采；输入：排队后禁用目录；输出：执行筛选。"""
    service = manager(tmp_path)
    service.start()
    provider = service.provider
    provider.block = "sh"
    task = service.submit("shares", start=DEMO_NOW.date(), group="独立")
    assert provider.entered.wait(2)
    service.repository.set_catalogue_enabled("159999", False)
    service.cancel(task["id"])
    provider.release.set()
    service.pending.join()
    task = service.submit("shares", start=DEMO_NOW.date(), group="独立")
    try:
        result = wait(service, task)
        assert result["status"] == "completed" and result["codes"] == ["510999"]
    finally:
        provider.release.set()
        service.close()
