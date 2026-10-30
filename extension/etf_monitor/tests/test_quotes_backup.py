"""独立行情备用源契约：真实源时间、单位和部分质量。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from etf_monitor.config import Settings, default_etfs
from etf_monitor.providers import LiveProvider, ProviderError


def provider_for(handler):
    """功能：创建有限HTTP替身；输入：响应函数；输出：可测试源实例。"""
    from etf_monitor.providers.transport import BoundedHTTP
    transport = BoundedHTTP(Settings(max_retries=0), client=httpx.Client(transport=httpx.MockTransport(handler)))
    return LiveProvider(Settings(max_retries=0), http=transport, clock=lambda: datetime(2026, 10, 28, 10, tzinfo=ZoneInfo("Asia/Shanghai")))


def backup_text(code="510050", stamp="20261028095930"):
    """功能：构造腾讯原始字段；输入：代码/时间；输出：GB18030响应字节。"""
    values = [""] * 60
    values[1], values[2], values[3], values[4] = "上证50ETF", code, "3.1", "3.0"
    values[6], values[30], values[37] = "100", stamp, "12.5"
    return f'v_sh{code}="{"~".join(values)}";'.encode("gb18030")


def test_primary_failure_uses_explicit_backup_partial():
    """功能：主源错误不静默伪成功；输入：503/腾讯快照；输出：partial和准确单位。"""
    def handler(request):
        """功能：模拟独立主备用；输入：URL；输出：对应响应。"""
        return httpx.Response(503) if request.url.host == "push2.eastmoney.com" else httpx.Response(200, content=backup_text())
    p = provider_for(handler)
    record = p.quotes(default_etfs()[:1])[0]
    assert record.source == "tencent:quotes:backup" and record.quality == "partial"
    assert record.volume == 10000 and record.amount == 125000
    assert record.iopv is None and record.premium_pct is None
    p.close()


@pytest.mark.parametrize("content", [b"invalid", backup_text("510300"), backup_text(stamp="20300101000000")])
def test_backup_invalid_is_error(content):
    """功能：备用缺失/身份/未来时间拒绝；输入：坏响应；输出：两源失败可见。"""
    p = provider_for(lambda request: httpx.Response(503) if request.url.host == "push2.eastmoney.com" else httpx.Response(200, content=content))
    with pytest.raises(ProviderError, match="备用失败"):
        p.quotes(default_etfs()[:1])
    p.close()
