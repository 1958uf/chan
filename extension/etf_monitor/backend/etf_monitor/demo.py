"""独立固定演示数据：不调用任何真实数据源。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import ETF, BarRecord, HolderRecord, MarketRecord, NavRecord, QuoteRecord, ShareRecord

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEMO_NOW = datetime(2025, 3, 28, 15, 10, tzinfo=SHANGHAI)
DEMO_DAYS = [date(2025, 2, 17) + timedelta(days=i) for i in range(40)
             if (date(2025, 2, 17) + timedelta(days=i)).weekday() < 5]


class DemoProvider:
    """自己的确定性样本生成器；任何mode=live路径均不得使用。"""

    def __init__(self, settings=None):
        """功能：构造无联网样本源；输入：可选配置；输出：演示源。"""
        self.source = "demo-fixed-v1"

    def base(self):
        """功能：提供样本来源；输入：无；输出：统一采集元数据。"""
        return {"source": self.source, "fetched_at": DEMO_NOW, "quality": "demo"}

    def calendar(self, start, end):
        """功能：过滤固定交易日；输入：起止日期；输出：样本日期列表。"""
        return [day for day in DEMO_DAYS if start <= day <= end]

    def catalogue(self, as_of, exchange=None):
        """功能：生成自有目录覆盖场景；输入：截止日和可选交易所；输出：已确认、候选及未分类样本。"""
        from .config import default_etfs
        items = [item.model_copy(update={"catalogue_source": self.source, "discovered_at": DEMO_NOW,
                    "classification_evidence": "固定演示样本分类，非真实产品目录核对"}) for item in default_etfs()]
        samples = [("510999", "演示同指数扩展产品", "沪深300", "宽基", "confirmed", True),
                   ("159999", "演示待核验主题产品", "待核验主题", "主题", "candidate", True),
                   ("159998", "演示未分类新产品", "未分类", "未分类", "unclassified", True),
                   ("510998", "演示已禁用同指数产品", "沪深300", "宽基", "confirmed", False),
                   # 自有虚构成员用于多资产演示，不把真实名称规则候选自动升级为确认。
                   ("510990", "演示虚构行业产品", "演示行业指数", "行业", "confirmed", True),
                   ("510991", "演示虚构主题产品", "演示主题指数", "主题", "confirmed", True),
                   ("510992", "演示虚构商品产品", "演示商品指数", "商品", "confirmed", True),
                   ("510993", "演示虚构债券产品", "演示债券指数", "债券", "confirmed", True),
                   ("159990", "演示虚构跨境产品", "演示跨境指数", "跨境", "confirmed", True)]
        items.extend(ETF(code=code, name=name, group=group, exchange="sh" if code.startswith("5") else "sz",
                         asset_class=asset, classification_status=status, enabled=enabled,
                         catalogue_source=self.source, discovered_at=DEMO_NOW,
                         tracking_index=group if status == "confirmed" and "演示虚构" in name else None,
                         classification_evidence="自有明确虚构产品及指数的演示确认，非真实产品核验" if "演示虚构" in name else "固定虚构演示目录，不代表真实产品")
                     for code, name, group, asset, status, enabled in samples)
        return [item for item in items if exchange is None or item.exchange == exchange]

    def shares(self, start, end, etfs):
        """功能：生成固定份额；输入：区间与ETF；输出：来源完整的日份额。"""
        result = []
        for etf in etfs:
            factor = int(etf.code[-2:]) + 1
            for index, day in enumerate(DEMO_DAYS):
                if start <= day <= end:
                    stamp = datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=16)
                    result.append(ShareRecord(code=etf.code, trade_date=day,
                                              shares=100_000_000 + factor * 100_000 + index * 700_000,
                                              **{**self.base(), "fetched_at": min(stamp, DEMO_NOW)}))
        return result

    def quotes(self, etfs):
        """功能：生成固定行情；输入：ETF；输出：带真实样本时刻的报价。"""
        return [QuoteRecord(code=etf.code, quote_time=DEMO_NOW, price=3.2, previous_close=3.18,
                            volume=10_000_000, amount=32_000_000, iopv=3.19,
                            premium_pct=(3.2 / 3.19 - 1) * 100, **self.base()) for etf in etfs]

    def bars(self, etf, start, end, interval="day"):
        """功能：生成固定日线或有界分钟样本；输入：ETF、区间、周期；输出：带来源的K线。"""
        if interval in ("1m", "5m"):
            if start > end or (end - start).days + 1 > 7:
                raise ValueError("演示分钟样本仅支持最多7自然日")
            step = 1 if interval == "1m" else 5
            result = []
            for day in self.calendar(start, end):
                for begin in (9 * 60 + 30, 13 * 60):
                    # 自行生成分钟结束时刻，午休不补零，不引入尚未发生的样本。
                    for minute in range(begin + step, begin + 121, step):
                        stamp = datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=minute // 60, minute=minute % 60)
                        if stamp > DEMO_NOW:
                            continue
                        price = 3.0 + (day - DEMO_DAYS[0]).days * .003 + (minute - begin) * .0001
                        result.append(BarRecord(code=etf.code, time=stamp, interval=interval,
                                                open=price, high=price + .002, low=price - .002, close=price + .001,
                                                volume=10000 * step, amount=(price + .001) * 10000 * step,
                                                **{**self.base(), "fetched_at": stamp}))
            return result
        if interval != "day":
            raise ValueError("演示周期只能为day/1m/5m")
        return [BarRecord(code=etf.code, time=datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=15),
                          interval=interval, open=3.0 + i * .005, high=3.04 + i * .005,
                          low=2.98 + i * .005, close=3.02 + i * .005,
                          volume=10_000_000 + i * 10_000, amount=30_000_000 + i * 100_000,
                          **{**self.base(), "fetched_at": min(datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=16), DEMO_NOW)}) for i, day in enumerate(DEMO_DAYS) if start <= day <= end]

    def navs(self, etf, start, end):
        """功能：生成日期对齐净值；输入：ETF与区间；输出：净值列表。"""
        return [NavRecord(code=etf.code, trade_date=day, nav=3.01 + i * .005,
                          **{**self.base(), "fetched_at": min(datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=16), DEMO_NOW)})
                for i, day in enumerate(DEMO_DAYS) if start <= day <= end]

    def holders(self, etf):
        """功能：生成明确虚构持有人；输入：ETF；输出：演示持有人。"""
        return [HolderRecord(code=etf.code, report_date=date(2024, 12, 31), published_on=date(2025, 3, 20),
                             holder="演示机构（非真实持有人）", shares=1_000_000, ratio_pct=1,
                             source_url="", institution_group="演示", **self.base())]

    def market(self, start, end):
        """功能：生成固定市场指标；输入：区间；输出：成交额和融资余额。"""
        return [MarketRecord(trade_date=day, metric=metric, value=value,
                             **{**self.base(), "fetched_at": min(datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=16), DEMO_NOW)})
                for day in DEMO_DAYS if start <= day <= end
                for metric, value in (("turnover", 1_200_000_000_000), ("margin", 1_500_000_000_000))]


def seed_demo(repository, etfs):
    """功能：幂等初始化独立演示库；输入：demo仓储和观察池；输出：是否首次seed。"""
    if repository.path.name != "demo.sqlite":
        raise ValueError("固定演示样本只能写入demo.sqlite")
    provider = DemoProvider()
    if not repository.document("metadata", "demo_catalogue_v2"):
        catalogue = provider.catalogue(DEMO_NOW.date())
        repository.sync_catalogue(catalogue)
        repository.save_records({"shares": provider.shares(DEMO_DAYS[0], DEMO_DAYS[-1], catalogue)}, DEMO_NOW,
                                calendar=DEMO_DAYS, calendar_request=(DEMO_DAYS[0] - timedelta(days=65), DEMO_DAYS[-1], provider.source))
        repository.put_document("metadata", "demo_catalogue_v1", {"seeded_at": DEMO_NOW.isoformat()})
        repository.put_document("metadata", "demo_catalogue_v2", {"seeded_at": DEMO_NOW.isoformat(),
            "notice": "新增自有虚构行业/主题/商品/债券/跨境确认样本，不提升真实候选分类"})
    if repository.document("metadata", "demo_seed_v1"):
        return False
    start, end = DEMO_DAYS[0], DEMO_DAYS[-1]
    batches = {"shares": provider.shares(start, end, etfs), "quotes": provider.quotes(etfs),
               "market": provider.market(start, end), "bars": [], "navs": [], "holders": []}
    for etf in etfs:
        batches["bars"].extend(provider.bars(etf, start, end))
        batches["navs"].extend(provider.navs(etf, start, end))
        batches["holders"].extend(provider.holders(etf))
    repository.save_records(batches, DEMO_NOW, calendar=DEMO_DAYS, calendar_request=(start, end, provider.source))
    repository.put_document("metadata", "demo_seed_v1", {"seeded_at": DEMO_NOW.isoformat(), "source": provider.source})
    return True
