"""真实公开数据契约测试。

功能：显式开启后有限核验两市份额及SQLite往返，默认不联网、不执行。
"""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from etf_monitor.config import Settings, default_etfs
from etf_monitor.providers import LiveProvider
from etf_monitor.storage import Repository

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.getenv("ETF_MONITOR_LIVE_TESTS") != "1", reason="真实接口需要显式ETF_MONITOR_LIVE_TESTS=1")]


def test_live_two_exchange_share_contract(tmp_path):
    """功能：交叉核对已抽查原始份额；输入：两日九ETF；输出：精确往返和幂等。"""
    expected = {
        "510050": (12791466800, 12556566800),
        "510300": (36238087700, 36377587700),
        "510310": (21926444000, 22081244000),
        "510330": (13507449800, 13614549800),
        "588000": (85778668200, 85136668200),
        "588080": (31087628100, 30853628100),
        "159915": (35144454936, 34903454936),
        "159919": (10396116676, 10758816676),
        "159949": (21408785113, 21922785113),
    }
    pool = [e for e in default_etfs() if e.code in expected]
    provider = LiveProvider(Settings(request_timeout=20, max_retries=1))
    repository = Repository(tmp_path / "live-contract.sqlite")
    repository.initialize()
    repository.put_etfs(pool)
    try:
        for exchange in ("sh", "sz"):
            selected = [e for e in pool if e.exchange == exchange]
            records = provider.shares(date(2026, 10, 27), date(2026, 10, 28), selected)
            assert len(records) == len(selected) * 2
            for record in records:
                index = 0 if record.trade_date == date(2026, 10, 27) else 1
                assert record.shares == expected[record.code][index]
            assert repository.save_records({"shares": records}, datetime.now(ZoneInfo("Asia/Shanghai"))) == len(records)
            assert repository.save_records({"shares": records}, datetime.now(ZoneInfo("Asia/Shanghai"))) == 0
    finally:
        provider.close()


def test_live_small_market_contract():
    """功能：核验行情/NAV/日线/日历字段；输入：单ETF两日；输出：合法有限记录。"""
    etf = next(e for e in default_etfs() if e.code == "510300")
    provider = LiveProvider(Settings(request_timeout=25, max_retries=0))
    try:
        quotes = provider.quotes([etf])
        assert quotes and quotes[0].quote_time.tzinfo is not None
        bars = provider.bars(etf, date(2026, 10, 27), date(2026, 10, 28))
        assert {bar.time.date() for bar in bars} == {date(2026, 10, 27), date(2026, 10, 28)}
        navs = provider.navs(etf, date(2026, 10, 27), date(2026, 10, 28))
        assert len(navs) == 2 and all(nav.nav > 0 for nav in navs)
        assert provider.calendar(date(2026, 10, 26), date(2026, 10, 28)) == [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]
    finally:
        provider.close()
