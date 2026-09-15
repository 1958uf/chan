"""资产组合与交易记录。

功能：记录资金曲线、持仓快照、交易明细，供回测结果统计。
设计：由回测引擎驱动，每根 K 线记录一次快照。
"""
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class BacktestResult:
    """回测结果容器。
    功能：承载交易记录、资金曲线、统计指标，供 metrics 计算。
    """
    trades: List = field(default_factory=list)
    equity_curve: List[Tuple] = field(default_factory=list)  # [(time, total_value), ...]
    initial_cash: float = 100000.0
    final_value: float = 0.0
    metrics: dict = field(default_factory=dict)

    def add_snapshot(self, time, total_value: float) -> None:
        """记录单根 K 线的资金快照。
        输入：time - 时间；total_value - 总资产
        输出：无
        """
        self.equity_curve.append((time, total_value))

    def summary(self) -> str:
        """生成回测摘要文本。"""
        m = self.metrics
        lines = [
            "=== 回测结果 ===",
            f"初始资金: {self.initial_cash:.2f}",
            f"最终资产: {self.final_value:.2f}",
            f"总收益率: {m.get('total_return', 0):.2%}",
            f"年化收益: {m.get('annual_return', 0):.2%}",
            f"最大回撤: {m.get('max_drawdown', 0):.2%}",
            f"夏普比率: {m.get('sharpe', 0):.4f}",
            f"交易次数: {len(self.trades)}",
            f"胜率: {m.get('win_rate', 0):.2%}",
            f"盈亏比: {m.get('profit_loss_ratio', 0):.2f}",
        ]
        return "\n".join(lines)
