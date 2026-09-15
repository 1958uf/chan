"""BaoStock 兼容层。

功能：委托 DataBasis.baostock_api.CBaoStock，get_kl_data 返回 CKLine_Unit。
设计：继承 DataBasis 的 CBaoStock，重写 get_kl_data 经适配器转 CKLine_Unit。旧调用零改动。
"""
from typing import Iterable

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.baostock_api import CBaoStock as _BasisCBaoStock

from .CommonStockAPI import CCommonStockApi


class CBaoStock(CCommonStockApi, _BasisCBaoStock):
    """BaoStock 兼容层：返回 CKLine_Unit。"""

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        _BasisCBaoStock.__init__(self, code, k_type, begin_date, end_date, autype)

    def _data_basis_get_kl_data(self):
        """委托 DataBasis 获取 KBar。"""
        return _BasisCBaoStock.get_kl_data(self)

    def _data_src_for_autofix(self):
        return DATA_SRC.BAO_STOCK
