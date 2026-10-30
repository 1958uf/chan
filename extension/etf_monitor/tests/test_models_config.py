"""数据契约与配置校验测试。

功能：验证新系统基础边界，不访问网络或主工程数据库。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from etf_monitor.config import Settings, default_etfs
from etf_monitor.models import BarRecord, ETF, HolderRecord, QuoteRecord, ShareRecord


def test_pool_contains_core_indices():
    """功能：核对默认池；输入：默认配置；输出：所有核心代码存在。"""
    codes = {item.code for item in default_etfs()}
    assert {"510050", "510300", "510310", "510330", "159919", "588000", "588080", "159915", "159949"} <= codes


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_shares_reject_invalid_values(value):
    """功能：拒绝坏数值；输入：非有限或负份额；输出：校验错误。"""
    with pytest.raises(ValidationError):
        ShareRecord(code="159915", trade_date="2026-10-28", shares=value, source="test", fetched_at=datetime.now(ZoneInfo("Asia/Shanghai")))


@pytest.mark.parametrize("code", ["../db", "15991", "1234567", "sh.510050"])
def test_etf_reject_invalid_codes(code):
    """功能：校验标的代码；输入：非六位代码；输出：拒绝。"""
    with pytest.raises(ValidationError):
        ETF(code=code, name="测试", group="测试", exchange="sh")


def test_settings_bounds_and_env(monkeypatch, tmp_path):
    """功能：限制运行参数；输入：环境及越界轮询；输出：配置正确。"""
    with pytest.raises(ValidationError):
        Settings(quote_interval=1)
    monkeypatch.setenv("ETF_MONITOR_HOME", str(tmp_path))
    monkeypatch.setenv("ETF_MONITOR_MODE", "demo")
    monkeypatch.setenv("ETF_MONITOR_SCHEDULER", "1")
    config = Settings.from_env()
    assert config.data_dir == tmp_path
    assert config.mode == "demo"
    assert config.scheduler_enabled is True


def test_timezones_and_ohlc_contract():
    """功能：验证时区及OHLC边界；输入：合法与非法记录；输出：分别接受拒绝。"""
    aware = datetime(2026, 10, 28, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    base = {"code": "510050", "source": "fixture", "fetched_at": aware}
    ShareRecord(**base, trade_date="2026-10-28", shares=0)
    QuoteRecord(**base, quote_time=aware, price=1)
    BarRecord(**base, time=aware, open=1, high=2, low=0.5, close=1.5)
    with pytest.raises(ValidationError):
        QuoteRecord(**base, quote_time=datetime(2026, 10, 28), price=1)
    with pytest.raises(ValidationError):
        BarRecord(**base, time=datetime(2026, 10, 28), open=1, high=2, low=0.5, close=1)
    with pytest.raises(ValidationError):
        BarRecord(**base, time=aware, open=1, high=2, low=1.2, close=1)
    with pytest.raises(ValidationError):
        HolderRecord(**base, report_date="2026-06-30", holder="测试", ratio_pct=101)
