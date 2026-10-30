# ETF监控系统开发契约

仅允许修改本目录，主工程和三个上游仓库保持不变。函数、类和文档使用中文，函数说明功能、输入、输出。Resonance许可未知，不复制其代码、测试、资产或启动脚本。实现自己的功能，AKShare作为固定版本依赖，原始数据抽查不等于全系统通过。

## 并行修改范围
- 数据代理：backend/etf_monitor/providers/、analysis/，tests/test_providers*、test_analysis*，不得改models.py/config.py。
- 后端代理：storage/、services/、api/、main.py、demo.py及自己测试。
- 前端代理：frontend/及自己的组件与浏览器测试。
- 主代理：models/config、pyproject、config/、scripts/、文档、集成验证与契约协调。

## 后端契约
已有models.py定义ETF、ShareRecord、QuoteRecord、BarRecord、NavRecord、HolderRecord、MarketRecord，统一金额元、份额份、datetime为Asia/Shanghai有时区；quality字段明确，不把空转零。Settings与default_etfs在config.py，mode=live/demo，调度默认禁用。

providers提供Facade类`LiveProvider(settings)`，方法：
- `shares(start: date,end: date,etfs:list[ETF]) -> list[ShareRecord]`
- `quotes(etfs:list[ETF]) -> list[QuoteRecord]`
- `bars(etf:ETF,start:date,end:date,interval='day') -> list[BarRecord]`
- `navs(etf:ETF,start:date,end:date) -> list[NavRecord]`
- `calendar(start:date,end:date) -> list[date]`
- `holders(etf:ETF) -> list[HolderRecord]`
- `market(start:date,end:date) -> list[MarketRecord]`
失败抛ProviderError，不静默为空；有效空明确消息。后台任务捕获后按源标记失败，前端可见。Provider必须有界网络超时，AKShare无界调用需子进程硬超时，Windows可用spawn或subprocess JSON协议。

analysis提供`analyse_etf(etf,shares,quotes,bars,navs,market,as_of)`返回JSON-safe dict；包含latest_shares,share_date,delta_shares,delta_pct,estimated_flow,flow_5d,flow_20d,price,quote_time,premium_pct,quality,score,coverage,label,indicators,history；indicator为name/value/state/explanation，缺证为unknown。调用可传空列表，按日期取不晚于as_of，不NaN、不未来数据。是否当日交易需提供日历边界；计算无I/O。

## REST契约（统一/api，全部JSON）
GET /api/health -> {mode,status,now,sources:[{source,status,last_success,error,...}],scheduler_enabled}
GET /api/dashboard -> {mode,as_of,etfs:[{code,name,group,...analyse_etf}],groups:[{group,flow,...}],market:[],notice:string}
GET /api/etfs -> {items:ETF[]}
POST /api/etfs -> ETF body，创建或更新（严格校验）
GET /api/etfs/{code} -> {etf,analysis,shares:ShareRecord[],quotes:QuoteRecord[],bars:BarRecord[],navs:NavRecord[],holders:HolderRecord[]}
GET /api/history?group=&start=&end= -> {items:[{date,code,group,shares,estimated_flow,...}]}
GET /api/holders?code= -> {items:HolderRecord[]}
POST /api/holders/import -> {records:HolderRecord[]}，人工补充严校验
GET /api/alerts -> {items:[{id,code,kind,severity,title,message,created_at,acknowledged,...}]}
POST /api/alerts/{id}/ack -> {ok:true}
GET /api/tasks -> {items:[{id,kind,status,progress,message,created_at,finished_at,...}]}
POST /api/tasks -> {kind:'refresh'|'backfill'|'holders'|'market'|'calendar',start?:date,end?:date,codes?:string[]} -> task
POST /api/tasks/{id}/cancel -> {ok:true}
GET /api/settings -> 非敏感配置
PUT /api/settings -> 可调阈值/调度，不能设置任意目录/URL/令牌
GET /api/export?format=csv|json&code=&start=&end= -> 下载；限量、CSV公式保护
GET /api/session -> {token:string} 同源仅本地，前端将token放X-ETF-Token，变更请求Origin检测；所有mutation验证token。

API分页默认有界。前端取接口失败必须显示，空库不自动注入演示数据。演示模式由显式mode配置，独立demo数据库固定seed，每页横幅。

测试：临时目录/固定时钟/mock，无联网默认；核心覆盖85%目标，前端类型构建/组件/Playwright；真实验收opt-in并如实写报告。
