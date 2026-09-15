"""BaoStock 数据源实现（纯净版）。

功能：从 BaoStock 获取 A 股/指数 K 线，返回 KBar。
设计：迁移自 DataAPI/BaoStockAPI.py，唯一变化 yield CKLine_Unit(dict) -> yield KBar(...)，时间产出 datetime。
依赖：baostock、Common.CEnum/Common.func_util，不依赖缠论 K 线对象。
"""
from datetime import datetime
from typing import Iterable

import baostock as bs

from Common.CEnum import AUTYPE, KL_TYPE
from Common.func_util import kltype_lt_day, str2float

from .kbar import KBar
from .stock_api import CStockApi


def parse_time(inp: str) -> datetime:
    """解析 BaoStock 时间字符串为 datetime。
    功能：兼容 10 位日期（2021-09-13）与 17/19 位带时分格式
    输入：inp - 时间字符串
    输出：datetime（日线时分秒为 0）
    """
    if len(inp) == 10:  # 2021-09-13
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = minute = 0
    elif len(inp) == 17:  # 20210902113000000
        year = int(inp[:4])
        month = int(inp[4:6])
        day = int(inp[6:8])
        hour = int(inp[8:10])
        minute = int(inp[10:12])
    elif len(inp) == 19:  # 2021-09-13 11:30:00
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    else:
        raise Exception(f"unknown time column from baostock:{inp}")
    return datetime(year, month, day, hour, minute)


class CBaoStock(CStockApi):
    """BaoStock 数据源。
    功能：实现 CStockApi，从 BaoStock 拉取 K 线返回 KBar。
    """

    is_connect = None

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CBaoStock, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[KBar]:
        """获取 K 线数据。
        功能：天级别以上含 volume/amount/turn，分钟级别仅 OHLC
        输出：Iterable[KBar]
        """
        # 天级别以上才有详细交易信息
        if kltype_lt_day(self.k_type):
            if not self.is_stock:
                raise Exception("没有获取到数据，注意指数是没有分钟级别数据的！")
            fields = "time,open,high,low,close"
        else:
            fields = "date,open,high,low,close,volume,amount,turn"
        autype_dict = {AUTYPE.QFQ: "2", AUTYPE.HFQ: "1", AUTYPE.NONE: "3"}
        rs = bs.query_history_k_data_plus(
            code=self.code,
            fields=fields,
            start_date=self.begin_date,
            end_date=self.end_date,
            frequency=self.__convert_type(),
            adjustflag=autype_dict[self.autype],
        )
        if rs.error_code != '0':
            raise Exception(rs.error_msg)
        has_trade = "volume" in fields.split(",")
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            t = parse_time(row[0])
            if has_trade:
                yield KBar(
                    time=t,
                    open=str2float(row[1]),
                    high=str2float(row[2]),
                    low=str2float(row[3]),
                    close=str2float(row[4]),
                    volume=str2float(row[5]),
                    turnover=str2float(row[6]),
                    turnrate=str2float(row[7]),
                )
            else:
                yield KBar(
                    time=t,
                    open=str2float(row[1]),
                    high=str2float(row[2]),
                    low=str2float(row[3]),
                    close=str2float(row[4]),
                )

    def SetBasciInfo(self):
        rs = bs.query_stock_basic(code=self.code)
        if rs.error_code != '0':
            raise Exception(rs.error_msg)
        code, code_name, ipoDate, outDate, stock_type, status = rs.get_row_data()
        self.name = code_name
        self.is_stock = (stock_type == '1')

    @classmethod
    def do_init(cls):
        if not cls.is_connect:
            cls.is_connect = bs.login()

    @classmethod
    def do_close(cls):
        if cls.is_connect:
            bs.logout()
            cls.is_connect = None

    def __convert_type(self):
        _dict = {
            KL_TYPE.K_DAY: 'd',
            KL_TYPE.K_WEEK: 'w',
            KL_TYPE.K_MON: 'm',
            KL_TYPE.K_5M: '5',
            KL_TYPE.K_15M: '15',
            KL_TYPE.K_30M: '30',
            KL_TYPE.K_60M: '60',
        }
        return _dict[self.k_type]
