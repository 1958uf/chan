# 重构方案：通用行情数据底座 + 多策略 + 统一回测框架

> 版本：v2（2026-09-15 优化）
> 变更要点：补全 `ChanModel/` 迁移、修正 `CTime` 语义、明确 `__init__.py` 补建、细化回测-缠论适配、增加风险与回滚章节。

## Context（为什么做这次重构）

当前项目所有数据源的 `get_kl_data()` 都**强制返回 `CKLine_Unit`**（缠论专属 K 线对象，构造即 import `Math.*`/`KLine.TradeInfo` 等缠论依赖），形成硬耦合：任何想复用数据层的非缠论策略，都不得不连缠论模块一起 import，无法干净拿纯 OHLCV。

同时，缠论核心（`Chan.py`、`ChanConfig.py`、`KLine/`、`Bi/`、`Seg/`、`ZS/`、`BuySellPoint/`、`Combiner/`、`ChanModel/`、`Plot/`、`Debug/` 等）散落在根目录占据特权位置，与"多策略平级"的框架目标矛盾。

本次重构把项目演进为 **「通用行情数据底座 + 公共基础设施 + 多策略（含缠论）+ 统一回测引擎」** 的框架，使长期开发多种非缠论策略（均线、动量、配对等）并回测时，策略间互不耦合、数据层纯净、回测统一。

### 用户已确认的设计选择
1. **OHLCV 载体**：`dataclass` 定义 `KBar`（不绑定 pandas）
2. **缠论彻底去特权化**：`Chan.py` + `ChanConfig.py` + `KLine/Bi/Seg/ZS/BuySellPoint/Combiner/ChanModel/` + `Plot/` + `Debug/` **全部移入 `Strategies/chan/`**
3. **公共层**：`Common/`、`Math/` 留在框架公共层（含通用指标 RSI/MACD 等，非缠论策略也可用）
4. **统一回测**：新建 `Backtest/` 统一回测引擎（事件驱动逐 K 线、资产/持仓/交易、收益统计）
5. **入口**：保留 `main.py`（缠论扫描，向后兼容）+ 新建 `cli.py`（多策略统一 CLI）
6. **数据层兼容**：`DataAPI/` 保留为兼容层，旧调用零改动

---

## 重构后顶层结构

```
Chan/
├── DataBasis/                    # 【新】通用行情数据底座（零缠论依赖）
│   ├── __init__.py
│   ├── kbar.py                   # KBar dataclass
│   ├── stock_api.py              # CStockApi 抽象基类（get_kl_data → Iterable[KBar]）
│   ├── data_factory.py           # create_data_api(DATA_SRC) 工厂
│   ├── baostock_api.py           # 各数据源实现（返回 KBar），类名 CBaoStock
│   ├── akshare_api.py            # 类名 CAkshare
│   ├── ccxt_api.py               # 类名 CCXT
│   ├── csv_api.py                # 类名 CSV_API
│   ├── sqlite_api.py             # 类名 SQLite_API，从 chan.db 读 KBar
│   └── sqlite_cache.py           # 从 DataAPI/sqlite_cache.py 迁移，纯 OHLCV 缓存管理
│
├── Common/                       # 【留公共层】枚举/时间/异常/工具（通用基础设施）
├── Math/                         # 【留公共层】MACD/BOLL/RSI/KDJ/Demark/趋势线（通用指标）
│
├── Strategies/                   # 【新】策略层（所有策略平级）
│   ├── __init__.py
│   ├── base.py                   # CStrategy 抽象基类（统一策略接口契约）
│   ├── registry.py               # 策略注册表（按名称查找策略类）
│   ├── chan/                     # 缠论策略（从根目录迁入，去特权化）
│   │   ├── __init__.py
│   │   ├── Chan.py               # ← 原 Chan.py
│   │   ├── ChanConfig.py         # ← 原 ChanConfig.py
│   │   ├── ChanModel/            # ← 原 ChanModel/（Features.py，买卖点特征容器）
│   │   ├── KLine/  Bi/  Seg/  ZS/  BuySellPoint/  Combiner/   # ← 原各模块
│   │   ├── Plot/                 # ← 原 Plot/（缠论专属绘图）
│   │   ├── chan_adapter.py       # 【新】KBar → CKLine_Unit 适配 + 回测 on_bar 桥接
│   │   ├── examples/             # ← 原 Debug/strategy_demo*.py
│   │   └── README.md
│   └── example_ma/               # 【新】非缠论策略示例（均线策略，只依赖 DataBasis+Math）
│       ├── __init__.py
│       ├── ma_strategy.py
│       └── README.md
│
├── Backtest/                     # 【新】统一回测引擎
│   ├── __init__.py
│   ├── engine.py                 # 事件驱动回测引擎（逐 K 线推进）
│   ├── broker.py                 # 撮合/持仓/资金管理
│   ├── portfolio.py              # 资产组合与交易记录
│   ├── metrics.py                # 收益统计（胜率/最大回撤/夏普/年化）
│   └── README.md
│
├── DataAPI/                      # 【兼容层】委托 DataBasis，旧调用零改动
│   ├── CommonStockAPI.py         # 继承 CStockApi + get_kl_data_legacy() 返回 CKLine_Unit
│   ├── BaoStockAPI.py            # 委托 DataBasis.baostock_api，保留类名 CBaoStock
│   ├── AkshareAPI.py             # 委托，保留类名 CAkshare
│   ├── ccxt.py                   # 委托，保留类名 CCXT
│   ├── csvAPI.py                 # 委托，保留类名 CSV_API
│   ├── SQLiteAPI.py              # 委托，保留类名 SQLite_API
│   ├── sqlite_cache.py           # 转发 DataBasis.sqlite_cache（ ChanSqliteCache ）
│   └── __init__.py
│
├── App/                          # 不变（更新 import 路径）
├── monitor/                      # 不变（独立旁路）
├── pool/  Script/  doc/  Image/  # 不变
├── chan.db                       # 不变
├── main.py                       # 保留（缠论扫描入口，更新 import 路径）
├── cli.py                        # 【新】多策略统一 CLI（选策略+参数+回测）
├── run.bat / setup_env.sh        # 微调（setup_env 验证项不变）
└── arch.md                       # 同步更新
```

> **注意**：原根目录的 `Bi/ Seg/ ZS/ Combiner/ ChanModel/` 等目录**当前没有 `__init__.py`**，靠 `sys.path` 裸导入。迁入 `Strategies/chan/` 后**必须为每个子目录补建 `__init__.py`**（空文件即可），否则相对 import 不生效。

---

## 核心设计：分层与适配

### 第 1 层：DataBasis（纯净行情底座）

**`DataBasis/kbar.py`** —— 纯 OHLCV 载体（`time` 用标准库 `datetime`，不泄漏 `Common.CTime`）：

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass(frozen=True)
class KBar:
    """单根 K 线的纯数据载体。
    功能：承载 OHLCV 原始数据，不依赖任何缠论模块。
    字段：time 为 datetime（精度到分钟，秒/微秒在适配层截断）；OHLCV/turnover/turnrate 为 float（不可得时为 None）。
    """
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    turnover: Optional[float] = None
    turnrate: Optional[float] = None
```

**`DataBasis/stock_api.py`** —— 抽象基类（对照 `DataAPI/CommonStockAPI.py`，去掉 `CKLine_Unit` 依赖），`get_kl_data() → Iterable[KBar]`。保留 `do_init`/`do_close`/`SetBasciInfo` 接口签名不变。

**`DataBasis/*_api.py`**：从 `DataAPI/*.py` 迁移字段映射逻辑（`create_item_dict`/`parse_time_column`/`str2float` 全保留），唯一变化 `yield CKLine_Unit(dict)` → `yield KBar(...)`，时间产出 `datetime` 而非 `CTime`。**类名保持一致**（`CBaoStock`/`CAkshare`/`CCXT`/`CSV_API`/`SQLite_API`），便于兼容层零改动委托。

**`DataBasis/sqlite_cache.py`**：从 `DataAPI/sqlite_cache.py` 原样迁移（本就不依赖 `CKLine_Unit`），保留类名 `ChanSqliteCache`。

**`DataBasis/data_factory.py`** —— `create_data_api(DATA_SRC)` 工厂（对照 `Chan.py:GetStockAPI` 抽离）：

```python
def create_data_api(data_src) -> type:
    """按 DATA_SRC 返回数据源类（返回 KBar 的纯净实现）。"""
    from Common.CEnum import DATA_SRC
    _map = {
        DATA_SRC.BAO_STOCK: CBaoStock,
        DATA_SRC.CCXT: CCXT,
        DATA_SRC.CSV: CSV_API,
        DATA_SRC.AKSHARE: CAkshare,
        DATA_SRC.SQLITE: SQLite_API,
    }
    return _map[data_src]
```

### 第 2 层：公共基础设施（Common / Math）

`Common/`、`Math/` 保持原位、原内容。它们是框架级公共层：`Math` 的 MACD/RSI/BOLL/KDJ 是通用指标，非缠论策略可直接复用；`Common` 的枚举/时间/异常/工具被全框架共用。**缠论移入子目录后，其内部对 `Common`/`Math` 的绝对 import 路径不变**（仍是 `from Common.CEnum import ...`、`from Math.MACD import ...`），因为这两个目录没动。

### 第 3 层：Strategies（策略层）

**`Strategies/base.py`** —— 统一策略接口契约：

```python
class CStrategy(abc.ABC):
    """策略抽象基类。
    功能：定义所有策略（缠论/非缠论）的统一接口契约。
    设计：策略只依赖 DataBasis.KBar，不依赖其他策略内部对象。
    """
    def __init__(self, code, k_type, begin_date, end_date, data_src, autype): ...
    @abstractmethod
    def on_bar(self, bar: KBar, ctx: "BacktestContext"):
        """逐 K 线回调，产生交易信号。ctx 提供下单 API 与当前持仓/资金。"""
    def generate_signals(self) -> list:
        """（可选）一次性计算全部信号，供非回测场景。默认空实现。"""
        return []
```

**`Strategies/chan/chan_adapter.py`** —— 缠论适配器（两职责：KBar→CKLine_Unit 转换 + 回测 on_bar 桥接）：

```python
def kbar_to_klu_dict(kbar: KBar, autofix=False) -> dict:
    """KBar → CKLine_Unit 构造所需的 DATA_FIELD 字典。
    关键：time 必须转为 CTime（引擎全程依赖 CTime 比较运算与 .ts）。
    精度：KBar.time 可能带秒/微秒，这里截断到分钟（与缠论 K 线粒度一致）。
    auto 语义：传入 auto=True 时，CTime 在 hour=0且minute=0 下会把 ts 设为当日 23:59。
    """
    from Common.CTime import CTime
    from Common.CEnum import DATA_FIELD
    t = kbar.time
    return {
        DATA_FIELD.FIELD_TIME: CTime(t.year, t.month, t.day, t.hour, t.minute, auto=True),
        DATA_FIELD.FIELD_OPEN: kbar.open, DATA_FIELD.FIELD_HIGH: kbar.high,
        DATA_FIELD.FIELD_LOW: kbar.low, DATA_FIELD.FIELD_CLOSE: kbar.close,
        DATA_FIELD.FIELD_VOLUME: kbar.volume,
        DATA_FIELD.FIELD_TURNOVER: kbar.turnover,
        DATA_FIELD.FIELD_TURNRATE: kbar.turnrate,
    }

def autofix_for(data_src) -> bool:
    """保留各数据源原有 autofix 设定：仅 CCXT 为 True，其余 False。"""
    from Common.CEnum import DATA_SRC
    return data_src == DATA_SRC.CCXT
```

> **CTime 语义澄清**（核对 `Common/CTime.py` 后）：`CTime(..., auto=True)` 仅在 `hour==0 且 minute==0` 时把 `ts` 设为当日 23:59，否则用真实时分。`KBar.time` 的 `datetime` 转换时统一传 `auto=True`：日线（时分为 0）自动对齐到 23:59，分钟级别用真实时分——与原数据源直接构造 `CKLine_Unit` 的行为一致。

**缠论迁移要点**（`Strategies/chan/` 内）：
- `Chan.py` 的 `load_stock_data()` 改为遍历 `get_kl_data()` 的 KBar，经 `kbar_to_klu_dict` 转 `CKLine_Unit`（约 5 行变化，autofix 取自 `autofix_for(self.data_src)`）
- **缠论内部模块间 import 改造**：内部相互引用从绝对路径改为**包内相对路径**。例如：
  - `Chan.py`：`from KLine.KLine_List import ...` → `from .KLine.KLine_List import ...`
  - `Bi/Bi.py`：`from KLine.KLine import CKLine` → `from ..KLine.KLine import CKLine`
  - `Seg/Seg.py`：`from KLine.KLine_Unit import ...` → `from ..KLine.KLine_Unit import ...`
  - `ZS/ZS.py`：`from KLine.KLine_Unit import ...` → `from ..KLine.KLine_Unit import ...`
  - `BuySellPoint/BS_Point.py`：`from ChanModel.Features import CFeatures` → `from ..ChanModel.Features import CFeatures`
  - `KLine/KLine_List.py`：`from Bi.Bi import CBi` → `from ..Bi.Bi import CBi`，等
  - 对 `Common`/`Math` 的引用**保持绝对**（`from Common.CEnum import ...` 不变，因它们在公共层）
  - `from Chan import CChan`（自引用）→ `from .Chan import CChan` 或 `from Strategies.chan.Chan import CChan`
- `Plot/`、`ChanModel/`、`Debug/`(→`examples/`) 同步迁移，内部对缠论模块的 import 改相对路径
- **补建 `__init__.py`**：`Strategies/chan/` 及其所有子目录（`KLine/ Bi/ Seg/ ZS/ BuySellPoint/ Combiner/ ChanModel/ Plot/ examples/`）均需创建空 `__init__.py`

> 这是本次最繁的部分，但纯机械替换，可用脚本辅助批量改写后人工核对。

### 第 4 层：Backtest（统一回测引擎）

**`Backtest/engine.py`** —— 事件驱动逐 K 线推进：
```python
class CBacktestEngine:
    """统一回测引擎。
    功能：逐 K 线驱动策略 on_bar 回调，经 broker 撮合，记录 portfolio 变化。
    输入：strategy(CStrategy)、data_iter(Iterable[KBar])、初始资金、手续费率
    输出：BacktestResult（含交易记录、资金曲线、统计指标）
    """
```

**`Backtest/broker.py`**：撮合（市价/限价）、持仓管理、手续费/滑点。
**`Backtest/portfolio.py`**：资金、持仓快照、交易记录、资金曲线。
**`Backtest/metrics.py`**：胜率、盈亏比、最大回撤、年化收益、夏普比率。

> 回测引擎只依赖 `DataBasis.KBar` + `Strategies.base.CStrategy`，与缠论完全解耦。

**缠论接入回测的桥接**（关键，文档此前未说清）：

缠论的 `CChan.trigger_step()` 是"步进式喂下一根 K 线并触发计算"，与 `CStrategy.on_bar(bar)` 的逐 K 线回调语义不同。桥接方式：在 `Strategies/chan/chan_adapter.py` 提供 `ChanStrategyAdapter(CStrategy)`：

```python
class ChanStrategyAdapter(CStrategy):
    """缠论策略的回测适配器。
    功能：把 CChan 的 trigger_step 步进模型包装成 CStrategy.on_bar 回调模型。
    实现：内部持有 CChan 实例，on_bar 时调用 chan.trigger_step() 喂入该 K 线，
         然后查询 chan 最新买卖点状态，转化为下单信号交给 ctx。
    """
    def __init__(self, code, k_type, begin_date, end_date, data_src, autype, chan_config=None):
        super().__init__(...)
        self._chan = CChan(code, begin_time=begin_date, end_time=end_date,
                           data_src=data_src, lv_list=[k_type], config=chan_config)
    def on_bar(self, bar: KBar, ctx):
        klu_dict = kbar_to_klu_dict(bar, autofix=autofix_for(self.data_src))
        klu = CKLine_Unit(klu_dict)
        self._chan.trigger_step(klu)  # 逐步喂数据
        bsp_list = self._chan.get_bsp_last_step()  # 取本步新增买卖点
        for bsp in bsp_list:
            if bsp.is_buy:
                ctx.buy(self.code, bar.close)
            else:
                ctx.sell(self.code, bar.close)
```

> 这样回测引擎无需感知缠论内部，缠论也无需改造 `trigger_step`。非回测场景（扫描）仍直接用 `CChan`。

### 第 5 层：兼容层 DataAPI/

`DataAPI/CommonStockAPI.py` 继承 `DataBasis.CStockApi`，新增 `get_kl_data_legacy()` 返回 `CKLine_Unit`（内部遍历 KBar，经 `Strategies.chan.chan_adapter.kbar_to_klu_dict` 转换，autofix 取自 `autofix_for(data_src)`）。各 `DataAPI/*.py` 委托 `DataBasis` 对应实现，保留原类名（`CBaoStock`/`CAkshare`/`CCXT`/`CSV_API`/`SQLite_API`）。`DataAPI/sqlite_cache.py` 转发 `DataBasis.sqlite_cache` 的 `ChanSqliteCache`。

> 这样 `main.py`、`App/`、`Strategies/chan/examples/` **仅改 import 路径**即可继续运行，行为完全一致。`main.py` 中 `from DataAPI.sqlite_cache import ChanSqliteCache` **不变**（兼容层转发）。

---

## 关键文件改动清单

### 新增文件
| 文件 | 作用 |
|---|---|
| `DataBasis/*`（kbar/stock_api/data_factory + 5 个数据源 + sqlite_cache + __init__） | 纯净行情底座 |
| `Strategies/base.py`、`registry.py`、`__init__.py` | 策略接口契约 + 注册表 |
| `Strategies/chan/chan_adapter.py` | KBar→CKLine_Unit 适配 + `ChanStrategyAdapter` 回测桥接 |
| `Strategies/chan/README.md`、`Strategies/example_ma/*` | 缠论说明 + 非缠论示例 |
| `Backtest/{engine,broker,portfolio,metrics}.py` + `README.md` | 统一回测引擎 |
| `cli.py` | 多策略统一 CLI |
| `Strategies/chan/` 下所有子目录的 `__init__.py` | 包化所需（原目录无） |

### 迁移文件（移动 + import 改写 + 补 __init__.py）
| 原位置 | 新位置 | 改动 |
|---|---|---|
| `Chan.py`、`ChanConfig.py` | `Strategies/chan/` | 内部 import 改相对路径；`load_stock_data` 接适配器 |
| `KLine/ Bi/ Seg/ ZS/ BuySellPoint/ Combiner/ ChanModel/` | `Strategies/chan/` 下同名目录 | 模块间 import 改相对路径（对 Common/Math 保持绝对）；补 `__init__.py` |
| `Plot/` | `Strategies/chan/Plot/` | 对缠论模块 import 改相对路径；补 `__init__.py` |
| `Debug/strategy_demo*.py` | `Strategies/chan/examples/` | import 路径更新（`from Chan` → `from Strategies.chan.Chan`，`from ChanModel` → `from Strategies.chan.ChanModel` 等） |

### 修改文件
| 文件 | 改动 |
|---|---|
| `main.py` | 缠论 import 路径更新（`from Chan` → `from Strategies.chan.Chan`，`from ChanConfig` → `from Strategies.chan.ChanConfig`，`from Plot.*` → `from Strategies.chan.Plot.*`）；`DataAPI` 相关 import 不变 |
| `App/ashare_bsp_scanner_gui.py` | 同上，缠论 import 路径更新 |
| `DataAPI/CommonStockAPI.py` | 继承 `DataBasis.CStockApi`，加 `get_kl_data_legacy` |
| `DataAPI/BaoStockAPI.py`、`AkshareAPI.py`、`ccxt.py`、`csvAPI.py`、`SQLiteAPI.py` | 委托 `DataBasis` 实现，保留类名 |
| `DataAPI/sqlite_cache.py` | 转发 `DataBasis.sqlite_cache` |
| `Script/migrate_csv_to_sqlite.py` | `sqlite_cache` import 源改为 `DataBasis`（或经 `DataAPI` 兼容层，二者皆可） |
| `arch.md` | 同步更新分层架构说明 |
| `run.bat` | 不变（仍 `python main.py`）；`setup_env.sh` 验证项不变 |

### 不动的文件
- `Common/`、`Math/`（内容、位置全不变）
- `monitor/`、`pool/`、`doc/`、`Image/`、`chan.db`
- `stock_pool.txt`、`debug.log`、`LICENSE`

---

## 关键约束（实现时务必遵守）

1. **CTime 转换**：`KBar.time`（datetime）转 `CKLine_Unit` 时构造 `CTime(year,month,day,hour,minute, auto=True)`。注意 `auto=True` **仅在 hour=0且minute=0 时**把 `ts` 设为当日 23:59（核对 `Common/CTime.py:33-38`），分钟级别用真实时分。适配层统一传 `auto=True` 即可复刻原行为，不可绕过。
2. **autofix 处理**：原 `ccxt.py` 用 `autofix=True`，其他不用（核对 `DataAPI/ccxt.py:47`）。适配器通过 `autofix_for(data_src)` 保留每数据源原有 autofix 设定，不要一刀切。
3. **OHLC 校验**：转换后由 `CKLine_Unit.check()` 自身校验，底座层不重复校验。
4. **可选字段**：`volume/turnover/turnrate` 缺失为 `None`，`CTradeInfo` 已能容忍，不影响核心计算。
5. **相对 import 改写**：缠论模块移入 `Strategies/chan/` 后，**仅模块间相互引用**改相对路径；对 `Common`/`Math` 的引用保持绝对路径不变（它们在公共层）。
6. **`__init__.py` 补建**：原 `Bi/ Seg/ ZS/ Combiner/ ChanModel/` 等无 `__init__.py`，迁入后必须补建，否则包内相对 import 失效。
7. **`ChanModel` 不可遗漏**：`BuySellPoint/BS_Point.py:4` 和 `Debug/strategy_demo5/6.py` 依赖 `ChanModel.Features`，必须随缠论一起迁入 `Strategies/chan/ChanModel/`。
8. **`__deepcopy__`**：`CChan` 深拷贝不涉及数据源（`g_kl_iter` load 后已耗尽），适配器无需参与拷贝。
9. **回测引擎与缠论解耦**：`Backtest/` 只 import `DataBasis` + `Strategies.base`，不 import 任何 `Strategies.chan.*` 内部模块。缠论通过 `ChanStrategyAdapter`（在 `Strategies/chan/` 内）接入回测。
10. **时间精度截断**：`KBar.time` 是 `datetime`，可能含秒/微秒；转 `CTime` 时只取 `year/month/day/hour/minute`，与缠论 K 线粒度一致。

---

## 实施步骤（建议顺序，每步可独立验证）

1. **建 DataBasis 骨架并迁移数据源**：`kbar.py`/`stock_api.py`/`data_factory.py` + 5 数据源 + `sqlite_cache`（返回 KBar）。`grep` 确认无缠论依赖。
2. **建 Strategies/chan/chan_adapter.py**：实现 `kbar_to_klu_dict` + `autofix_for`。
3. **迁移缠论代码**：移动 `Chan.py`/`ChanConfig.py`/`KLine/Bi/Seg/ZS/BuySellPoint/Combiner/ChanModel/Plot/Debug` 到 `Strategies/chan/`，**补建所有 `__init__.py`**，批量改相对 import，`Chan.load_stock_data` 接适配器。
4. **建 DataAPI 兼容层**：各文件委托 DataBasis + `get_kl_data_legacy`；`sqlite_cache.py` 转发。
5. **更新外部调用方 import**：`main.py`、`App/`、`Strategies/chan/examples/`、`Script/migrate_csv_to_sqlite.py`。
6. **缠论回归验证**：`python main.py` 单股 + 批量扫描，GUI，examples，确认行为不变。
7. **建 Strategies/base.py + registry.py + example_ma**：非缠论策略骨架，只依赖 DataBasis+Math。
8. **建 Backtest/**：engine/broker/portfolio/metrics，用 example_ma 跑通一次回测。
9. **实现 ChanStrategyAdapter**：缠论接入回测，跑通一次缠论回测。
10. **建 cli.py**：统一 CLI（选策略/参数/回测）。
11. **更新 arch.md**：补充 DataBasis/Strategies/Backtest 分层说明。

---

## 验证方式（端到端）

1. **缠论回归（兼容性）**：
   - `python main.py` 单股查询（如 `sh.600519`），对比重构前后买卖点输出一致
   - `python main.py` 批量扫描股票池，买点汇总不变
   - 运行 `Strategies/chan/examples/strategy_demo.py`，回测快照一致
   - 启动 `App/ashare_bsp_scanner_gui.py`，GUI 扫描与绘图正常
2. **底座独立性**：
   - `python -c "import DataBasis"` 成功
   - `grep -rE "from (Chan|KLine|Bi|Seg|ZS|BuySellPoint|Combiner|ChanModel|Strategies.chan)" DataBasis/` 无结果
3. **策略独立性**：
   - `python Strategies/example_ma/ma_strategy.py` 运行，只 import `DataBasis`+`Math`（无 `Strategies.chan` 内部 import），输出均线金叉/死叉
4. **回测引擎**：
   - `python cli.py --strategy example_ma --code sh.600519 --backtest` 跑通，输出收益统计（胜率/回撤/夏普）
   - `python cli.py --strategy chan --code sh.600519 --backtest` 跑通缠论回测
   - `grep -rE "from Strategies.chan" Backtest/` 无结果（回测引擎零缠论依赖）
5. **缓存验证**：`chan.db` 增量更新逻辑正常（`ChanSqliteCache` 行为不变）
6. **import 全检**：`python -c "import Strategies.chan.Chan; import Strategies.example_ma; import Backtest.engine"` 全部成功

---

## 风险与回滚

### 主要风险
1. **相对 import 改写遗漏**：缠论模块间引用密集（`KLine_List` 引 `Bi/Seg/ZS/BuySellPoint/Combiner`，`Seg` 引 `Bi/Combiner`，`ZS` 引 `Bi/Seg/BuySellPoint` 等），批量替换易漏。**对策**：改完后用 `python -c "import Strategies.chan.Chan"` 逐层验证，配合 `grep -rE "from (KLine|Bi|Seg|ZS|BuySellPoint|Combiner|ChanModel|Chan) " Strategies/chan/` 确认无残留绝对路径。
2. **`ChanModel` 遗漏导致 `BS_Point` import 失败**：买卖点模块是缠论核心依赖链末端，遗漏会连锁失败。**对策**：步骤 3 完成后立即跑 `python -c "from Strategies.chan.BuySellPoint.BS_Point import CBS_Point"`。
3. **`CTime` auto 语义误用**：若适配层对分钟级别也传 `auto=False` 或截断错误，多级别对齐会错乱（日线 ts 变成 00:00 而非 23:59）。**对策**：统一传 `auto=True`，并用单股日线用例对比重构前后 `klu.time.ts` 一致。
4. **`__init__.py` 缺失致包化失败**：相对 import 全部报错。**对策**：步骤 3 第一步就批量建空 `__init__.py`。
5. **回测-缠论桥接语义偏差**：`trigger_step` 喂入的是 `CKLine_Unit`，而 `on_bar` 拿到的是 `KBar`，中间转换若 autofix/时间不一致会导致缠论计算结果与直接运行 `CChan` 不同。**对策**：步骤 9 用同一股票、同一时段对比 `ChanStrategyAdapter` 回测的买卖点与 `CChan` 直跑的买卖点一致。

### 回滚策略
- 每个步骤独立提交（git），任一步骤验证失败可 `git revert` 单步回滚。
- 步骤 3（缠论迁移）是最大风险点，建议在独立分支进行，回归通过后再合并。
- 兼容层 `DataAPI/` 保证旧代码路径始终可用，即便新层出问题也不影响 `main.py` 运行。

---

## 预期收益

- **数据底座纯净**：`DataBasis/` 零缠论依赖，任何策略直接用 `KBar`
- **缠论去特权化**：缠论成为 `Strategies/chan/` 下与其他策略平级的一个策略，根目录只剩框架级文件
- **策略可扩展**：新增策略只需在 `Strategies/` 下建子包、实现 `CStrategy`、注册到 registry
- **统一回测**：所有策略共用 `Backtest/` 引擎，缠论（通过 `ChanStrategyAdapter`）与非缠论策略一致回测
- **兼容平滑**：旧代码继续用 `DataAPI`/`main.py`，新代码用 `DataBasis`/`cli.py`，无需一次性迁移
