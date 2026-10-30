"""传输墙钟、流式大小与熔断可靠性测试。"""
import httpx
import pytest

from etf_monitor.config import Settings
from etf_monitor.providers.base import ProviderError
from etf_monitor.providers.transport import BoundedHTTP


class ChunkStream(httpx.SyncByteStream):
    """固定分块流：用于证明到达上限即拒绝，不先读完整响应。"""
    def __init__(self, tick=None):
        """功能：构造测试流；输入：时钟推进回调；输出：字节流。"""
        self.tick = tick
        self.read = 0

    def __iter__(self):
        """功能：产生有限分块；输入：无；输出：模拟网络字节。"""
        for _ in range(10):
            self.read += 1
            if self.tick:
                self.tick()
            yield b"abcd"


def test_response_limit_stops_stream_early():
    """功能：超过上限不再读取；输入：40字节流5字节限额；输出：仅两块读取。"""
    stream = ChunkStream()
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    transport = BoundedHTTP(Settings(max_retries=0), client=client)
    transport.max_bytes = 5
    with pytest.raises(ProviderError, match="32MiB"):
        transport.get("test", "https://example.test")
    assert stream.read == 2
    transport.close()


def test_slow_stream_total_deadline():
    """功能：慢流不能无限刷新readtimeout；输入：逐块推时钟；输出：墙钟预算拒绝。"""
    now = [0.0]
    stream = ChunkStream(lambda: now.__setitem__(0, now[0] + 2))
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    transport = BoundedHTTP(Settings(request_timeout=1, max_retries=0), client=client)
    transport.clock = lambda: now[0]
    with pytest.raises(ProviderError, match="总时间"):
        transport.get("slow", "https://example.test")
    assert stream.read < 10
    transport.close()


def test_circuit_breaker_and_recovery():
    """功能：连续失败短暂熔断后恢复；输入：503再200；输出：请求次数有界。"""
    now, calls = [0.0], [0]
    def handler(request):
        """功能：模拟故障恢复；输入：请求；输出：固定响应。"""
        calls[0] += 1
        return httpx.Response(503 if calls[0] <= 3 else 200, json={"ok": True})
    transport = BoundedHTTP(Settings(max_retries=0), client=httpx.Client(transport=httpx.MockTransport(handler)))
    transport.clock = lambda: now[0]
    for _ in range(3):
        with pytest.raises(ProviderError):
            transport.get("broken", "https://example.test")
    with pytest.raises(ProviderError, match="熔断"):
        transport.get("broken", "https://example.test")
    assert calls[0] == 3
    now[0] = 61
    assert transport.json("broken", "https://example.test") == {"ok": True}
    transport.close()


def test_non_ascii_download_header_preserved_as_raw_bytes():
    """功能：深交所非ASCII文件头不触发编码异常；输入：原始头；输出：可读取响应。"""
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"xlsx", headers=[(b"content-disposition", b'attachment;filename="\xbb\xf9\xbd\xf0.xlsx"')])))
    transport = BoundedHTTP(Settings(max_retries=0), client=client)
    assert transport.get("excel", "https://example.test").content == b"xlsx"
    transport.close()
