"""SQLite 数据源实现（纯净版）。

功能：从本地 SQLite 缓存（chan.db）读取 K 线，返回 KBar。
设计：迁移自 DataAPI/SQLiteAPI.py，唯一变化 yield CKLine_Unit(dict) -> yield KBar(...)，时间产出 datetime。
依赖：Common.CEnum/Common.ChanException/Common.func_util，不依赖缠论 K 线对象。
"""
import sqlite3
from datetime import datetime
from typing import Iterable, Optional

from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.func_util import str2float

from .kbar import KBar
from .stock_api import CStockApi
from .sqlite_cache import _autype_to_str


# 默认数据库文件路径
_DEFAULT_DB_PATH = "chan.db"


def parse_time(inp: str) -> datetime:
    """解析 SQLite 时间字符串为 datetime。
    功能：兼容 YYYY-MM-DD（日线）与 YYYY-MM-DD HH:MM 等格式
    输入：inp - 时间字符串
    输出：datetime
    """
    inp = inp.strip()
    if len(inp) == 10:  # 2021-09-13
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = minute = 0
    elif len(inp) == 16:  # 2021-09-13 11:30
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    elif len(inp) == 19:  # 2021-09-13 11:30:00
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    else:
        raise CChanException(f"unknown time column from sqlite:{inp}", ErrCode.SRC_DATA_FORMAT_ERROR)
    return datetime(year, month, day, hour, minute)


class SQLite_API(CStockApi):
    """从本地 SQLite 缓存读取 K 线的数据源。
    功能：实现 CStockApi，供通过 DATA_SRC.SQLITE 调用。
    """

    db_path = _DEFAULT_DB_PATH
    _conn: Optional[sqlite3.Connection] = None

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(SQLite_API, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[KBar]:
        """从 SQLite 读取 K 线并逐行 yield KBar。
        功能：按 code/k_type/autype 与日期区间查询，过滤异常行
        输出：Iterable[KBar]
        """
        k_type_str = self.k_type.name[2:].lower()  # K_DAY -> day
        autype_str = _autype_to_str(self.autype)

        if SQLite_API._conn is None:
            SQLite_API._conn = sqlite3.connect(SQLite_API.db_path)
            SQLite_API._conn.row_factory = sqlite3.Row

        sql = (
            "SELECT date, open, high, low, close, volume, turnover, turnrate "
            "FROM kline "
            "WHERE code=? AND k_type=? AND autype=? "
        )
        params = [self.code, k_type_str, autype_str]
        if self.begin_date is not None:
            sql += " AND date >= ?"
            params.append(self.begin_date)
        if self.end_date is not None:
            sql += " AND date <= ?"
            params.append(self.end_date)
        sql += " ORDER BY date"

        try:
            cur = SQLite_API._conn.execute(sql, params)
        except sqlite3.Error as e:
            raise CChanException(f"sqlite query error: {e}", ErrCode.SRC_DATA_NOT_FOUND)

        for row in cur:
            # 跳过 OHLC 为空/异常的行
            if row["open"] is None or row["close"] is None:
                continue
            yield KBar(
                time=parse_time(row["date"]),
                open=str2float(row["open"]),
                high=str2float(row["high"]),
                low=str2float(row["low"]),
                close=str2float(row["close"]),
                volume=str2float(row["volume"]) if row["volume"] is not None else None,
                turnover=str2float(row["turnover"]) if row["turnover"] is not None else None,
                turnrate=str2float(row["turnrate"]) if row["turnrate"] is not None else None,
            )

    def SetBasciInfo(self):
        """从 stock_meta 读取股票名称；is_stock 默认 True。"""
        self.is_stock = True
        self.name = None
        if SQLite_API._conn is None:
            SQLite_API._conn = sqlite3.connect(SQLite_API.db_path)
            SQLite_API._conn.row_factory = sqlite3.Row
        try:
            cur = SQLite_API._conn.execute(
                "SELECT name FROM stock_meta WHERE code=?", (self.code,)
            )
            row = cur.fetchone()
            if row and row["name"]:
                self.name = row["name"]
        except sqlite3.Error:
            pass

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        if cls._conn is not None:
            try:
                cls._conn.close()
            except sqlite3.Error:
                pass
            cls._conn = None
