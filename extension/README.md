# ETF 跟踪扩展项目

## 功能说明

本目录存放2026-10-29从 GitHub 下载的 A 股 ETF 份额、宽基资金动向相关项目，供本地研究选型。**未安装依赖、未运行代码、未启动服务，也未自动启用技能或定时任务。**

| 本地目录 | 上游项目 | 主要用途 | 限制 |
| --- | --- | --- | --- |
| [akshare/](akshare/) | [AKShare](https://github.com/akfamily/akshare) | 沪深交易所ETF日份额、深市历史份额和行情数据底座 | MIT；不是现成监控看板，份额不是盘中实时披露 |
| [national-team-position/](national-team-position/) | [国家队持仓估计](https://github.com/Xiaoyuan-Liu/national-team-position) | 六类沪市宽基ETF份额历史图和JSON | MIT；周/月采样，不包含创业板及深市ETF，名称中的国家队为代理估计 |
| [Resonance/](Resonance/) | [同频](https://github.com/OrangesHuang/Resonance) | 盘中量价信号、日份额变化、五因子看板 | 约30秒更新行情而非份额；未发现明确许可证，默认池不含创业板159915/创业板50 159949，待授权和功能验证 |

详细报告：[A股ETF份额跟踪项目调研](../docs/20261029_A股ETF份额跟踪项目调研.md)，包含下载提交、其他候选、源码证据、原始上游实测结果、观察池及后续参数示例。

## 参数说明

- AKShare：上交所份额应显式传 `date`；深交所历史份额使用 `start_date`、`end_date`、`symbol="ETF"`。不要将无日期参数的最新快照接口用于历史回补。
- national-team-position：`--start`、`--end`、`--freq weekly|monthly`、`--output-dir`、`--data-only`。
- Resonance：`ETF_MONITOR_HOME` 指定数据库工作目录，ETF池和轮询间隔见 `backend/base/config.py`。默认启动脚本可能监听所有网卡，后续本地评估应使用 `127.0.0.1`。

## 使用示例

以下仅查看已下载版本，不安装依赖、不执行监控程序：

```powershell
# 从主工程根目录执行。
git -C extension/akshare log -1 --oneline
git -C extension/national-team-position log -1 --oneline
git -C extension/Resonance log -1 --oneline
```

后续手动取数、运行趋势图和本地启动命令见详细报告；使用前需准备独立环境、核实许可并验证上游数据。

## 必须注意

- ETF总份额变化不等于国家队买卖，场内交易还可能不改变份额。
- 公开机构持有人信息是滞后的报告期数据，不能用于实时确认账户身份。
- 启发式“概率”只是评分，不是经过验证的国家队身份概率。
- 三个扩展保留各自 `.git`，不要直接全仓暂存；后续选择子模块或源码快照方式需单独处理。
- 第三方原始代码保持不变；Resonance 的再分发、商业使用或合并到主工程前，应先向作者确认授权。
