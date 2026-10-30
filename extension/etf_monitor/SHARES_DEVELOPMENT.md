# 份额主线改造接口契约

## 修改范围

只新系统及docs/discuss，原主工程与三个上游不变。保留旧模型/测试兼容。盘中自动默认关闭，新日更只抓目录/日历/两市份额，不依赖NAV/价格。函数中文功能输入输出。

并行职责：
- 目录与纯份额代理：providers/catalogue.py、analysis/shares.py、tests/test_catalogue*、test_share_stats*。不改models/config（已main扩展ETF字段）。
- 后端代理：storage/repository.py、services/tasks.py、api新增shares_routes.py、必要api/routes兼容和demo目录，自负责测试。不得改providers/catalogue/analysis/shares或前端。
- 前端代理：frontend自己文件及测试，main保留维护real-backend.spec.ts。
- main：共享模型/配置、脚本、文档、集成验证和协调。

## 已扩展ETF字段
asset_class宽基/行业/主题/风格/债券/商品/跨境/货币/未分类（模型字符串），manager/tracking_index可选，classification_status confirmed/candidate/unclassified，classification_evidence，catalogue_source/discovered_at，manual_classification。目录表与观察池表分离，原18精选仍存在。目录sync不得覆盖用户人工分组/禁用，目录全量有分页最多5000；旧watchpool200仍辅助不阻主份额。

## 数据源与纯计算接口
`fetch_catalogue(provider:LiveProvider, as_of:date)->list[ETF]`：用provider.http（有界）读取上交所份额清单/深交所最新列表，宽基代码/可核指数映射confirmed；名称规则candidate未核验，不混指数。返回目录包括latest未分类，来源真实日期，失败应ProviderError逐市可隔离（可支持exchange参数）。
`classify_etf(code,name,exchange,...) -> dict`：字段资产类/group/tracking_index/status/evidence，精准词匹配排除增强/联接/不同变体，未经证实候选不可当完整同指数成员。
`share_overview(etfs,records,calendar,as_of,period='day')->dict`：返回{as_of,items,groups,coverage,notice}；成员同统计日，基线日=period对齐（day前交易日/week上一自然周期末/month上一自然周期末），另delta_5d/20d。quality valid/partial/missing/suspect/demo。必须无依赖NAV价格。数值份、百分比，缺不零。
item:{code,name,group,asset_class,shares,trade_date,delta_shares,delta_pct,delta_5d,delta_20d,increase_streak,decrease_streak,quality,reason,source,classification_status}
group:{group,asset_class,total_shares,delta_shares,delta_pct,increased,decreased,unchanged,missing_count,candidate_count,total_count,available_count,comparable_count,coverage_pct,trade_date,quality}
可比集合同时有首尾记录且无异常，group delta=sum可比成员delta，denom=sum同可比前份额；membership新纳入分开，绝不用不同日latest求和。
`share_history(etfs,records,calendar,start,end,frequency='day')->list[dict]`：每行date/group/total_shares/delta_shares/delta_pct/comparable_count/total_count/coverage_pct/quality，用期末存量不日加总，频率day/week/month。

## API路径
GET /api/shares/overview?as_of=YYYY-MM-DD&period=day|week|month&asset_class=&group= -> overview, mode
GET /api/shares/groups/{group}?as_of=&period= -> {group:summary,items:成员产品,mode,notice}
GET /api/shares/history?start=&end=&frequency=day|week|month&group=&code= -> {items,mode,frequency,notice}
GET /api/catalogue?asset_class=&group=&classification_status=&q=&limit=100&offset=0 -> {items:ETF[],total,coverage:{sources,...}}
POST /api/catalogue/classify -> {code,group,asset_class,tracking_index?,classification_status:'confirmed'} 写manual true，token/Origin保护
POST /api/tasks -> 原kind新增 catalogue|shares，start/end/codes/group/asset_class可选。catalogue sync发现不默认激活全部观察池，shares针对目录confirmed且enabled（全部confirmed/指定group），新主pool不限18watchlist。
GET /api/shares/export?format=csv|json&as_of=&period=&group= -> 下载shares overview，不依赖NAV。
所有mutations仍原session token、安全/分页。main.py app路由include新shares_router由backend负责。

## 页面
首页#/dashboard改份额首页；#/groups/{encodedGroup}类别内全已确认成员，候选明确显示；#/history份额day/week/month，#/catalogue发现与确认；#/etfs ETF检索仍辅助；旧盘中详情保留辅助手动。
支持API缺失状态、group统计日期+分类分母+可比数，演示横幅。日更新按钮只kind shares，目录sync kind catalogue，资产/group筛选，排行增减/百分比/持续。

## 测试
保留221基线（有意原任务默认逻辑改动应更新相应测试而非删除），新分类误匹配、同步人工覆盖、同日可比集合/新ETF/退出/疑似拆分/断档/不足20天/周月末不加存量；纯shares tasks不调用quote/nav/bar/market，分市失败可部分commit。前端组件/真实demo browser，有限源目录与份额核对。
