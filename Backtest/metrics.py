"""收益统计指标。

功能：计算胜率、盈亏比、最大回撤、年化收益、夏普比率。
设计：基于 BacktestResult 的交易记录与资金曲线计算。
"""
from typing import List, Tuple
import math


def compute_metrics(trades: List, equity_curve: List[Tuple],
                    initial_cash: float) -> dict:
    """计算回测统计指标。
    功能：从交易记录与资金曲线计算胜率/回撤/夏普等
    输入：trades - 交易列表；equity_curve - [(time, value)]；initial_cash - 初始资金
    输出：指标字典
    """
    metrics = {}

    # 最终资产与总收益率
    final_value = equity_curve[-1][1] if equity_curve else initial_cash
    metrics["final_value"] = final_value
    metrics["total_return"] = (final_value - initial_cash) / initial_cash if initial_cash > 0 else 0

    # 年化收益（按交易日估算）
    n_days = len(equity_curve)
    if n_days > 1 and initial_cash > 0:
        metrics["annual_return"] = (final_value / initial_cash) ** (252 / n_days) - 1
    else:
        metrics["annual_return"] = 0

    # 最大回撤
    peak = initial_cash
    max_dd = 0.0
    for _, v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    metrics["max_drawdown"] = max_dd

    # 夏普比率（日收益率的均值/标准差 * sqrt(252)，简化）
    if len(equity_curve) > 2:
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1][1]
            cur = equity_curve[i][1]
            if prev > 0:
                returns.append((cur - prev) / prev)
        if returns:
            mean_r = sum(returns) / len(returns)
            var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = math.sqrt(var_r) if var_r > 0 else 0
            metrics["sharpe"] = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0
        else:
            metrics["sharpe"] = 0
    else:
        metrics["sharpe"] = 0

    # 胜率与盈亏比（按配对的 buy/sell 统计）
    wins, losses = [], []
    i = 0
    buy_price = None
    for t in trades:
        if t.direction == "buy":
            buy_price = t.price
        elif t.direction == "sell" and buy_price is not None:
            pnl = t.price - buy_price
            (wins if pnl > 0 else losses).append(abs(pnl))
            buy_price = None
    total_closed = len(wins) + len(losses)
    metrics["win_rate"] = len(wins) / total_closed if total_closed > 0 else 0
    metrics["profit_loss_ratio"] = (
        (sum(wins) / len(wins)) / (sum(losses) / len(losses))
        if wins and losses else 0
    )

    return metrics
