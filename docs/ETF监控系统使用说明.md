# ETF监控系统使用说明

## 一、功能说明

系统位置：`extension/etf_monitor/`。这是独立本地Web应用，不修改既有缠论、股票缓存或旧monitor，不进行自动交易。

页面包含：监控总览、ETF检索/详情、历史流量、持有人报告、告警中心、采集任务、数据源健康、观察池、运行配置。默认观察池覆盖上证50、四只沪深300、科创50、创业板与创业板50、中证500/1000/A500/2000和红利补充池。

- 份额：上交所/深交所官方日份额、日期区间回补、日变化和累计变化。
- 行情：价格/成交额/折溢价、日线与可得分钟数据；不同时间与来源明确区分。
- 流量：`份额变化×同日NAV`的估算金额，缺净值不使用价格替代。
- 披露：公开报告期前十持有人，人工规范导入，保留公告与报告日期。
- 研究指标：逐项说明、覆盖率与评分，不能作为国家队真实身份概率。
- 运维：本地告警、任务进度/取消/错误、源健康、CSV/JSON/PNG导出。

**份额按日披露，盘中行情不是实时申赎。总份额包含所有投资者；公开报告有滞后，无法实时确认国家队账户买卖。**

## 二、安装环境

Python≥3.11、Node/npm。需要联网下载安装包时只写独立系统环境，不改原工程解释器。使用明确解释器和`python -m pip`避免pip指向别处。

```powershell
# 从主工程根目录执行，第一条解释器按自己的环境替换。
python3.11 -m venv extension/etf_monitor/.venv
extension/etf_monitor/.venv/Scripts/python.exe -m pip install -r extension/etf_monitor/requirements.lock.txt
extension/etf_monitor/.venv/Scripts/python.exe -m pip install --no-deps -e extension/etf_monitor

# 前端在 extension/etf_monitor/frontend 目录执行。
npm.cmd ci
npm.cmd run build
```

如果公开PyPI下载不稳定，可显式选择可信HTTPS镜像，例如`--index-url https://pypi.tuna.tsinghua.edu.cn/simple`；不要关闭TLS校验。锁定文件只含包版本，不含远程Git地址或凭证。

## 三、启动与参数说明

```powershell
# 从主工程根目录执行，默认只本地监听。
& ./extension/etf_monitor/scripts/start.ps1 -Mode demo -Port 8765

# 真实模式，先手动采集核查健康。
& ./extension/etf_monitor/scripts/start.ps1 -Mode live -Port 8765

# 在数据源已验证后再显式开启调度。
& ./extension/etf_monitor/scripts/start.ps1 -Mode live -Port 8765 -Schedule
```

浏览器打开`http://127.0.0.1:8765`。Ctrl+C停止本次服务；不删除缓存，不结束占用端口的其他进程。前端构建由后端托管，无需另开Node生产服务。

| 参数/环境变量 | 用途与范围 |
|---|---|
| `-Mode` | demo/live；演示持续显示固定样本标识，真实空库不注入演示 |
| `-Port` | 1024~65535，仅127.0.0.1 |
| `-DataDir` / `ETF_MONITOR_HOME` | 独立运行目录，demo.sqlite与live.sqlite分离 |
| `-Schedule` / `ETF_MONITOR_SCHEDULER=1` | 显式启用日历控制的调度，默认关闭 |
| `ETF_MONITOR_TOKEN` | 可选本地变更API令牌；未设置生成会话令牌，不打印或导出 |
| 行情轮询间隔 | 页面配置，默认30秒、有界范围 |
| 份额告警阈值 | 日份额变化率的研究提醒，不能直接确认买方身份 |
| 回填范围 | 有界日期区间，禁止未来日期，长区间应分批 |

## 四、建议使用流程

1. 首次用demo查看界面，注意固定日期/虚构数据，不用于交易。
2. 切换live后页面可能无数据，这是正确状态；先提交少量核心ETF短日期区间的刷新/回填。
3. 查看任务是否完成、partial/failed/timeout；100%进度不是成功证明。
4. 数据有效后可查看历史流量：默认“事后历史”允许后补数据；API另有`knowledge_mode=point_in_time`与带时区`known_at`选择本地当时已知修订版本，不能将事后曲线当无前视回测。日历无覆盖时指标明确未知。
5. 查看源健康、份额统计日期、行情源时间、NAV日期和缺口；无日历不得推断连续交易日。
5. 数据有效后再扩大观察池、历史范围，开启调度。
6. 持有人按ETF报告期查看，未知公告日不可用于历史已知判断。
7. 导出CSV/JSON或图表PNG进行研究，保留来源与质量标签。

## 五、故障排查

- **行情或分钟接口断连**：公开源可能限流或变更，查看实际来源与错误；备用结果不能冒充主源成功；分钟空缺不以日线填补。
- **份额有数据但累计流量未知**：可能缺完整交易日历、窗口、NAV或连续份额；缺失不等零。
- **历史图为空**：检查日期范围、观察池、历史采集状态以及查询口径，不能凭最新快照伪造历史。
- **持有人失败**：报告格式与分页可能变化；系统应明确失败，可通过规范记录人工补充，不把未获取理解为无机构持仓。
- **端口被占用**：指定其他端口，不能自动结束原有程序。
- **PowerShell脚本执行策略**：按本机策略处理或使用README的明确Python启动方式；系统不改系统执行策略。
- **编辑器提示包未安装**：将IDE解释器切换到本系统`.venv/Scripts/python.exe`；与主工程环境不同是有意隔离。

## 六、测试与验收命令

```powershell
# 从系统目录执行离线后端测试，默认不请求外网。
.venv/Scripts/python.exe -m pytest -m "not live" --cov=etf_monitor --cov-report=term-missing
.venv/Scripts/python.exe -m ruff check backend tests
.venv/Scripts/python.exe -m pip check

# 从frontend目录执行。
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test -- --run
npm.cmd run test:e2e -- contract.spec.ts
```

真实演示后端浏览器验收：先启动demo后端，在frontend目录设置`ETF_REAL_BACKEND=1`、`ETF_FRONTEND_URL=http://127.0.0.1:8765`后执行`npm.cmd run test:e2e -- real-backend.spec.ts`。这是实际API集成但仍是演示市场数据，不等于真实接口验收。

在线契约显式设置`ETF_MONITOR_LIVE_TESTS=1`再运行`pytest tests/test_live_contract.py -m live -v`，只请求少量日期和标的。上游断连应保留失败，不改断言使其假通过。

完整测试数字、修复问题、依赖检查、在线失败/限制及最终状态见可靠性验收报告。运行成功不保证公开数据永续稳定或评分有预测能力。

## 七、许可和安全

AKShare作为固定依赖，MIT声明保留；national-team-position参考趋势展示概念；Resonance许可未确认，不复制其实现。系统默认仅本机同源，变更接口需要令牌与Origin校验，不支持任意URL/命令/文件路径。

不要直接面向互联网部署，也不要把主仓库含凭证的远程地址写入环境锁定文件；记录包版本使用包元信息，不使用可能回显Git凭证的`pip freeze`。
