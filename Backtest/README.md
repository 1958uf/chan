# Backtest — 统一回测引擎

事件驱动的逐 K 线回测框架，与缠论完全解耦（只依赖 `DataBasis.KBar` + `Strategies.base.CStrategy`）。
任何实现 `CStrategy` 接口的策略（均线、动量、缠论经适配器等）都用同一引擎回测。

## 模块说明

| 文件 | 职责 |
| --- | --- |
| `engine.py` | 回测引擎 `CBacktestEngine`：逐 K 线驱动 `strategy.on_bar(bar, ctx)`，撮合下单，记录资金曲线；便捷入口 `run_backtest()` |
| `broker.py` | 券商撮合器 `Broker`：市价成交（按当根收盘价）、持仓/现金管理、手续费（费率 + 最小手续费） |
| `portfolio.py` | 结果容器 `BacktestResult`：交易记录、资金曲线、统计指标，`summary()` 输出摘要文本 |
| `metrics.py` | 统计指标 `compute_metrics()`：总收益率、年化收益、最大回撤、夏普比率、胜率、盈亏比 |

## 快速使用

### 方式一：命令行（推荐）

```bash
# 均线策略回测（chan.db 已有 sh.600008 数据）
python cli.py --strategy example_ma --code sh.600008 --data-src sqlite --backtest

# 缠论策略回测（经 ChanStrategyAdapter 桥接）
python cli.py --strategy chan --code sh.600008 --data-src sqlite --backtest
```

### 方式二：代码调用

```python
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.data_factory import create_data_api
from Backtest.engine import run_backtest
from Strategies.example_ma.ma_strategy import MaStrategy

api_cls = create_data_api(DATA_SRC.SQLITE)
api_cls.do_init()
try:
    api = api_cls(code="sh.600008", k_type=KL_TYPE.K_DAY,
                  begin_date="2024-01-01", end_date="2025-12-31",
                  autype=AUTYPE.QFQ)
    strategy = MaStrategy(code="sh.600008", k_type=KL_TYPE.K_DAY,
                          begin_date="2024-01-01", end_date="2025-12-31",
                          data_src=DATA_SRC.SQLITE, autype=AUTYPE.QFQ)
    result = run_backtest(strategy, api.get_kl_data(), initial_cash=100000.0)
finally:
    api_cls.do_close()

print(result.summary())          # 文本摘要
print(result.trades)             # 交易明细列表
print(result.equity_curve)       # 资金曲线 [(time, total_value), ...]
print(result.metrics)            # 指标字典
```

## 参数说明

### run_backtest / CBacktestEngine

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `strategy` | `CStrategy` | 必填 | 策略实例（须实现 `on_bar`） |
| `data_iter` | `Iterable[KBar]` | 必填 | K 线数据迭代器（通常来自 `DataBasis`） |
| `initial_cash` | `float` | `100000.0` | 初始资金 |
| `commission_rate` | `float` | `0.0003` | 手续费率（万分之三） |

### Broker

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `initial_cash` | `float` | `100000.0` | 初始现金 |
| `commission_rate` | `float` | `0.0003` | 按成交额计的手续费率 |
| `min_commission` | `float` | `5.0` | 单笔最小手续费（元） |

## 撮合规则（当前简化实现）

- **成交价**：策略在 `on_bar` 中下单，按当根 K 线收盘价立即成交（无排队/滑点）
- **买入**：`volume=0` 表示全仓买入（预留手续费后能买多少买多少）
- **卖出**：`volume=0` 表示清仓
- **手续费**：`max(成交额 × 费率, 最小手续费)`

## 指标口径

| 指标 | 口径 |
| --- | --- |
| `total_return` | (最终资产 − 初始资金) / 初始资金 |
| `annual_return` | `(最终/初始)^(252/K线数) − 1`（按 252 个交易日估算） |
| `max_drawdown` | 资金曲线峰谷最大回撤比例 |
| `sharpe` | 逐 K 收益率均值/标准差 × √252（无风险利率取 0） |
| `win_rate` | 按顺序配对 buy/sell，盈利平仓笔数占比 |
| `profit_loss_ratio` | 平均盈利额 / 平均亏损额 |

> 注意：`annual_return`/`sharpe` 按 K 线根数折算年化，分钟级别回测时口径会偏保守，结果仅供参考。

## 扩展策略接入回测

1. 在 `Strategies/` 下实现 `CStrategy` 子类，核心是实现 `on_bar(bar, ctx)`
2. 通过 `ctx.buy(code, price)` / `ctx.sell(code, price)` 下单，`ctx.position` / `ctx.cash` 查询状态
3. （可选）用 `@register("策略名")` 注册，即可 `python cli.py --strategy 策略名 --backtest` 直接回测
4. 缠论这类内部有复杂状态机的策略，参照 `Strategies/chan/chan_strategy.py` 写一个适配器包装成 `on_bar` 回调

## 设计约束

- `Backtest/` 内**禁止** import 任何 `Strategies.chan.*` 内部模块（保持引擎与缠论解耦）
- 缠论接入回测的唯一入口是 `Strategies/chan/chan_strategy.py` 的 `ChanStrategyAdapter`
- 引擎只认 `DataBasis.KBar`，不认 `CKLine_Unit`（KBar → CKLine_Unit 的转换收口在 `Strategies/chan/chan_adapter.py`）
