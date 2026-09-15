"""ccxt 数据源实现（纯净版）。

功能：从 ccxt（默认 binance）获取数字货币 K 线，返回 KBar。
设计：迁移自 DataAPI/ccxt.py，唯一变化 yield CKLine_Unit(dict, autofix=True) -> yield KBar(...)，时间产出 datetime。
依赖：ccxt、Common.CEnum/Common.func_util，不依赖缠论 K 线对象。
注意：原 ccxt.py 用 autofix=True（OHLC 异常自动修正），底座层不校验，由适配层在转 CKLine_Unit 时按 data_src 传 autofix。
"""
from datetime import datetime
from typing import Iterable

import ccxt

from Common.CEnum import AUTYPE, KL_TYPE
from Common.func_util import kltype_lt_day

from .kbar import KBar
from .stock_api import CStockApi


class CCXT(CStockApi):
    """ccxt 数据源。
    功能：实现 CStockApi，从 ccxt 拉取数字货币 K 线返回 KBar。
    """

    is_connect = None

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CCXT, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[KBar]:
        """获取 K 线数据。
        功能：通过 ccxt.binance 拉取 OHLCV
        输出：Iterable[KBar]（仅 OHLC，无 volume/turnover/turnrate）
        """
        exchange = ccxt.binance()
        timeframe = self.__convert_type()
        since_date = exchange.parse8601(f'{self.begin_date}T00:00:00')
        data = exchange.fetch_ohlcv(self.code, timeframe, since=since_date)

        for item in data:
            # item: [timestamp_ms, open, high, low, close, volume]
            t = datetime.fromtimestamp(item[0] / 1000)
            yield KBar(
                time=t,
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5] if len(item) > 5 else None,
            )

    def SetBasciInfo(self):
        pass

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def __convert_type(self):
        _dict = {
            KL_TYPE.K_DAY: '1d',
            KL_TYPE.K_WEEK: '1w',
            KL_TYPE.K_MON: '1M',
            KL_TYPE.K_5M: '5m',
            KL_TYPE.K_15M: '15m',
            KL_TYPE.K_30M: '30m',
            KL_TYPE.K_60M: '1h',
        }
        return _dict[self.k_type]
