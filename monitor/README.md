# K线均线接近监控脚本

监控 A 股**指数 / 个股**与**指定周线均线（默认 50 周线）**的接近程度，当现价落入均线 ±2% 区间时，终端高亮 + 蜂鸣提示。

- 与缠论主程序解耦：不读 `chan.db`、不改既有代码
- 数据来源 akshare（零登录、支持指数与个股、盘中可用）
- 两种运行模式：盘后跑一次（可挂 Windows 计划任务）/ 盘中常驻轮询

## 环境要求

与项目主程序同环境（`chan_py311`）即可，需安装：

```
akshare
pandas
pyyaml
```

前两个项目已在用，新增仅 `pyyaml`：

```
conda activate chan_py311
pip install pyyaml
```

## 目录结构

```
monitor/
  __init__.py       包标识
  config.yaml       监控标的、均线周期、阈值、轮询间隔等配置
  watchlist.txt     自选个股清单（每行一个代码）
  data_source.py    akshare 数据源封装（周线序列 + 实时现价）
  indicators.py     SMA 与"接近均线"判定
  alerts.py         终端彩色输出与蜂鸣
  run.py            CLI 入口
```

## 用法

在项目根目录执行（注意用 `-m` 以包方式运行，保证相对导入正确）：

```bash
conda activate chan_py311

# 盘后模式：跑一次后退出（用最新周线收盘价判定）
python -m monitor.run --mode eod

# 盘中模式：常驻轮询，每 5 分钟刷一次，仅交易时段工作
python -m monitor.run --mode live --interval 300

# 指定其它配置 / 自选清单
python -m monitor.run --mode eod --config monitor/config.yaml --watchlist monitor/watchlist.txt
```

## 配置说明（config.yaml）

| 字段              | 说明                                    | 默认                    |
| ----------------- | --------------------------------------- | ----------------------- |
| `ma_period`     | 均线周期（周）                          | 50                      |
| `threshold`     | 接近阈值（小数，0.02=±2%）             | 0.02                    |
| `targets`       | 监控标的列表，含`code/name/kind`      | 上证50/沪深300/创业板指 |
| `interval`      | live 模式轮询间隔（秒）                 | 300                     |
| `history_start` | 周线历史拉取起始日期                    | 2023-01-01              |
| `adjust`        | 个股复权方式`qfq/hfq/""`              | qfq                     |
| `session`       | 交易时段（live 模式据此跳过非交易时段） | A股标准时段             |
| `max_retry`     | 网络请求失败重试次数                    | 3                       |

### 标的代码格式（akshare 简写）

- 指数：`sh000016`（上证50）、`sh000300`（沪深300）、`sz399006`（创业板指）
- 个股：`sh600519`、`sz000858`

### 自选个股（watchlist.txt）

每行一个代码，`#` 开头或空行忽略：

```
sh600519   # 贵州茅台
sz000858   # 五粮液
```

## 信号判定

- 均线：周线收盘价的 SMA(50)
- 当前价：
  - `eod` 模式 = 最新一根周线收盘价
  - `live` 模式 = akshare 实时现价（盘中周线未收，用现价近似本周收盘）
- 触发：`|现价 - MA50| / MA50 ≤ 2%`
- 方向：现价在均线上方（↑ 绿）/ 下方（↓ 红）

## 挂定时任务（可选）

盘后模式适合用 Windows 任务计划每天收盘后自动跑：

1. 打开"任务计划程序" → 创建基本任务
2. 触发器：每日 15:35
3. 操作：启动程序
   - 程序：`D:\xuquanqing\software\xqqminiforge\envs\chan_py311\python.exe`
   - 参数：`-m monitor.run --mode eod`
   - 起始位置：`D:\xuquanqing\persion\Chan`

## 注意事项

- akshare 实时接口偶发限频/超时：已内置重试，单只失败不影响整体。
- 周线重采样按 `W-FRI` 取每周最后交易日收盘，停牌周自动 dropna，保证均线连续。
- 历史数据需 ≥ `ma_period + 10` 周，否则该标的显示"数据不足"。
