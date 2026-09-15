"""策略抽象基类。

功能：定义所有策略（缠论/非缠论）的统一接口契约。
设计：策略只依赖 DataBasis.KBar，不依赖其他策略内部对象。回测引擎只依赖本接口。
依赖：DataBasis.KBar、Common.CEnum，不依赖任何缠论内部模块。
"""
import abc
from typing import List, Optional

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.kbar import KBar


class BacktestContext:
    """回测上下文（由 Backtest 引擎注入）。
    功能：在 on_bar 回调中向策略暴露下单 API 与当前账户状态。
    设计：轻量接口，具体实现由 Backtest/broker.py + portfolio.py 提供。
    """

    def buy(self, code: str, price: float, volume: float = 0) -> None:
        """市价买入。"""
        raise NotImplementedError

    def sell(self, code: str, price: float, volume: float = 0) -> None:
        """市价卖出。"""
        raise NotImplementedError

    @property
    def position(self) -> float:
        """当前持仓数量。"""
        raise NotImplementedError

    @property
    def cash(self) -> float:
        """当前可用资金。"""
        raise NotImplementedError


class CStrategy(abc.ABC):
    """策略抽象基类。
    功能：定义所有策略（缠论/非缠论）的统一接口契约。
    设计：策略只依赖 DataBasis.KBar，不依赖其他策略内部对象。
    """

    def __init__(self, code: str, k_type: KL_TYPE = KL_TYPE.K_DAY,
                 begin_date: Optional[str] = None, end_date: Optional[str] = None,
                 data_src=DATA_SRC.BAO_STOCK, autype: AUTYPE = AUTYPE.QFQ):
        """初始化策略。
        输入：code 代码；k_type 级别；begin_date/end_date 起止；data_src 数据源；autype 复权
        输出：无
        """
        self.code = code
        self.k_type = k_type
        self.begin_date = begin_date
        self.end_date = end_date
        self.data_src = data_src
        self.autype = autype

    @abc.abstractmethod
    def on_bar(self, bar: KBar, ctx: BacktestContext) -> None:
        """逐 K 线回调，产生交易信号。
        输入：bar - 当前 KBar；ctx - 回测上下文（下单/查持仓）
        输出：无（通过 ctx 下单）
        """
        pass

    def generate_signals(self) -> List:
        """一次性计算全部信号，供非回测场景。
        功能：默认空实现，策略按需覆盖
        输出：信号列表
        """
        return []
