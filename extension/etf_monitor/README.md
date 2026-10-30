# ETF 监控系统

## 功能说明

这是新增的独立本地 Web 系统，主线是**多类别ETF日份额观察**：产品目录、类别同日份额、可比成员增减、日/周/月历史、日更和补采。盘中量价、公开披露与研究评分保留为辅助，默认不自动轮询。使用独立数据库，不改变缠论、原monitor或chan.db；不下单。

**数据口径**：ETF总份额不是国家队持仓；盘中行情不是实时申赎；信号为可解释研究评分，不是机构身份概率。演示模式有固定样本且持续标识，不能作投资依据。

## 环境与安装

要求Python≥3.11、Node/npm。不要用指向其他环境的裸pip。

```powershell
# 从主工程根目录执行；将python3.11替换为自己的明确解释器路径。
python3.11 -m venv extension/etf_monitor/.venv
extension/etf_monitor/.venv/Scripts/python.exe -m pip install --index-url https://pypi.org/simple -e "extension/etf_monitor[test]"

# 在extension/etf_monitor/frontend中执行。
npm.cmd ci
npm.cmd run build
```

锁文件记录实际安装依赖；安装与运行分开，启动脚本不自动安装、删除缓存或结束已有进程。

## 参数说明

| 参数 | 默认 | 用途 |
|---|---|---|
| `ETF_MONITOR_MODE` | live | live使用真实数据；demo用隔离演示数据 |
| `ETF_MONITOR_HOME` | 系统runtime目录 | 独立运行数据目录，不使用主工程chan.db |
| `ETF_MONITOR_SCHEDULER` | 0 | 1显式开启份额日更，0只通过界面手工采集 |
| `intraday_enabled` | false | 盘中自动轮询默认关闭，行情保留辅助 |
| `daily_update_hour/minute` | 18/17 | 日更起始时刻，统计日仍依据实际披露数据 |
| `ETF_MONITOR_TOKEN` | 本次运行生成 | 本地变更API令牌，不打印、不写入健康报告 |
| `-Port` | 8765 | PowerShell启动端口，仅127.0.0.1 |
| `-Mode` | demo | 启动脚本默认演示，真实运行须显式live |
| `-Schedule` | 关闭 | 启用目录与份额日更，盘中自动默认关闭 |

观察池在`config/etfs.json`，核心包含上证50、四只沪深300、科创50、创业板/创业板50等；配置和页面新增标的均严格校验。

## 使用示例

```powershell
# 显式演示，不联网采集。
& ./extension/etf_monitor/scripts/start.ps1 -Mode demo

# 真实模式，先手动采集并观察源状态。
& ./extension/etf_monitor/scripts/start.ps1 -Mode live

# 数据验证后需要常驻调度时才打开。
& ./extension/etf_monitor/scripts/start.ps1 -Mode live -Schedule
```

前端构建完成后访问`http://127.0.0.1:8765`。Ctrl+C关闭本次服务；端口被占用会提示失败，不结束原有程序。

## 检测测试

```powershell
# 从系统目录执行离线单元/集成和覆盖率，默认不联网。
.venv/Scripts/python.exe -m pytest -m "not live" --cov=etf_monitor --cov-report=term-missing

# 从frontend目录执行类型、构建、组件测试。
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test -- --run
```

真实接口验收应显式开启、限量请求并记录原始日期与单位；不能用失败后演示数据替代通过。完整命令、浏览器端到端和最终结果见正式验收报告（实现与验证结束后生成）。

## 本轮份额主线验收

后端399项离线测试通过、覆盖率96.29%；前端75项测试、22项浏览器契约场景与5项真实演示后端浏览器场景通过。有限目录抽查发现1691只ETF，其中核心确认19只、候选1017只、未分类655只；发现不等于全分类已确认。

文档：[份额使用说明](../../docs/多类别ETF份额观察站使用说明.md)、[份额数据口径](../../docs/多类别ETF份额观察站数据口径.md)、[可靠性验收报告](../../docs/多类别ETF份额观察站可靠性验收报告.md)。真实历史按需回填，盘中不再作为主要开发目标。

## 运行限制

- 公开数据可能滞后、限流或字段变化，界面必须查看实际统计日期和错误状态。
- ETF份额跳变可能来自拆分合并等非申赎因素，疑似调整不可直接作为资金流信号。
- 机构持有人为报告期披露，未知公告日不参与历史已知判断。
- 仅本地使用，系统不是面向公网的多用户金融服务；禁止直接绑定0.0.0.0。
- 上游Resonance许可未明确，本系统独立实现其功能思路而不复制实现，见`THIRD_PARTY_NOTICES.md`。
