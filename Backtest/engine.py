"""事件驱动回测引擎。

功能：逐 K 线驱动策略 on_bar 回调，经 broker 撮合，记录 portfolio 变化，输出统计。
设计：只依赖 DataBasis.KBar + Strategies.base.CStrategy，与缠论完全解耦。
依赖：Backtest.broker/portfolio/metrics，DataBasis，Strategies.base。
"""
from typing import Iterable, Optional

from DataBasis.kbar import KBar
from Strategies.base import BacktestContext, CStrategy

from .broker import Broker
from .metrics import compute_metrics
from .portfolio import BacktestResult


class _ContextImpl(BacktestContext):
    """回测上下文实现：委托 Broker 提供下单/持仓/资金查询。"""

    def __init__(self, broker: Broker, code: str):
        self._broker = broker
        self._code = code

    def buy(self, code: str, price: float, volume: float = 0) -> None:
        self._broker.buy(code, price, _ContextImpl._current_time, volume)

    def sell(self, code: str, price: float, volume: float = 0) -> None:
        self._broker.sell(code, price, _ContextImpl._current_time, volume)

    @property
    def position(self) -> float:
        return self._broker.position_volume(self._code)

    @property
    def cash(self) -> float:
        return self._broker.cash

    _current_time = None


class CBacktestEngine:
    """统一回测引擎。
    功能：逐 K 线驱动策略 on_bar 回调，经 broker 撮合，记录 portfolio 变化。
    输入：strategy(CStrategy)、data_iter(Iterable[KBar])、初始资金、手续费率
    输出：BacktestResult（含交易记录、资金曲线、统计指标）
    """

    def __init__(self, initial_cash: float = 100000.0, commission_rate: float = 0.0003):
        """初始化回测引擎。
        输入：initial_cash 初始资金；commission_rate 手续费率
        输出：无
        """
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate

    def run(self, strategy: CStrategy, data_iter: Iterable[KBar]) -> BacktestResult:
        """运行回测。
        功能：逐 K 线调用 strategy.on_bar，撮合下单，记录资金曲线
        输入：strategy - 策略实例；data_iter - KBar 迭代器
        输出：BacktestResult
        """
        broker = Broker(initial_cash=self.initial_cash, commission_rate=self.commission_rate)
        ctx = _ContextImpl(broker, strategy.code)
        result = BacktestResult(initial_cash=self.initial_cash)

        for bar in data_iter:
            _ContextImpl._current_time = bar.time
            strategy.on_bar(bar, ctx)
            # 记录资金快照
            total_value = broker.total_value({strategy.code: bar.close})
            result.add_snapshot(bar.time, total_value)

        # 收尾：用最后一根收盘价计算最终资产
        result.trades = broker.trades
        result.final_value = result.equity_curve[-1][1] if result.equity_curve else self.initial_cash
        result.metrics = compute_metrics(result.trades, result.equity_curve, self.initial_cash)
        return result


def run_backtest(strategy: CStrategy, data_iter: Iterable[KBar],
                 initial_cash: float = 100000.0,
                 commission_rate: float = 0.0003) -> BacktestResult:
    """便捷函数：运行回测并返回结果。
    功能：封装 CBacktestEngine.run
    输入：strategy 策略实例；data_iter KBar 迭代器；initial_cash 初始资金；commission_rate 手续费率
    输出：BacktestResult
    """
    engine = CBacktestEngine(initial_cash=initial_cash, commission_rate=commission_rate)
    return engine.run(strategy, data_iter)
