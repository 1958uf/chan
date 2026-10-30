"""共享成员生命周期契约回归。"""
import pytest
from pydantic import ValidationError

from etf_monitor.models import ETF


def test_delisted_on_contract_matches_history():
    """功能：真实模型支持退出日期；输入：成员生命周期；输出：合法/非法边界。"""
    item = ETF(code="510300", name="测试", group="测试", exchange="sh", listed_on="2020-01-01", delisted_on="2026-10-28")
    assert item.delisted_on.isoformat() == "2026-10-28"
    with pytest.raises(ValidationError):
        ETF(code="510300", name="测试", group="测试", exchange="sh", listed_on="2026-10-28", delisted_on="2026-10-28")
