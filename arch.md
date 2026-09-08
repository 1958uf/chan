# Chan 项目架构说明

> 本文档记录 `Chan`（缠论量化分析框架）项目的目录结构与整体架构，便于快速了解项目组织与数据流。

## 一、项目整体定位

这是一个基于"缠论"（缠中说禅技术分析理论）的 Python 量化分析框架，项目名 `chan.py`。它实现了完整的缠论分析链路：从行情数据获取，到 K 线合并、分型识别、笔/线段/中枢/买卖点的自动计算，再到可视化绘图和回测策略演示。当前项目在此基础上还做了一层"实盘辅助"封装——SQLite 缓存、批量扫描股票池、均线接近监控告警。

- 核心模型语言：Python 3.11，conda 环境名 `chan_py311`
- 主数据源：BaoStock（A 股日线），另支持 akshare、ccxt（数字货币）、CSV、本地 SQLite 缓存
- 入口：`main.py`（终端批量扫描/单股查询）、`App/ashare_bsp_scanner_gui.py`（PyQt6 GUI）、`monitor/run.py`（均线接近监控）

## 二、各目录职责

| 目录 | 职责 | 关键文件 |
|---|---|---|
| **根目录** | 核心引擎类与全局入口/配置 | `Chan.py`、`ChanConfig.py`、`main.py`、`run.bat`、`setup_env.sh`、`chan.db`（SQLite 缓存库，约 78MB） |
| **App** | 独立应用入口（GUI） | `ashare_bsp_scanner_gui.py`（PyQt6 A 股买点扫描器，批量扫描并可视化 K 线/笔/线段/中枢/买卖点/MACD） |
| **Bi** | "笔"的模型与算法 | `Bi.py`（`CBi` 笔类）、`BiList.py`（笔列表管理）、`BiConfig.py`（笔算法/严格度/分型校验配置） |
| **BuySellPoint** | 买卖点识别 | `BS_Point.py`（买卖点类）、`BSPointList.py`（含一/二/三类买卖点）、`BSPointConfig.py`（背驰率、最小中枢数等配置） |
| **ChanModel** | 机器学习/特征工程层 | `Features.py`（特征字典容器，供买卖点附带特征） |
| **Combiner** | K 线合并（含处理）引擎 | `KLine_Combiner.py`（泛型合并器，含分型判定）、`Combine_Item.py`（统一提取笔/K线单元/线段的高低价与时间） |
| **Common** | 公共基础设施 | `CEnum.py`（数据源/级别/方向/买卖点类型等枚举）、`ChanException.py`、`CTime.py`、`func_util.py`（级别校验、区间重叠）、`cache.py`（memoize 装饰器） |
| **DataAPI** | 行情数据源抽象与各实现 | `CommonStockAPI.py`（抽象基类）、`BaoStockAPI.py`、`AkshareAPI.py`、`ccxt.py`（数字货币）、`csvAPI.py`、`SQLiteAPI.py`、`sqlite_cache.py`（chan.db 增量缓存管理，替代旧 CSV 缓存层） |
| **Debug** | 策略/回测示例 | `strategy_demo.py` ~ `strategy_demo6.py`（演示用 `CChan` + `trigger_step` 做逐步回测） |
| **KLine** | K 线对象与多级别管理 | `KLine_Unit.py`（单根 K 线，挂载 MACD/BOLL/RSI/KDJ/Demark）、`KLine.py`（合并后 K 线）、`KLine_List.py`（单级别 K 线容器，串联 笔/线段/中枢/买卖点）、`TradeInfo.py` |
| **Math** | 技术指标计算 | `MACD.py`、`BOLL.py`、`RSI.py`、`KDJ.py`、`Demark.py`（TD 序列）、`TrendLine.py`、`TrendModel.py` |
| **monitor** | 独立的均线接近监控告警系统（与缠论主程序解耦） | `run.py`（CLI 入口，eod/live 两模式）、`data_source.py`、`indicators.py`、`alerts.py`、`config.yaml`、`watchlist.txt` |
| **Plot** | 可视化绘图 | `PlotDriver.py`（matplotlib 静态图）、`AnimatePlotDriver.py`（逐 K 线动画）、`PlotMeta.py`（绘图元数据适配） |
| **pool** | 股票池文本 | `pool.txt`、`ai_pool.txt`、`优标.txt`、`check_code2name.txt` |
| **Script** | 运维脚本 | `migrate_csv_to_sqlite.py`（旧 CSV 缓存迁移到 chan.db）、`requirements.txt` |
| **Seg** | "线段"模型与多种线段算法 | `Seg.py`、`SegConfig.py`、`SegListChan.py`（缠论正宗分型特征算法）、`SegListDYH.py`（1+1，弃用）、`SegListDef.py`（break，弃用）、`Eigen.py`（特征序列分型）、`EigenFX.py`（特征分型状态机） |
| **ZS** | "中枢"模型与识别 | `ZS.py`（中枢类，含范围/子中枢）、`ZSList.py`（中枢列表更新）、`ZSConfig.py`（是否合并/单笔中枢/算法配置） |
| **doc** | 文档 | `0_系统迭代/`、`1_环境需求/`、`2_策略/`（缠论策略专业/白话版）、`3_备份/`、`4_系统术语/` |
| **Image** | README 等文档用图片 | `frame.png`、`zs_algo.png`、`plot_cbsp.png` 等 |

## 三、核心入口与配置文件说明

### `Chan.py` —— 核心引擎类 `CChan`
- 接收：股票代码、起止时间、数据源（默认 BAO_STOCK）、级别列表（默认 `[K_DAY, K_60M]`，从高到低）、配置对象、复权类型。
- 内部聚合每级别一份 `CKLine_List`，并持有 `g_kl_iter` 用于多级别对齐迭代。
- 支持 `trigger_step` 逐步喂数据用于回测；否则一次性 `load()` 完成全量计算。

### `ChanConfig.py` —— 全局配置 `CChanConfig`
- 聚合各子模块配置：`CBiConfig`（笔）、`CSegConfig`（线段）、`CZSConfig`（中枢）、`CBSPointConfig`（买卖点）。
- 指标开关：MACD/BOLL/RSI/KDJ/Demark、均线周期列表、趋势周期。
- 数据质量校验参数。

### `main.py` —— 终端入口
- 负责：BaoStock 登录（带重试）、最近交易日判定、`chan.db` 增量缓存更新、股票代码归一化、板块判定、批量扫描股票池汇总买点、单股终端表格输出。

### `run.bat` / `setup_env.sh`
- `run.bat`：Windows 一键运行——`conda activate chan_py311` → `python main.py`。
- `setup_env.sh`：一键部署——创建 conda 环境 `chan_py311`，安装依赖并验证。

## 四、数据流（缠论分析链路）

整体遵循缠论标准层级，逐级递进：

```
行情数据源 (DataAPI: BaoStock/akshare/ccxt/SQLite/CSV)
        │  逐根 yield CKLine_Unit（含 OHLC + 成交流 + 指标）
        ▼
K线合并层 (Combiner/KLine_Combiner + KLine/KLine.py)
        │  按方向做 K 线包含处理 → 合并后 K 线 CKLine
        │  识别顶/底分型
        ▼
笔 Bi (Bi/BiList.py)
        │  相邻分型连线构成一笔（含方向、是否确定）
        ▼
线段 Seg (Seg/SegListChan.py + Eigen/EigenFX)
        │  基于笔的特征序列分型识别线段
        ▼
中枢 ZS (ZS/ZSList.py)
        │  连续三笔重叠区间构成中枢
        ▼
买卖点 BuySellPoint (BSPointList.py)
        │  结合中枢数量、背驰率、MACD 背驰判定一/二/三类买卖点
        ▼
输出 (Plot 绘图 / main.py 终端表格 / App GUI)
```

### 关键设计要点

- **多级别联动**：`CChan.lv_list` 可配置多个级别（如日线+60分钟），低级别 K 线单元会挂到父级别 K 线上（`klu.sup_kl`），支撑跨级别背驰与买卖点判定。
- **指标旁路**：MACD/BOLL/RSI/KDJ/Demark 在 `CKLine_Unit` 构造时同步计算，供背驰判定和绘图使用，不参与层级递进。
- **缓存层**：`main.py` 通过 `ChanSqliteCache`（`chan.db`）做增量缓存，`SQLiteAPI` 作为数据源直接从缓存读，避免重复走网络。
- **监控旁路**：`monitor/` 是独立的均线接近告警系统，不依赖缠论核心和 chan.db，直接用 akshare 拉数据做 SMA 判定。
