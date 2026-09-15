"""数据源工厂。

功能：按 DATA_SRC 返回对应的数据源类（返回 KBar 的纯净实现）。
设计：对照 Chan.py:GetStockAPI 抽离，集中管理数据源映射，避免散落各处。
依赖：Common.CEnum，不依赖缠论 K 线对象。
"""
import importlib

from Common.CEnum import DATA_SRC
from Common.ChanException import CChanException, ErrCode


def create_data_api(data_src) -> type:
    """按 DATA_SRC 返回数据源类。
    功能：集中映射 DATA_SRC -> 数据源类（返回 KBar 的实现）
    输入：data_src - DATA_SRC 枚举或 'custom:模块名.类名' 字符串
    输出：数据源类（CStockApi 子类）
    """
    _map = {
        DATA_SRC.BAO_STOCK: "DataBasis.baostock_api:CBaoStock",
        DATA_SRC.CCXT: "DataBasis.ccxt_api:CCXT",
        DATA_SRC.CSV: "DataBasis.csv_api:CSV_API",
        DATA_SRC.AKSHARE: "DataBasis.akshare_api:CAkshare",
        DATA_SRC.SQLITE: "DataBasis.sqlite_api:SQLite_API",
    }
    if data_src in _map:
        module_name, cls_name = _map[data_src].split(":")
        module = importlib.import_module(module_name)
        return getattr(module, cls_name)
    # 支持自定义数据源字符串：custom:模块名.类名
    assert isinstance(data_src, str)
    if data_src.find("custom:") < 0:
        raise CChanException("load src type error", ErrCode.SRC_DATA_TYPE_ERR)
    package_info = data_src.split(":")[1]
    package_name, cls_name = package_info.split(".")
    module = importlib.import_module(f"DataBasis.{package_name}")
    return getattr(module, cls_name)
