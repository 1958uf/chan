"""缠论策略适配器：把 CChan 步进模型包装成 CStrategy.on_bar 回调模型。

功能：使缠论策略可通过统一回测引擎（Backtest.engine）回测。
设计：
    - 内部持有 CChan 实例（trigger_step=True 模式，不自动 load）
    - on_bar 时把 KBar 转 CKLine_Unit，经 trigger_load 喂入 CChan
    - 喂入后查询最新买卖点，转化为下单信号
    - 回测引擎无需感知缠论内部，缠论也无需改造 trigger_load
依赖：Strategies.base.CStrategy、Strategies.chan.Chan.CChan、DataBasis.KBar。
注意：本模块在 Strategies/chan/ 内，可自由 import 缠论内部模块；Backtest/ 不可 import 本模块。
"""
from typing import Optional

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.kbar import KBar
from Strategies.base import BacktestContext, CStrategy
from Strategies.registry import register

from .Chan import CChan
from .ChanConfig import CChanConfig
from .chan_adapter import autofix_for, kbar_to_klu


@register("chan")
class ChanStrategyAdapter(CStrategy):
    """缠论策略的回测适配器。
    功能：把 CChan 的 trigger_load 步进模型包装成 CStrategy.on_bar 回调模型。
    实现：on_bar 时调用 chan.trigger_load 喂入该 K 线，然后查询最新买卖点转化为下单信号。
    """

    def __init__(self, code: str, k_type: KL_TYPE = KL_TYPE.K_DAY,
                 begin_date: Optional[str] = None, end_date: Optional[str] = None,
                 data_src=DATA_SRC.BAO_STOCK, autype: AUTYPE = AUTYPE.QFQ,
                 chan_config: Optional[dict] = None):
        super().__init__(code, k_type, begin_date, end_date, data_src, autype)

        # 构造缠论配置：trigger_step=True，不自动 load
        cfg = {"trigger_step": True}
        if chan_config:
            cfg.update(chan_config)
        self._config = CChanConfig(cfg)

        # 创建 CChan 实例（trigger_step 模式下 __init__ 不会自动 load）
        self._chan = CChan(
            code=code,
            begin_time=begin_date,
            end_time=end_date,
            data_src=data_src,
            lv_list=[k_type],
            config=self._config,
            autype=autype,
        )
        self._autofix = autofix_for(data_src)
        self._last_bsp_count = 0

    def on_bar(self, bar: KBar, ctx: BacktestContext) -> None:
        """逐 K 线回调：喂入 CChan，查询买卖点，下单。
        输入：bar - 当前 KBar；ctx - 回测上下文
        输出：无（通过 ctx 下单）
        """
        klu = kbar_to_klu(bar, autofix=self._autofix)
        klu.kl_type = self.k_type

        # 喂入 CChan（trigger_step 模式）
        self._chan.trigger_load({self.k_type: [klu]})

        # 查询最新买卖点
        kl_data = self._chan.kl_datas.get(self.k_type)
        if kl_data is None:
            return
        bsp_lst = kl_data.bs_point_lst
        cur_count = len(bsp_lst)

        # 有新增买卖点时产生交易信号
        if cur_count > self._last_bsp_count:
            for i in range(self._last_bsp_count, cur_count):
                bsp = bsp_lst.getSortedBspList()[i] if hasattr(bsp_lst, "getSortedBspList") else None
                if bsp is None:
                    continue
                bsp_type = bsp.type
                # 一类、二类买点买入；卖点卖出
                is_buy = any(t in [bsp_type] for t in [])  # bsp.type 是列表
                # bsp.type 可能是 BSP_TYPE 或列表，统一处理
                types = bsp.type if isinstance(bsp.type, list) else [bsp.type]
                from Common.CEnum import BSP_TYPE
                buy_types = [BSP_TYPE.T1, BSP_TYPE.T1P, BSP_TYPE.T2, BSP_TYPE.T2S, BSP_TYPE.T3A, BSP_TYPE.T3B]
                is_buy = any(t in buy_types for t in types)
                if is_buy:
                    if ctx.position == 0:
                        ctx.buy(self.code, bar.close)
                else:
                    if ctx.position > 0:
                        ctx.sell(self.code, bar.close)
            self._last_bsp_count = cur_count

    def generate_signals(self):
        """返回 CChan 实例供非回测场景直接使用。"""
        return self._chan
