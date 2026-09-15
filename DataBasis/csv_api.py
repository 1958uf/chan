"""CSV 数据源实现（纯净版）。

功能：从本地 CSV 文件读取 K 线，返回 KBar。
设计：迁移自 DataAPI/csvAPI.py，唯一变化 yield CKLine_Unit(dict) -> yield KBar(...)，时间产出 datetime。
依赖：Common.CEnum/Common.func_util，不依赖缠论 K 线对象。
"""
import os
from datetime import datetime
from typing import Iterable

from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.func_util import str2float

from .kbar import KBar
from .stock_api import CStockApi


def parse_time(inp: str) -> datetime:
    """解析 CSV 时间字符串为 datetime。
    功能：兼容 10/17/19 位时间格式
    输入：inp - 时间字符串
    输出：datetime
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
        raise Exception(f"unknown time column from csv:{inp}")
    return datetime(year, month, day, hour, minute)


# CSV 列顺序（与原 csvAPI 一致：time, open, high, low, close）
_CSV_COLUMNS = ["time", "open", "high", "low", "close"]


class CSV_API(CStockApi):
    """CSV 数据源。
    功能：实现 CStockApi，从本地 CSV 文件读取 K 线返回 KBar。
    """

    base_dir = None  # 为 None 时使用默认路径（项目根目录），设置后从该目录读取缓存文件

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=None):
        self.headers_exist = True  # 第一行是否是标题
        self.columns = _CSV_COLUMNS
        self.time_column_idx = self.columns.index("time")
        super(CSV_API, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[KBar]:
        """从 CSV 读取 K 线。
        功能：按 begin_date/end_date 过滤，逐行产出 KBar（仅 OHLC）
        输出：Iterable[KBar]
        """
        cur_path = os.path.dirname(os.path.realpath(__file__))
        k_type = self.k_type.name[2:].lower()
        if CSV_API.base_dir is not None:
            file_path = os.path.join(CSV_API.base_dir, f"{self.code}_{k_type}.csv")
        else:
            file_path = f"{cur_path}/../{self.code}_{k_type}.csv"
        if not os.path.exists(file_path):
            raise CChanException(f"file not exist: {file_path}", ErrCode.SRC_DATA_NOT_FOUND)

        for line_number, line in enumerate(open(file_path, 'r')):
            if self.headers_exist and line_number == 0:
                continue
            data = line.strip("\n").split(",")
            if len(data) != len(self.columns):
                raise CChanException(f"file format error: {file_path}", ErrCode.SRC_DATA_FORMAT_ERROR)
            if self.begin_date is not None and data[self.time_column_idx] < self.begin_date:
                continue
            if self.end_date is not None and data[self.time_column_idx] > self.end_date:
                continue
            yield KBar(
                time=parse_time(data[0]),
                open=str2float(data[1]),
                high=str2float(data[2]),
                low=str2float(data[3]),
                close=str2float(data[4]),
            )

    def SetBasciInfo(self):
        pass

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass
