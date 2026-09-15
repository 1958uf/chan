"""ccxt 兼容层。

功能：委托 DataBasis.ccxt_api.CCXT，get_kl_data 返回 CKLine_Unit（autofix=True）。
设计：继承 DataBasis 的 CCXT，重写 get_kl_data 经适配器转 CKLine_Unit。旧调用零改动。
注意：ccxt 原用 autofix=True，由 _data_src_for_autofix 返回 CCXT 触发。
"""
from typing import Iterable

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.ccxt_api import CCXT as _BasisCCXT

from .CommonStockAPI import CCommonStockApi


class CCXT(CCommonStockApi, _BasisCCXT):
    """ccxt 兼容层：返回 CKLine_Unit。"""

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        _BasisCCXT.__init__(self, code, k_type, begin_date, end_date, autype)

    def _data_basis_get_kl_data(self):
        """委托 DataBasis 获取 KBar。"""
        return _BasisCCXT.get_kl_data(self)

    def _data_src_for_autofix(self):
        return DATA_SRC.CCXT
