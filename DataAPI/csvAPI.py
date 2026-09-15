"""CSV 兼容层。

功能：委托 DataBasis.csv_api.CSV_API，get_kl_data 返回 CKLine_Unit。
设计：继承 DataBasis 的 CSV_API，重写 get_kl_data 经适配器转 CKLine_Unit。旧调用零改动。
"""
import os
from typing import Iterable

from Common.CEnum import AUTYPE, KL_TYPE
from DataBasis.csv_api import CSV_API as _BasisCSV_API

from .CommonStockAPI import CCommonStockApi


class CSV_API(CCommonStockApi, _BasisCSV_API):
    """CSV 兼容层：返回 CKLine_Unit。"""

    base_dir = None  # 为 None 时使用默认路径，设置后从该目录读取缓存文件

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=None):
        self.headers_exist = True
        _BasisCSV_API.__init__(self, code, k_type, begin_date, end_date, autype)

    def _data_basis_get_kl_data(self):
        """委托 DataBasis 获取 KBar。"""
        return _BasisCSV_API.get_kl_data(self)
