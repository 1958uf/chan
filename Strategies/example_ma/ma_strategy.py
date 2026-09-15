"""均线策略示例（非缠论策略）。

功能：基于 SMA 金叉/死叉的简单策略，演示只依赖 DataBasis+Strategies.base 的策略实现。
设计：
    - 不依赖任何缠论模块（无 CKLine_Unit/Bi/Seg/ZS 等）
    - 只依赖 DataBasis.KBar + Strategies.base.CStrategy
    - 内部维护短期/长期 SMA 状态，金叉买入、死叉卖出
使用：通过 cli.py --strategy example_ma 调用，或直接实例化。
"""
from collections import deque
from typing import List, Optional

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.kbar import KBar
from Strategies.base import BacktestContext, CStrategy
from Strategies.registry import register


def sma(values: deque, period: int) -> Optional[float]:
    """计算简单移动平均。
    功能：对 values 的最近 period 个值求平均
    输入：values - 价格序列；period - 均线周期
    输出：SMA 值（数据不足返回 None）
    """
    if len(values) < period:
        return None
    recent = list(values)[-period:]
    return sum(recent) / period


@register("example_ma")
class MaStrategy(CStrategy):
    """均线策略。
    功能：短期均线上穿长期均线（金叉）买入，下穿（死叉）卖出。
    设计：只依赖 DataBasis.KBar，不依赖缠论。
    参数：short_period=5, long_period=20
    """

    def __init__(self, code: str, k_type: KL_TYPE = KL_TYPE.K_DAY,
                 begin_date: Optional[str] = None, end_date: Optional[str] = None,
                 data_src=DATA_SRC.BAO_STOCK, autype: AUTYPE = AUTYPE.QFQ,
                 short_period: int = 5, long_period: int = 20):
        super().__init__(code, k_type, begin_date, end_date, data_src, autype)
        self.short_period = short_period
        self.long_period = long_period
        self._closes: deque = deque()
        self._prev_short: Optional[float] = None
        self._prev_long: Optional[float] = None
        self.signals: List[dict] = []

    def on_bar(self, bar: KBar, ctx: BacktestContext) -> None:
        """逐 K 线回调：更新均线状态，检测金叉/死叉。
        输入：bar - 当前 KBar；ctx - 回测上下文
        输出：无（通过 ctx 下单，信号记录到 self.signals）
        """
        self._closes.append(bar.close)

        cur_short = sma(self._closes, self.short_period)
        cur_long = sma(self._closes, self.long_period)

        if cur_short is not None and cur_long is not None and self._prev_short is not None and self._prev_long is not None:
            # 金叉：短期从下方穿过长期
            if self._prev_short <= self._prev_long and cur_short > cur_long:
                if ctx.position == 0:
                    ctx.buy(self.code, bar.close)
                    self.signals.append({"time": bar.time, "action": "buy", "price": bar.close})
            # 死叉：短期从上方穿过长期
            elif self._prev_short >= self._prev_long and cur_short < cur_long:
                if ctx.position > 0:
                    ctx.sell(self.code, bar.close)
                    self.signals.append({"time": bar.time, "action": "sell", "price": bar.close})

        self._prev_short = cur_short
        self._prev_long = cur_long

    def generate_signals(self) -> List[dict]:
        """返回已记录的交易信号列表。
        输出：[{time, action, price}, ...]
        """
        return self.signals
