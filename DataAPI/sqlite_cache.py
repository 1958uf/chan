"""
SQLite 缓存管理模块

功能说明：
    - 管理本地 SQLite 数据库 chan.db，缓存 A 股 K 线数据
    - 提供增量更新、原子写入、去重能力，替代原 CSV 缓存层
    - 补齐 volume/turnover/turnrate 字段
    - 顺带缓存股票元信息（名称/板块/最后更新日期）

设计要点：
    - 主表 kline 按 (code, k_type, date, autype) 唯一，INSERT OR REPLACE 天然去重
    - 增量更新在单个事务内完成，保证原子性（避免半截数据）
    - 依赖 baostock 拉取最新数据，保留断线重连与空行跳过逻辑

使用示例：
    cache = ChanSqliteCache("chan.db")
    if cache.needs_update("sh.600519"):
        cache.update("sh.600519", begin_time="2024-01-01")
"""
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import baostock as bs

from Common.CEnum import AUTYPE


# 默认数据库文件路径（项目根目录下 chan.db，已被 .gitignore 的 *.db 忽略）
_DEFAULT_DB_PATH = "chan.db"

# BaoStock 复权标志映射：autype -> adjustflag
_AUTYPE_FLAG = {AUTYPE.QFQ: "2", AUTYPE.HFQ: "1", AUTYPE.NONE: "3"}
# autype -> 数据库存储字符串
_AUTYPE_STR = {AUTYPE.QFQ: "QFQ", AUTYPE.HFQ: "HFQ", AUTYPE.NONE: "NONE"}


def _autype_to_str(autype: AUTYPE) -> str:
    """将 AUTYPE 枚举转换为数据库存储字符串。
    功能：复权方式枚举 -> 'QFQ'/'HFQ'/'NONE'
    输入：autype - AUTYPE 枚举值
    输出：对应字符串；未知则默认 'QFQ'
    """
    return _AUTYPE_STR.get(autype, "QFQ")


def _last_business_day() -> date:
    """返回最近一个已收盘的交易日（忽略节假日，仅排除周末）。
    若今天是工作日且已过 15:30（A股收盘），返回今天；否则返回上一个工作日。
    周一/周六/周日未收盘时返回上周五，周二~周五未收盘时返回昨天。
    """
    today = date.today()
    now = datetime.now()
    wd = today.weekday()   # 0=周一 … 6=周日
    # 工作日且已过收盘时间，今天数据已可用
    if wd < 5 and (now.hour > 15 or (now.hour == 15 and now.minute >= 30)):
        return today
    if wd == 0:            # 周一未收盘 → 上周五
        return today - timedelta(days=3)
    elif wd == 6:          # 周日 → 上周五
        return today - timedelta(days=2)
    elif wd == 5:          # 周六 → 上周五
        return today - timedelta(days=1)
    else:                  # 周二~周五未收盘 → 昨天
        return today - timedelta(days=1)


class ChanSqliteCache:
    """SQLite K 线缓存管理器。
    功能：封装 chan.db 的建表、增量更新、查询、元信息维护等操作。
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        """初始化缓存管理器并确保表结构存在。
        输入：db_path - SQLite 数据库文件路径，默认 'chan.db'
        输出：无（创建连接与表结构）
        """
        self.db_path = db_path
        # 允许父目录存在性由调用方保证；连接时自动创建库文件
        self._conn = sqlite3.connect(self.db_path)
        # 让查询结果可用列名访问
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """创建 kline 与 stock_meta 表（如不存在）。
        功能：建立主表与元信息表，含主键约束与索引。
        输入：无
        输出：无
        """
        cur = self._conn.cursor()
        # 主表：按 (code, k_type, date, autype) 唯一，天然去重
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kline (
                code      TEXT NOT NULL,
                k_type    TEXT NOT NULL,
                date      TEXT NOT NULL,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                volume    REAL,
                turnover  REAL,
                turnrate  REAL,
                autype    TEXT NOT NULL,
                PRIMARY KEY (code, k_type, date, autype)
            )
        """)
        # 区间查询索引：某只股票某周期某复权按日期范围
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kline_query
            ON kline (code, k_type, autype, date)
        """)
        # 元信息表：缓存股票名称/板块/最后更新日期
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_meta (
                code        TEXT PRIMARY KEY,
                name        TEXT,
                board       TEXT,
                last_update TEXT
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "ChanSqliteCache":
        """支持 with 语句，返回自身。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出 with 语句时自动关闭连接。"""
        self.close()

    # ------------------------------------------------------------------
    # 查询类
    # ------------------------------------------------------------------
    def get_last_date(self, code: str, k_type: str = "day",
                      autype: AUTYPE = AUTYPE.QFQ) -> Optional[str]:
        """查询某只股票某周期缓存中的最后一条日期。
        功能：返回 MAX(date)，无数据返回 None
        输入：code - 股票代码；k_type - 周期；autype - 复权方式
        输出：日期字符串（如 '2026-07-16'）或 None
        """
        cur = self._conn.execute(
            "SELECT MAX(date) AS d FROM kline WHERE code=? AND k_type=? AND autype=?",
            (code, k_type, _autype_to_str(autype)),
        )
        row = cur.fetchone()
        return row["d"] if row and row["d"] is not None else None

    def needs_update(self, code: str, k_type: str = "day",
                     autype: AUTYPE = AUTYPE.QFQ) -> bool:
        """判断缓存是否需要更新（无数据 or 最后日期 < 最近交易日）。
        功能：对比最后缓存日期与最近交易日，决定是否触发增量更新
        输入：code - 股票代码；k_type - 周期；autype - 复权方式
        输出：True 表示需要更新
        """
        last = self.get_last_date(code, k_type, autype)
        if not last:
            return True
        try:
            last_date = date.fromisoformat(last[:10])
        except ValueError:
            return True
        return last_date < _last_business_day()

    def get_stock_name(self, code: str) -> str:
        """从 stock_meta 读取股票名称。
        功能：返回缓存的股票名称，无记录返回空字符串
        输入：code - 股票代码
        输出：股票名称或 ''
        """
        cur = self._conn.execute(
            "SELECT name FROM stock_meta WHERE code=?", (code,)
        )
        row = cur.fetchone()
        return row["name"] if row and row["name"] else ""

    def get_stock_names(self, codes: List[str]) -> dict:
        """批量读取股票名称。
        功能：一次性查 stock_meta，返回 {code: name}
        输入：codes - 股票代码列表
        输出：{code: name} 字典，缺失的 code 值为 ''
        """
        if not codes:
            return {}
        placeholders = ",".join("?" * len(codes))
        cur = self._conn.execute(
            f"SELECT code, name FROM stock_meta WHERE code IN ({placeholders})",
            codes,
        )
        name_map = {c: "" for c in codes}
        for row in cur.fetchall():
            name_map[row["code"]] = row["name"] or ""
        return name_map

    # ------------------------------------------------------------------
    # 写入类
    # ------------------------------------------------------------------
    def upsert_many(self, code: str, k_type: str, autype: AUTYPE,
                    rows: List[Tuple]) -> int:
        """批量写入 K 线数据（INSERT OR REPLACE，去重）。
        功能：在一个事务内写入多行，保证原子性
        输入：
            code   - 股票代码
            k_type - 周期
            autype - 复权方式
            rows   - 行列表，每行 (date, open, high, low, close, volume, turnover, turnrate)
        输出：实际写入行数
        """
        if not rows:
            return 0
        autype_str = _autype_to_str(autype)
        sql = """
            INSERT OR REPLACE INTO kline
                (code, k_type, date, open, high, low, close, volume, turnover, turnrate, autype)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = [
            (code, k_type, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], autype_str)
            for r in rows
        ]
        with self._conn:  # 事务上下文，异常自动回滚
            self._conn.executemany(sql, params)
        return len(params)

    def upsert_stock_meta(self, code: str, name: str, board: str = "",
                          last_update: str = "") -> None:
        """写入或更新股票元信息。
        功能：缓存股票名称/板块/最后更新日期
        输入：code/name/board/last_update
        输出：无
        """
        with self._conn:
            self._conn.execute("""
                INSERT OR REPLACE INTO stock_meta (code, name, board, last_update)
                VALUES (?, ?, ?, ?)
            """, (code, name, board, last_update))

    def update(self, code: str, begin_time: str,
               autype: AUTYPE = AUTYPE.QFQ, k_type: str = "day",
               bs_login_fn=None, on_reconnect=None) -> int:
        """增量（或全量）更新某只股票的 K 线缓存。
        功能：查 MAX(date) -> 从次日起 BaoStock 拉取 -> 事务内写入（原子、去重）
        输入：
            code         - 股票代码，如 'sh.600519'
            begin_time   - 全量拉取起始日期，如 '2024-01-01'
            autype       - 复权方式
            k_type       - 周期，默认 'day'
            bs_login_fn  - 可选的登录回调（登录态由调用方管理），默认假定已登录
            on_reconnect - 断线重连回调，签名 () -> None
        输出：本次新增/更新的行数
        """
        if bs_login_fn is not None:
            bs_login_fn()

        autype_flag = _AUTYPE_FLAG.get(autype, "2")
        autype_str = _autype_to_str(autype)

        # 增量起点：已有数据则从次日起，否则用 begin_time 全量
        last = self.get_last_date(code, k_type, autype)
        if last:
            start = (date.fromisoformat(last[:10]) + timedelta(days=1)).isoformat()
        else:
            start = begin_time

        rs = bs.query_history_k_data_plus(
            code=code,
            fields="date,open,high,low,close,volume,amount,turn",
            start_date=start,
            end_date=None,
            frequency="d" if k_type == "day" else k_type,
            adjustflag=autype_flag,  # 前复权等，与 AUTYPE 对应
        )
        if rs.error_code != "0":
            raise Exception(rs.error_msg)

        rows: List[Tuple] = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            # date, open, high, low, close, volume, amount, turn
            # 跳过 OHLC 任一字段为空的行（停牌日 BaoStock 返回空字符串，会导致缠论计算越界）
            if any(v == "" for v in row[1:5]):
                continue
            d = row[0]
            rows.append((
                d,
                _to_float(row[1]),   # open
                _to_float(row[2]),   # high
                _to_float(row[3]),   # low
                _to_float(row[4]),   # close
                _to_float(row[5]),   # volume
                _to_float(row[6]),   # amount -> turnover
                _to_float(row[7]),   # turn -> turnrate
            ))

        # 断线重连：拉取阶段异常时由调用方处理；此处仅写入已得数据
        n = self.upsert_many(code, k_type, autype, rows)
        # 更新元信息最后更新日期
        if rows:
            self.upsert_stock_meta(code, name="", last_update=rows[-1][0])
        return n

    def row_count(self, code: str = None, k_type: str = "day") -> int:
        """统计行数（用于迁移/校验）。
        功能：可选按股票过滤，返回 kline 表行数
        输入：code - 可选；k_type - 周期
        输出：行数
        """
        if code:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS c FROM kline WHERE code=? AND k_type=?",
                (code, k_type),
            )
        else:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS c FROM kline WHERE k_type=?", (k_type,)
            )
        return cur.fetchone()["c"]


def _to_float(v) -> float:
    """安全转浮点：空字符串/None -> 0.0。
    功能：兼容 BaoStock 停牌日返回的空值
    输入：v - 字符串或数值
    输出：float
    """
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0
