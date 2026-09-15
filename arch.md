# Chan 项目架构说明

> 本文档记录 `Chan` 项目的目录结构与整体架构，便于快速了解项目组织与数据流。
> 版本：v2（2026-09-15，重构为「通用行情数据底座 + 多策略 + 统一回测框架」）

## 一、项目整体定位

本项目是一个 Python 量化分析框架，演进为 **「通用行情数据底座 + 公共基础设施 + 多策略（含缠论）+ 统一回测引擎」** 的分层架构：

- **DataBasis**：纯净行情数据底座（零缠论依赖），所有数据源返回纯 `KBar`（OHLCV）
- **Common/Math**：框架级公共基础设施（枚举/时间/异常/通用指标）
- **Strategies**：策略层，所有策略平级（缠论是其中一个策略，已去特权化）
- **Backtest**：统一回测引擎，与缠论完全解耦
- **DataAPI**：兼容层，委托 DataBasis，旧调用零改动

- 运行环境：Python 3.11，conda 环境名 `chan_py311`
- 主数据源：BaoStock（A 股日线），另支持 akshare、ccxt（数字货币）、CSV、本地 SQLite 缓存
- 入口：`main.py`（缠论扫描，向后兼容）、`cli.py`（多策略统一 CLI）、`App/ashare_bsp_scanner_gui.py`（PyQt6 GUI）、`monitor/run.py`（均线接近监控）

## 二、分层架构

```
┌─────────────────────────────────────────────────────┐
│ 入口层：main.py / cli.py / App / monitor            │
├─────────────────────────────────────────────────────┤
│ Backtest/   统一回测引擎（零缠论依赖）               │
│ Strategies/ 策略层（chan/example_ma/... 平级）       │
├─────────────────────────────────────────────────────┤
│ Common/  Math/   公共基础设施（通用指标/枚举/时间）   │
│ DataBasis/       纯净行情底座（零缠论依赖，返回KBar）│
│ DataAPI/         兼容层（委托 DataBasis，返回CKLine_Unit）│
└─────────────────────────────────────────────────────┘
```

### 分层依赖约束

- **DataBasis**：只依赖 `Common`，零缠论依赖，产出纯 `KBar`
- **Backtest**：只依赖 `DataBasis` + `Strategies.base`，零缠论依赖
- **Strategies.base/example_ma**：只依赖 `DataBasis` + `Common/Math`，不依赖缠论内部
- **Strategies.chan**：依赖 `DataBasis`（经 `chan_adapter` 转 `CKLine_Unit`）+ `Common/Math`
- **DataAPI（兼容层）**：委托 `DataBasis`，经适配器返回 `CKLine_Unit`，供旧代码使用

## 三、各目录职责

| 目录 | 职责 | 关键文件 |
|---|---|---|
| **DataBasis** | 【纯净行情底座】零缠论依赖，返回 KBar | `kbar.py`（KBar dataclass）、`stock_api.py`（CStockApi 抽象基类）、`data_factory.py`（工厂）、`baostock_api.py`/`akshare_api.py`/`ccxt_api.py`/`csv_api.py`/`sqlite_api.py`（各数据源，返回 KBar）、`sqlite_cache.py`（chan.db 缓存管理） |
| **Common** | 公共基础设施 | `CEnum.py`（数据源/级别/方向/买卖点类型等枚举）、`ChanException.py`、`CTime.py`、`func_util.py`（级别校验、区间重叠、str2float）、`cache.py`（memoize 装饰器） |
| **Math** | 通用技术指标（非缠论策略也可用） | `MACD.py`、`BOLL.py`、`RSI.py`、`KDJ.py`、`Demark.py`（TD 序列）、`TrendLine.py`、`TrendModel.py` |
| **Strategies** | 【策略层】所有策略平级 | `base.py`（CStrategy 抽象基类）、`registry.py`（策略注册表） |
| **Strategies/chan** | 缠论策略（从根目录迁入，去特权化） | `Chan.py`（CChan 核心引擎）、`ChanConfig.py`、`chan_adapter.py`（KBar→CKLine_Unit 适配）、`chan_strategy.py`（缠论回测适配器）、`KLine/`、`Bi/`、`Seg/`、`ZS/`、`BuySellPoint/`、`Combiner/`、`ChanModel/`、`Plot/`、`examples/` |
| **Strategies/example_ma** | 非缠论策略示例（均线策略，只依赖 DataBasis+Math） | `ma_strategy.py`（SMA 金叉/死叉） |
| **Backtest** | 【统一回测引擎】零缠论依赖 | `engine.py`（事件驱动逐 K 线）、`broker.py`（撮合/持仓/资金）、`portfolio.py`（资产组合/回测结果）、`metrics.py`（胜率/回撤/夏普） |
| **DataAPI** | 【兼容层】委托 DataBasis，旧调用零改动 | `CommonStockAPI.py`（CCommonStockApi + get_kl_data 返回 CKLine_Unit）、`BaoStockAPI.py`/`AkshareAPI.py`/`ccxt.py`/`csvAPI.py`/`SQLiteAPI.py`（委托 DataBasis）、`sqlite_cache.py`（转发 DataBasis.sqlite_cache） |
| **App** | 独立应用入口（GUI） | `ashare_bsp_scanner_gui.py`（PyQt6 A 股买点扫描器） |
| **monitor** | 独立的均线接近监控告警系统（与缠论主程序解耦） | `run.py`（CLI 入口，eod/live 两模式）、`data_source.py`、`indicators.py`、`alerts.py`、`config.yaml`、`watchlist.txt` |
| **pool** | 股票池文本 | `pool.txt`、`ai_pool.txt`、`优标.txt`、`check_code2name.txt` |
| **Script** | 运维脚本 | `migrate_csv_to_sqlite.py`（旧 CSV 缓存迁移到 chan.db）、`requirements.txt` |
| **doc** | 文档 | `0_系统迭代/`、`1_环境需求/`、`2_策略/`、`3_备份/`、`4_系统术语/` |
| **Image** | README 等文档用图片 | `frame.png`、`zs_algo.png`、`plot_cbsp.png` 等 |

## 四、核心入口与配置文件说明

### `main.py` —— 缠论扫描终端入口（向后兼容）
- 负责：BaoStock 登录（带重试）、最近交易日判定、`chan.db` 增量缓存更新、股票代码归一化、板块判定、批量扫描股票池汇总买点、单股终端表格输出。
- import：`from Strategies.chan.Chan import CChan`，`DataAPI` 兼容层不变。

### `cli.py` —— 多策略统一 CLI（新）
- 功能：按策略名称选择策略，指定数据源/级别/起止/复权，运行回测。
- 使用：`python cli.py --list`、`python cli.py --strategy example_ma --code sh.600008 --data-src sqlite --backtest`。
- 通过 `Strategies.registry` 查找策略，`DataBasis` 获取数据，`Backtest.engine` 回测。

### `Strategies/chan/Chan.py` —— 缠论核心引擎 `CChan`
- 接收：股票代码、起止时间、数据源（默认 BAO_STOCK）、级别列表、配置对象、复权类型。
- `GetStockAPI` 通过 `DataBasis.create_data_api` 获取数据源（返回 KBar），`load_stock_data` 经 `chan_adapter.kbar_to_klu` 转为 `CKLine_Unit`。
- 支持 `trigger_step` 逐步喂数据用于回测；否则一次性 `load()` 完成全量计算。

### `Strategies/chan/chan_adapter.py` —— KBar↔CKLine_Unit 适配收口
- `kbar_to_klu_dict`/`kbar_to_klu`：KBar → CKLine_Unit（time 转 CTime，auto=True）。
- `autofix_for`：保留各数据源 autofix 设定（仅 CCXT 为 True）。
- 这是 KBar 与 CKLine_Unit 之间唯一的转换处。

### `Strategies/chan/chan_strategy.py` —— 缠论回测适配器
- 把 `CChan.trigger_load` 步进模型包装成 `CStrategy.on_bar` 回调模型，使缠论可经统一回测引擎回测。

### `Backtest/engine.py` —— 统一回测引擎
- 事件驱动逐 K 线推进：`strategy.on_bar(bar, ctx)` → `broker` 撮合 → 记录 `portfolio` 快照。
- 输出 `BacktestResult`（交易记录、资金曲线、统计指标：胜率/回撤/夏普/年化）。

### `run.bat` / `setup_env.sh`
- `run.bat`：Windows 一键运行——`conda activate chan_py311` → `python main.py`。
- `setup_env.sh`：一键部署——创建 conda 环境 `chan_py311`，安装依赖并验证。

## 五、数据流

### 缠论分析链路（新架构）

```
行情数据源 (DataBasis: BaoStock/akshare/ccxt/SQLite/CSV)
        │  逐根 yield KBar（纯 OHLCV，零缠论依赖）
        ▼
chan_adapter.kbar_to_klu  (Strategies/chan/chan_adapter.py)
        │  KBar → CKLine_Unit（time 转 CTime，挂载指标）
        ▼
CChan (Strategies/chan/Chan.py)
        │  K线合并(Combiner) → 分型 → 笔(Bi) → 线段(Seg) → 中枢(ZS) → 买卖点(BSP)
        ▼
输出 (Plot 绘图 / main.py 终端表格 / App GUI / Backtest 回测)
```

### 统一回测链路

```
DataBasis.get_kl_data()  →  Iterable[KBar]
        │
        ▼
Backtest.engine  逐 K 线驱动 strategy.on_bar(bar, ctx)
        │  ctx.buy/sell → Broker 撮合 → Portfolio 记录
        ▼
BacktestResult  →  metrics（胜率/回撤/夏普/年化）
```

- 非缠论策略（example_ma）：直接实现 `on_bar`，只依赖 `KBar`。
- 缠论策略（chan）：经 `ChanStrategyAdapter` 把 `trigger_load` 包装成 `on_bar`。

### 关键设计要点

- **底座纯净**：`DataBasis/` 零缠论依赖，任何策略直接用 `KBar`。
- **缠论去特权化**：缠论成为 `Strategies/chan/` 下与其他策略平级的一个策略，根目录只剩框架级文件。
- **CTime 语义**：`KBar.time`（datetime）转 `CTime` 时统一 `auto=True`，日线（时分=0）自动对齐 23:59，分钟级别用真实时分。
- **兼容平滑**：旧代码继续用 `DataAPI`/`main.py`，新代码用 `DataBasis`/`cli.py`，无需一次性迁移。
- **监控旁路**：`monitor/` 是独立的均线接近告警系统，不依赖缠论核心和 chan.db。
