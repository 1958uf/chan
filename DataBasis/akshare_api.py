"""akshare 数据源实现（纯净版）。

功能：从 akshare 获取 A 股/指数 K 线，返回 KBar。
设计：迁移自 DataAPI/AkshareAPI.py，唯一变化 yield CKLine_Unit(dict) -> yield KBar(...)，时间产出 datetime。
依赖：akshare、pandas、Common.CEnum/Common.func_util，不依赖缠论 K 线对象。
"""
from datetime import datetime
from typing import Iterable

import akshare as ak
import pandas as pd

from Common.CEnum import AUTYPE, KL_TYPE
from Common.func_util import str2float

from .kbar import KBar
from .stock_api import CStockApi


def parse_date(date_val) -> datetime:
    """解析 akshare 日期为 datetime。
    功能：兼容 pd.Timestamp、字符串（2021-09-13 / 20210913）及其他类型
    输入：date_val - 日期值
    输出：datetime（时分秒为 0）
    """
    if isinstance(date_val, pd.Timestamp):
        return datetime(date_val.year, date_val.month, date_val.day)
    if isinstance(date_val, str):
        if len(date_val) == 10:  # 2021-09-13
            year = int(date_val[:4])
            month = int(date_val[5:7])
            day = int(date_val[8:10])
        else:  # 20210913
            year = int(date_val[:4])
            month = int(date_val[4:6])
            day = int(date_val[6:8])
        return datetime(year, month, day)
    # 其他类型尝试转换
    date_str = str(date_val)[:10]
    return datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]))


class CAkshare(CStockApi):
    """使用 akshare 获取 A 股数据。
    功能：实现 CStockApi，从 akshare 拉取 K 线返回 KBar。
    """

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CAkshare, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[KBar]:
        """获取 K 线数据。
        功能：个股用 stock_zh_a_hist，指数用 stock_zh_index_daily
        输出：Iterable[KBar]
        """
        # 转换复权类型
        adjust_dict = {AUTYPE.QFQ: "qfq", AUTYPE.HFQ: "hfq", AUTYPE.NONE: ""}
        adjust = adjust_dict.get(self.autype, "qfq")

        # 转换周期类型
        period = self.__convert_type()

        # 格式化日期
        start_date = self.begin_date.replace("-", "") if self.begin_date else "19900101"
        end_date = self.end_date.replace("-", "") if self.end_date else "20991231"

        if self.is_stock:
            df = ak.stock_zh_a_hist(
                symbol=self.code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        else:
            df = ak.stock_zh_index_daily(symbol=self.code)
            df['日期'] = df['date'].astype(str)
            df = df.rename(columns={
                'date': '日期',
                'open': '开盘',
                'high': '最高',
                'low': '最低',
                'close': '收盘',
                'volume': '成交量',
            })
            if 'amount' in df.columns:
                df['成交额'] = df['amount']
            else:
                df['成交额'] = 0
            df = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]

        for _, row in df.iterrows():
            yield KBar(
                time=parse_date(row['日期']),
                open=str2float(row['开盘']),
                high=str2float(row['最高']),
                low=str2float(row['最低']),
                close=str2float(row['收盘']),
                volume=str2float(row['成交量']),
                turnover=str2float(row.get('成交额', 0)),
                turnrate=str2float(row['换手率']) if '换手率' in row else None,
            )

    def SetBasciInfo(self):
        """设置基本信息。"""
        self.name = self.code
        if self.code.startswith('sh') or self.code.startswith('sz'):
            code_num = self.code[2:]
            if code_num.startswith('000') or code_num.startswith('399'):
                self.is_stock = False
            else:
                self.is_stock = True
        else:
            self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def __convert_type(self):
        _dict = {
            KL_TYPE.K_DAY: 'daily',
            KL_TYPE.K_WEEK: 'weekly',
            KL_TYPE.K_MON: 'monthly',
        }
        if self.k_type not in _dict:
            raise Exception(f"akshare不支持{self.k_type}级别的K线数据")
        return _dict[self.k_type]
