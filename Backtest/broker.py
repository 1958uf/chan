"""撮合/持仓/资金管理。

功能：模拟券商撮合，管理持仓与资金，处理手续费/滑点。
设计：简化版市价撮合，按 on_bar 当根收盘价成交。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from DataBasis.kbar import KBar


@dataclass
class Position:
    """持仓快照。
    功能：记录某标的的持仓数量与成本。
    """
    code: str
    volume: float = 0.0
    avg_price: float = 0.0


@dataclass
class Trade:
    """单笔交易记录。"""
    time: object
    code: str
    direction: str  # 'buy' / 'sell'
    price: float
    volume: float
    amount: float
    commission: float


class Broker:
    """券商撮合器。
    功能：市价撮合买卖，管理现金与持仓，计算手续费。
    设计：按当根 K 线收盘价成交，买入全仓/卖出清仓（简化）。
    """

    def __init__(self, initial_cash: float = 100000.0, commission_rate: float = 0.0003,
                 min_commission: float = 5.0):
        """初始化券商。
        输入：initial_cash 初始资金；commission_rate 手续费率；min_commission 最小手续费
        输出：无
        """
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []

    def buy(self, code: str, price: float, time: object, volume: float = 0) -> None:
        """市价买入。
        功能：用全部可用资金买入（volume=0 时全仓），扣除手续费
        输入：code 标的；price 成交价；time 时间；volume 指定数量（0=全仓）
        输出：无
        """
        if price <= 0:
            return
        if volume <= 0:
            # 全仓买入
            volume = self.cash / price
        amount = volume * price
        commission = max(amount * self.commission_rate, self.min_commission)
        if amount + commission > self.cash:
            volume = (self.cash - commission) / price
            amount = volume * price
            commission = max(amount * self.commission_rate, self.min_commission)
        self.cash -= (amount + commission)

        pos = self.positions.get(code, Position(code=code))
        if pos.volume > 0:
            total_cost = pos.avg_price * pos.volume + amount
            pos.volume += volume
            pos.avg_price = total_cost / pos.volume if pos.volume > 0 else 0
        else:
            pos.volume = volume
            pos.avg_price = price
        self.positions[code] = pos
        self.trades.append(Trade(time, code, "buy", price, volume, amount, commission))

    def sell(self, code: str, price: float, time: object, volume: float = 0) -> None:
        """市价卖出。
        功能：卖出持仓（volume=0 时清仓），扣除手续费
        输入：code 标的；price 成交价；time 时间；volume 指定数量（0=清仓）
        输出：无
        """
        pos = self.positions.get(code)
        if pos is None or pos.volume <= 0:
            return
        if volume <= 0 or volume >= pos.volume:
            volume = pos.volume
        amount = volume * price
        commission = max(amount * self.commission_rate, self.min_commission)
        self.cash += (amount - commission)
        pos.volume -= volume
        if pos.volume <= 0:
            pos.volume = 0
            pos.avg_price = 0
        self.trades.append(Trade(time, code, "sell", price, volume, amount, commission))

    def position_volume(self, code: str) -> float:
        """返回某标的持仓数量。"""
        pos = self.positions.get(code)
        return pos.volume if pos else 0.0

    def total_value(self, prices: Dict[str, float]) -> float:
        """计算总资产（现金 + 持仓市值）。
        输入：prices - {code: 当前价}
        输出：总资产
        """
        value = self.cash
        for code, pos in self.positions.items():
            if pos.volume > 0:
                value += pos.volume * prices.get(code, pos.avg_price)
        return value
