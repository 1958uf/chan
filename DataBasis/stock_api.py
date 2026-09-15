"""数据源抽象基类。

功能：定义所有数据源的统一接口契约，get_kl_data() 返回 Iterable[KBar]。
设计：对照 DataAPI/CommonStockAPI.py 去掉 CKLine_Unit 依赖，保留 do_init/do_close/SetBasciInfo 接口。
依赖：仅依赖 Common.CEnum（KL_TYPE/AUTYPE），不依赖任何缠论 K 线对象。
"""
import abc
from typing import Iterable

from Common.CEnum import AUTYPE, KL_TYPE

from .kbar import KBar


class CStockApi(abc.ABC):
    """行情数据源抽象基类。

    功能：定义所有数据源（BaoStock/akshare/ccxt/CSV/SQLite）的统一接口。
    设计：get_kl_data 产出纯 KBar，与缠论 CKLine_Unit 解耦。
    """

    def __init__(self, code, k_type: KL_TYPE, begin_date, end_date, autype: AUTYPE):
        """初始化数据源实例。
        输入：code 股票代码；k_type 级别；begin_date/end_date 起止日期；autype 复权方式
        输出：无（设置实例属性并调用 SetBasciInfo 填充 name/is_stock）
        """
        self.code = code
        self.name = None
        self.is_stock = None
        self.k_type = k_type
        self.begin_date = begin_date
        self.end_date = end_date
        self.autype = autype
        self.SetBasciInfo()

    @abc.abstractmethod
    def get_kl_data(self) -> Iterable[KBar]:
        """获取 K 线数据迭代器。
        输出：Iterable[KBar]，逐根产出纯 OHLCV 数据
        """
        pass

    @abc.abstractmethod
    def SetBasciInfo(self):
        """设置基本信息（股票名称、是否为个股等）。"""
        pass

    @classmethod
    @abc.abstractmethod
    def do_init(cls):
        """类级别初始化（如登录数据源）。"""
        pass

    @classmethod
    @abc.abstractmethod
    def do_close(cls):
        """类级别关闭（如登出数据源）。"""
        pass
