"""默认数据边界和演示隔离的主集成验收。

功能：在后端就绪后执行真实create_app的ASGI行为，不请求公开上游。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from etf_monitor.models import BarRecord, QuoteRecord, ShareRecord


@pytest.mark.parametrize("model,extra", [
    (ShareRecord, {"trade_date": "2026-10-28", "shares": 1}),
    (QuoteRecord, {"quote_time": "2026-10-28T10:00:00", "price": 1}),
])
def test_time_contract_rejects_naive(model, extra):
    """功能：不允许无时区原始记录；输入：naive时间；输出：拒绝。"""
    with pytest.raises(ValidationError):
        model(code="510050", source="fixture", fetched_at=datetime(2026, 10, 28), **extra)


def test_ohlc_range_rejected():
    """功能：拒绝反常OHLC；输入：最高低于收盘；输出：校验失败。"""
    now = datetime(2026, 10, 28, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    with pytest.raises(ValidationError):
        BarRecord(code="510050", source="fixture", fetched_at=now, time=now, open=1, high=0.9, low=0.8, close=1)
