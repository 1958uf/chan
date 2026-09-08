"""
监控指标计算与"接近均线"判定

功能说明：
    - 简单移动平均 SMA 计算
    - 给定均线周期与阈值，判定当前价是否"接近"均线
    - 输出结构化的判定结果，供 alerts 层渲染

设计要点：
    - 纯函数，无副作用，便于测试
    - 偏离度 = (当前价 - 均线) / 均线，带方向与百分比
    - 接近判定：|偏离度| <= threshold 视为触发
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MaCheckResult:
    """单只标的的均线接近判定结果。
    属性：
        code      - 标的代码
        name      - 标的名称
        ma_value  - 均线值（计算不出时为 None）
        price     - 当前价
        deviation - 偏离度（小数，如 0.012 表示 +1.2%）
        near      - 是否触发接近（|deviation| <= threshold）
        above     - 当前价是否在均线上方
        reason    - 未触发或失败的原因说明（数据不足等）
    """
    code: str
    name: str
    ma_value: Optional[float]
    price: Optional[float]
    deviation: Optional[float]
    near: bool
    above: Optional[bool]
    reason: str = ""


def sma(closes: List[float], period: int) -> Optional[float]:
    """计算简单移动平均。
    功能：取 closes 末尾 period 个值的算术平均
    输入：closes - 收盘价序列（旧->新）；period - 均线周期
    输出：均线值；数据不足 period 个则返回 None
    """
    if closes is None or len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def check_near_ma(code: str, name: str, closes: List[float],
                  price: Optional[float], period: int,
                  threshold: float) -> MaCheckResult:
    """判定当前价是否接近指定周期的均线。
    功能：算均线 -> 算偏离度 -> 判定是否在阈值内
    输入：
        code      - 标的代码
        name      - 标的名称
        closes    - 周线收盘价序列（旧->新）
        price     - 当前价（盘后用最新周收，盘军用实时价）
        period    - 均线周期（周）
        threshold - 接近阈值（小数，0.02 = ±2%）
    输出：MaCheckResult 判定结果
    """
    ma_value = sma(closes, period)
    if ma_value is None:
        return MaCheckResult(code, name, None, price, None, False, None,
                             reason=f"周线数据不足{period}周，无法计算均线")
    if price is None or price <= 0:
        return MaCheckResult(code, name, ma_value, None, None, False, None,
                             reason="当前价缺失")
    deviation = (price - ma_value) / ma_value
    near = abs(deviation) <= threshold
    return MaCheckResult(
        code=code, name=name, ma_value=ma_value, price=price,
        deviation=deviation, near=near, above=(deviation > 0),
        reason="" if near else "偏离超出阈值",
    )
