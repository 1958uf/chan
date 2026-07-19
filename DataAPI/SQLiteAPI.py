"""
SQLite 数据源 API

功能说明：
    - 实现 chan.py 数据源抽象 CCommonStockApi，从本地 SQLite 缓存（chan.db）读取 K 线
    - 替代 csvAPI 作为 main.py 的缓存读取后端
    - 支持 OHLC + volume/turnover/turnrate 字段

设计要点：
    - 复用 CommonStockAPI 抽象，与 BaoStockAPI/AkshareAPI 结构一致
    - db_path 类属性可被外部覆盖（类比 CSV_API.base_dir）
    - get_kl_data 按 (code, k_type, autype, date 区间) 查询并逐行 yield CKLine_Unit
"""
import sqlite3
from typing import Iterable, Optional

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi
from .sqlite_cache import _autype_to_str


# 默认数据库文件路径
_DEFAULT_DB_PATH = "chan.db"

# autype 字符串 -> AUTYPE 枚举
_STR_TO_AUTYPE = {"QFQ": AUTYPE.QFQ, "HFQ": AUTYPE.HFQ, "NONE": AUTYPE.NONE}


def parse_time_column(inp: str) -> CTime:
    """解析时间字符串为 CTime。
    功能：兼容 YYYY-MM-DD（日线）与 YYYY-MM-DD HH:MM 等格式
    输入：inp - 时间字符串
    输出：CTime 对象
    """
    inp = inp.strip()
    if len(inp) == 10:           # 2021-09-13
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = minute = 0
    elif len(inp) == 16:         # 2021-09-13 11:30
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    elif len(inp) == 19:         # 2021-09-13 11:30:00
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    else:
        raise CChanException(f"unknown time column from sqlite:{inp}", ErrCode.SRC_DATA_FORMAT_ERROR)
    return CTime(year, month, day, hour, minute)


def create_item_dict(row: sqlite3.Row) -> dict:
    """将 sqlite3.Row 转换为 CKLine_Unit 所需的字典。
    功能：组装 time + OHLC + volume/turnover/turnrate
    输入：row - sqlite3.Row（含 date/open/high/low/close/volume/turnover/turnrate）
    输出：符合 DATA_FIELD 命名的 dict
    """
    return {
        DATA_FIELD.FIELD_TIME: parse_time_column(row["date"]),
        DATA_FIELD.FIELD_OPEN: str2float(row["open"]),
        DATA_FIELD.FIELD_HIGH: str2float(row["high"]),
        DATA_FIELD.FIELD_LOW: str2float(row["low"]),
        DATA_FIELD.FIELD_CLOSE: str2float(row["close"]),
        DATA_FIELD.FIELD_VOLUME: str2float(row["volume"]) if row["volume"] is not None else None,
        DATA_FIELD.FIELD_TURNOVER: str2float(row["turnover"]) if row["turnover"] is not None else None,
        DATA_FIELD.FIELD_TURNRATE: str2float(row["turnrate"]) if row["turnrate"] is not None else None,
    }


class SQLite_API(CCommonStockApi):
    """从本地 SQLite 缓存读取 K 线的数据源。
    功能：实现 CCommonStockApi，供 CChan 通过 DATA_SRC.SQLITE 调用。
    """

    # 类属性：数据库路径，可被外部覆盖（类比 CSV_API.base_dir）
    db_path = _DEFAULT_DB_PATH
    # 连接句柄（按需开启/关闭，参考 BaoStock 的 is_connect 模式）
    _conn: Optional[sqlite3.Connection] = None

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(SQLite_API, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self) -> Iterable[CKLine_Unit]:
        """从 SQLite 读取 K 线并逐行 yield CKLine_Unit。
        功能：按 code/k_type/autype 与日期区间查询，过滤异常行
        输入：self（code/k_type/begin_date/end_date/autype 由构造函数注入）
        输出：迭代器，每次产出一个 CKLine_Unit
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
            yield CKLine_Unit(create_item_dict(row))

    def SetBasciInfo(self):
        """从 stock_meta 读取股票名称；is_stock 默认 True。
        功能：填充 name/is_stock，供上层判断
        输入：self
        输出：无
        """
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
            # 元信息缺失不影响 K 线读取
            pass

    @classmethod
    def do_init(cls):
        """类初始化（SQLite 无需登录，连接按需建立）。"""
        pass

    @classmethod
    def do_close(cls):
        """关闭 SQLite 连接。"""
        if cls._conn is not None:
            try:
                cls._conn.close()
            except sqlite3.Error:
                pass
            cls._conn = None
