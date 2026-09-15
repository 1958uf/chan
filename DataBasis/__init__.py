"""通用行情数据底座。

功能：提供零缠论依赖的纯 OHLCV 行情数据抽象与各数据源实现。
设计：所有数据源的 get_kl_data() 返回 Iterable[KBar]，不依赖 CKLine_Unit。
"""
from .kbar import KBar
from .stock_api import CStockApi
from .data_factory import create_data_api

__all__ = ["KBar", "CStockApi", "create_data_api"]
