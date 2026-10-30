"""统一数据契约。

功能：用明确单位、日期、来源和质量状态隔离外部接口。
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Quality = Literal["valid", "partial", "stale", "suspect", "missing", "error", "demo"]


class Record(BaseModel):
    """记录基类：禁止非有限数值，保留来源和采集时间。"""
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    source: str
    fetched_at: datetime
    quality: Quality = "valid"

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_timezone(cls, value: datetime) -> datetime:
        """功能：拒绝无时区采集时间；输入：时间；输出：原有时区时间。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("采集时间必须带时区")
        return value


class ETF(BaseModel):
    """观察标的：代码保持六位文本，分类不是机构身份判断。"""
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1, max_length=80)
    group: str = Field(min_length=1, max_length=40)
    exchange: Literal["sh", "sz"]
    enabled: bool = True
    listed_on: date | None = None
    delisted_on: date | None = None
    tags: list[str] = Field(default_factory=list)
    asset_class: str = Field(default="宽基", max_length=30)
    manager: str | None = Field(default=None, max_length=100)
    tracking_index: str | None = Field(default=None, max_length=100)
    classification_status: Literal["confirmed", "candidate", "unclassified"] = "confirmed"
    classification_evidence: str = Field(default="精选观察池，待核对完整指数产品范围", max_length=300)
    catalogue_source: str | None = None
    discovered_at: datetime | None = None
    manual_classification: bool = False

    @model_validator(mode="after")
    def validate_listing_dates(self):
        """功能：校验上市退出日期；输入：日期字段；输出：合法成员生命周期。"""
        if self.listed_on and self.delisted_on and self.delisted_on <= self.listed_on:
            raise ValueError("退出日期必须晚于上市日期")
        return self


class ShareRecord(Record):
    """交易所日份额：shares单位为份，不是实时申赎。"""
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    shares: float = Field(ge=0)


class QuoteRecord(Record):
    """行情快照：金额单位元，数量单位份；源时间不可伪造。"""
    code: str = Field(pattern=r"^\d{6}$")
    quote_time: datetime
    price: float = Field(gt=0)
    previous_close: float | None = Field(default=None, gt=0)
    volume: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)
    iopv: float | None = Field(default=None, gt=0)
    premium_pct: float | None = None

    @field_validator("quote_time")
    @classmethod
    def validate_quote_timezone(cls, value: datetime) -> datetime:
        """功能：要求源行情时间带时区；输入：源时间；输出：校验时间。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("行情时间必须带时区")
        return value


class BarRecord(Record):
    """日线/分钟线：时间带时区，价格不复权以便核对份额。"""
    code: str = Field(pattern=r"^\d{6}$")
    time: datetime
    interval: Literal["day", "1m", "5m"] = "day"
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)

    @field_validator("time")
    @classmethod
    def validate_bar_timezone(cls, value: datetime) -> datetime:
        """功能：要求K线时间带时区；输入：时间；输出：校验时间。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("K线时间必须带时区")
        return value

    @model_validator(mode="after")
    def validate_ohlc(self):
        """功能：校验价格区间；输入：OHLC；输出：合法K线。"""
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("K线高低价区间非法")
        return self


class NavRecord(Record):
    """基金单位净值：净值日期必须与份额变化对齐。"""
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    nav: float = Field(gt=0)


class HolderRecord(Record):
    """报告期持有人：公告日未知时不得用于历史已知判断。"""
    code: str = Field(pattern=r"^\d{6}$")
    report_date: date
    published_on: date | None = None
    holder: str = Field(min_length=1, max_length=200)
    shares: float | None = Field(default=None, ge=0)
    ratio_pct: float | None = Field(default=None, ge=0, le=100)
    source_url: str = ""
    institution_group: str | None = None


class MarketRecord(Record):
    """市场日指标：市场成交额/融资余额，金额单位元。"""
    trade_date: date
    metric: Literal["turnover", "margin"]
    value: float = Field(ge=0)


class FetchResult(BaseModel):
    """采集摘要：部分成功与完整成功分别表示，不吞掉错误。"""
    source: str
    status: Literal["ok", "partial", "error", "empty"]
    count: int = 0
    message: str = ""
    requested_start: date | None = None
    requested_end: date | None = None
    actual_dates: list[date] = Field(default_factory=list)
