"""数据源抽象基类（兼容层）。

功能：保留原 CCommonStockApi 接口，委托 DataBasis.CStockApi，旧调用零改动。
设计：get_kl_data 返回 CKLine_Unit（遍历 DataBasis 的 KBar 经适配器转换），
     新代码应直接用 DataBasis。
"""
import abc
from typing import Iterable

from DataBasis.stock_api import CStockApi
from Common.CEnum import AUTYPE, KL_TYPE


class CCommonStockApi(CStockApi):
    """兼容层数据源基类。
    功能：在 DataBasis.CStockApi 基础上提供返回 CKLine_Unit 的 get_kl_data。
    设计：子类只需实现 _data_basis_get_kl_data（返回 KBar），本类负责转 CKLine_Unit。
    """

    @abc.abstractmethod
    def _data_basis_get_kl_data(self):
        """子类委托 DataBasis 实现获取 KBar 迭代器。"""
        pass

    def get_kl_data(self) -> Iterable:
        """返回 CKLine_Unit（兼容旧接口）。
        功能：遍历 DataBasis 的 KBar，经缠论适配器转为 CKLine_Unit
        输出：Iterable[CKLine_Unit]
        """
        from Strategies.chan.chan_adapter import kbar_to_klu, autofix_for
        autofix = autofix_for(self._data_src_for_autofix())
        for kbar in self._data_basis_get_kl_data():
            yield kbar_to_klu(kbar, autofix=autofix)

    def _data_src_for_autofix(self):
        """返回当前数据源类型，供 autofix_for 判定。子类可覆盖。"""
        return None


def create_data_api_legacy(data_src):
    """兼容层工厂：按 DATA_SRC 返回返回 CKLine_Unit 的数据源类。
    功能：对照 DataBasis.create_data_api，返回 DataAPI 下的兼容类
    输入：data_src - DATA_SRC 枚举
    输出：CCommonStockApi 子类
    """
    from Common.CEnum import DATA_SRC
    _map = {
        DATA_SRC.BAO_STOCK: "DataAPI.BaoStockAPI:CBaoStock",
        DATA_SRC.CCXT: "DataAPI.ccxt:CCXT",
        DATA_SRC.CSV: "DataAPI.csvAPI:CSV_API",
        DATA_SRC.AKSHARE: "DataAPI.AkshareAPI:CAkshare",
        DATA_SRC.SQLITE: "DataAPI.SQLiteAPI:SQLite_API",
    }
    import importlib
    module_name, cls_name = _map[data_src].split(":")
    return getattr(importlib.import_module(module_name), cls_name)
