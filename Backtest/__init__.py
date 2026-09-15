"""统一回测引擎。

功能：事件驱动逐 K 线推进策略 on_bar 回调，经 broker 撮合，记录 portfolio 变化。
设计：只依赖 DataBasis.KBar + Strategies.base.CStrategy，与缠论完全解耦。
"""
