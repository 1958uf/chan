"""KBar：纯 OHLCV 数据载体。

功能：承载单根 K 线的原始行情数据，不依赖任何缠论模块。
设计：frozen dataclass，time 用标准库 datetime（精度到分钟），OHLCV/turnover/turnrate 缺失为 None。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class KBar:
    """单根 K 线的纯数据载体。

    功能：承载 OHLCV 原始数据，不依赖任何缠论模块。
    字段：
        time      - datetime，K 线时间（精度到分钟，秒/微秒在适配层截断）
        open/high/low/close - float，OHLC 价格
        volume    - Optional[float]，成交量，不可得时为 None
        turnover  - Optional[float]，成交额，不可得时为 None
        turnrate  - Optional[float]，换手率，不可得时为 None
    """
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    turnover: Optional[float] = None
    turnrate: Optional[float] = None
