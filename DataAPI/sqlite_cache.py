"""SQLite 缓存兼容层。

功能：转发 DataBasis.sqlite_cache，保留 ChanSqliteCache 类名，旧调用零改动。
设计：直接 re-export DataBasis 的实现，本模块不再维护独立副本。
"""
from DataBasis.sqlite_cache import (  # noqa: F401
    ChanSqliteCache,
    _autype_to_str,
    _last_business_day,
    _to_float,
    _DEFAULT_DB_PATH,
    _AUTYPE_FLAG,
    _AUTYPE_STR,
)
