"""目录原始JSON/Excel与分类固定样本测试，默认无网络。"""
from datetime import date, datetime
from io import BytesIO

import httpx
import pandas as pd
import pytest

from etf_monitor.config import Settings
from etf_monitor.providers.base import ProviderError, SHANGHAI
from etf_monitor.providers.catalogue import classify_etf, fetch_catalogue
from etf_monitor.providers.live import LiveProvider
from etf_monitor.providers.transport import BoundedHTTP

DAY = date(2026, 4, 2)
NOW = datetime(2026, 4, 2, 17, tzinfo=SHANGHAI)
SSE_RAW = {"result": [{"SEC_CODE": "510300", "SEC_NAME": "沪深300ETF", "STAT_DATE": "2026-04-02", "TOT_VOL": "100"},
                       {"SEC_CODE": "588999", "SEC_NAME": "科创100ETF", "STAT_DATE": "2026-04-02", "TOT_VOL": "10"},
                       {"SEC_CODE": "589999", "SEC_NAME": "未知ETF", "STAT_DATE": "2026-04-02", "TOT_VOL": "20"}],
           "pageHelp": {"total": 3}}
SZSE_ROWS = [{"基金代码": "159919", "基金简称": "嘉实沪深300ETF", "基金类别": "ETF", "上市日期": "2012-05-28", "基金管理人": "嘉实基金", "净值": "故意不是净值"},
             {"基金代码": "159999", "基金简称": "300红利ETF", "基金类别": "ETF"},
             {"基金代码": "160001", "基金简称": "沪深300LOF", "基金类别": "LOF"},
             {"基金代码": "说明", "基金简称": None, "基金类别": None}]


def workbook(rows):
    """功能：构建固定交易所Excel；输入：原始行；输出：xlsx字节。"""
    stream = BytesIO()
    pd.DataFrame(rows).to_excel(stream, index=False)
    return stream.getvalue()


def provider(handler):
    """功能：仅通过有界HTTP模拟目录；输入：响应处理器；输出：LiveProvider。"""
    settings = Settings(request_timeout=1, max_retries=0)
    http = BoundedHTTP(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return LiveProvider(settings, http=http, clock=lambda: NOW)


@pytest.mark.parametrize("code,name,exchange,group", [
    ("510300", "沪深300ETF", "sh", "沪深300"), ("159919", "嘉实沪深300ETF", "sz", "沪深300"),
    ("159915", "创业板ETF", "sz", "创业板"), ("159949", "创业板50ETF", "sz", "创业板50"),
    ("588000", "科创50ETF", "sh", "科创50"), ("510880", "红利ETF", "sh", "上证红利"),
    ("515080", "中证红利ETF", "sh", "中证红利"), ("159338", "A500ETF", "sz", "中证A500"),
])
def test_core_code_exact_confirmed(code, name, exchange, group):
    """功能：已核核心产品确认且红利指数分开；输入：固定身份；输出：精确组。"""
    result = classify_etf(code, name, exchange)
    assert result["classification_status"] == "confirmed"
    assert result["group"] == group
    assert result["tracking_index"]


@pytest.mark.parametrize("name,expected_group", [
    ("沪深300红利ETF", "沪深300·红利"), ("沪深300增强ETF", "沪深300·增强"),
    ("沪深300ESGETF", "沪深300·ESG"), ("创业板50ETF", "创业板50"),
    ("双创50ETF", "科创创业50"), ("科创创业50ETF", "科创创业50"),
    ("科创100ETF", "科创100"), ("科创50ETF", "科创50"),
    ("沪深300价值ETF", "沪深300·价值"), ("上证50等权ETF", "上证50·等权"),
    ("沪深300金融ETF", "沪深300·金融"), ("中证500医药ETF", "中证500·医药"),
])
def test_names_candidates_not_base_index_confirmed(name, expected_group):
    """功能：变体及相近名称不混基础指数；输入：未知代码名称；输出：独立候选。"""
    result = classify_etf("589999", name, "sh")
    assert result["classification_status"] == "candidate"
    assert result["group"] == expected_group
    assert result["tracking_index"] is None
    assert "仅名称" in result["classification_evidence"]


@pytest.mark.parametrize("name", ["沪深3000ETF", "300ETF", "沪深300ETF联接", "普通未知ETF"])
def test_unsafe_substring_and_link_not_confirmed(name):
    """功能：数字子串和联接没有确认依据；输入：不精确名称；输出：不归入沪深300。"""
    result = classify_etf("589999", name, "sh")
    assert result["classification_status"] != "confirmed"
    assert result["group"] != "沪深300"


@pytest.mark.parametrize("name,asset", [
    ("中证500ETF", "宽基"), ("银行ETF", "行业"), ("机器人ETF", "主题"),
    ("300红利ETF", "风格"), ("国债ETF", "债券"), ("黄金ETF", "商品"),
    ("纳斯达克ETF", "跨境"), ("货币ETF", "货币"), ("未知ETF", "未分类"),
])
def test_asset_classes_cover_all_categories(name, asset):
    """功能：九种资产类别独立覆盖；输入：目录名称；输出：保守资产分类。"""
    result = classify_etf("589999", name, "sh")
    assert result["asset_class"] == asset
    assert "机构" not in result["classification_evidence"]


@pytest.mark.parametrize("tracking", ["沪深300指数", "000300", "399300"])
def test_verified_tracking_index_exact_match(tracking):
    """功能：可核指数字段确认非核心代码；输入：精确指数；输出：确认及证据。"""
    result = classify_etf("589999", "某沪深300ETF", "sh", tracking_index=tracking, index_source="sse:index")
    assert result["classification_status"] == "confirmed" and result["group"] == "沪深300"
    assert "sse:index" in result["classification_evidence"]


@pytest.mark.parametrize("tracking,name", [("沪深300红利指数", "沪深300红利ETF"),
    ("沪深300指数", "沪深300增强ETF"), ("中证科创创业50指数", "双创50ETF")])
def test_tracking_variants_not_mixed(tracking, name):
    """功能：跟踪指数变体与基础指数隔离；输入：红利增强双创；输出：不归沪深300确认总体。"""
    result = classify_etf("589999", name, "sh", tracking_index=tracking)
    assert not (result["group"] == "沪深300" and result["classification_status"] == "confirmed")


def test_code_exchange_index_conflicts_require_review():
    """功能：已知代码冲突拒绝自动确认；输入：错误交易所、增强或指数；输出：未分类。"""
    assert classify_etf("510300", "沪深300ETF", "sz")["classification_status"] == "unclassified"
    assert classify_etf("510300", "沪深300增强ETF", "sh")["classification_status"] == "unclassified"
    assert classify_etf("510300", "沪深300ETF", "sh", tracking_index="上证50指数")["classification_status"] == "unclassified"
    assert classify_etf("159915", "创业板50ETF", "sz")["classification_status"] == "unclassified"
    assert classify_etf("588000", "科创100ETF", "sh")["classification_status"] == "unclassified"
    assert classify_etf("589999", "科创50ETF", "sh", tracking_index="中证科创创业50指数")["classification_status"] == "unclassified"


@pytest.mark.parametrize("code,tracking", [("510300", None), ("589999", "沪深300指数")])
def test_kechuang_alias_conflicts_reject_core_or_tracking_confirmation(code, tracking):
    """功能：科创板50别名同样校验身份冲突；输入：300代码或跟踪300；输出：禁止确认为沪深300。"""
    result = classify_etf(code, "科创板50ETF", "sh", tracking_index=tracking)
    assert result["classification_status"] == "unclassified"
    assert result["group"] != "沪深300"
    assert "冲突" in result["classification_evidence"]


@pytest.mark.parametrize("tracking", ["科创板50", "科创板50指数", "科创50指数", "上证科创板50成份指数"])
def test_kechuang_alias_tracking_exact_normalized(tracking):
    """功能：名称与跟踪指数共用科创50别名归一；输入：等价指数字段；输出：精确科创50确认。"""
    result = classify_etf("589999", "科创板50ETF", "sh", tracking_index=tracking)
    assert result["classification_status"] == "confirmed" and result["group"] == "科创50"
    assert result["tracking_index"] == "上证科创板50成份指数"
    assert classify_etf("588000", "科创板50ETF", "sh")["classification_status"] == "confirmed"
    candidate = classify_etf("589999", "科创板50ETF", "sh")
    assert candidate["classification_status"] == "candidate" and candidate["group"] == "科创50"


def test_discover_both_markets_via_bounded_http_no_nav_or_quotes():
    """功能：沪深真实路径与最新来源明确；输入：固定JSON/Excel；输出：目录不依赖净值。"""
    calls = []
    def handle(request):
        """功能：模拟仅允许交易所目录路径；输入：请求；输出：固定原始响应。"""
        calls.append(request)
        return httpx.Response(200, json=SSE_RAW) if "sse.com.cn" in request.url.host else httpx.Response(200, content=workbook(SZSE_ROWS))
    live = provider(handle)
    try:
        etfs = fetch_catalogue(live, DAY)
    finally:
        live.close()
    by_code = {etf.code: etf for etf in etfs}
    assert set(by_code) == {"510300", "588999", "589999", "159919", "159999"}
    assert by_code["510300"].catalogue_source == "sse:catalogue:2026-04-02"
    assert "latest" in by_code["159919"].catalogue_source
    assert by_code["159919"].discovered_at == NOW
    assert by_code["159919"].listed_on == date(2012, 5, 28)
    assert by_code["159919"].manager == "嘉实基金"
    assert by_code["588999"].classification_status == "candidate"
    assert by_code["589999"].classification_status == "unclassified"
    assert calls[0].url.params["STAT_DATE"] == DAY.isoformat()
    assert calls[0].url.params["pageHelp.pageSize"] == "500"
    assert calls[1].url.host == "fund.szse.cn"
    assert calls[1].url.params["CATALOGID"] == "1000_lf"
    assert len(calls) == 2


def test_sse_paginate_and_isolate_exchange_failure():
    """功能：固定分页不截断且分市可隔离；输入：两页及深市故障；输出：沪市501成员。"""
    calls = []
    def handle(request):
        """功能：按页生成固定JSON，其他市场失败；输入：请求；输出：分页响应。"""
        calls.append(request)
        if request.url.host != "query.sse.com.cn":
            return httpx.Response(503)
        page = int(request.url.params["pageHelp.pageNo"])
        rows = [{"SEC_CODE": str(580000 + i), "SEC_NAME": "未知ETF", "STAT_DATE": DAY.isoformat()}
                for i in (range(500) if page == 1 else range(500, 501))]
        return httpx.Response(200, json={"result": rows, "pageHelp": {"total": 501}})
    live = provider(handle)
    try:
        assert len(fetch_catalogue(live, DAY, exchange="sh")) == 501
        assert len(calls) == 2
        with pytest.raises(ProviderError) as exc:
            fetch_catalogue(live, DAY, exchange="sz")
        assert exc.value.source == "szse:catalogue"
    finally:
        live.close()


@pytest.mark.parametrize("payload", [{}, {"result": None}, {"result": [], "pageHelp": {"total": 1}},
    {**SSE_RAW, "pageHelp": {"total": 5001}},
    {"result": [{"SEC_CODE": "510300", "SEC_NAME": "300ETF", "STAT_DATE": "2026-04-01"}]},
    {"result": SSE_RAW["result"] * 2},
    {"result": [{"SEC_CODE": "abc", "SEC_NAME": "ETF", "STAT_DATE": DAY.isoformat()}]},
    {"result": [{"SEC_CODE": "159919", "SEC_NAME": "ETF", "STAT_DATE": DAY.isoformat()}]},
])
def test_sse_malformed_future_wrong_date_duplicate_truncated_rejected(payload):
    """功能：目录坏字段、重复和截断显式失败；输入：固定JSON；输出：来源异常。"""
    live = provider(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderError) as exc:
            fetch_catalogue(live, DAY, "sh")
        assert exc.value.source == "sse:catalogue"
    finally:
        live.close()


@pytest.mark.parametrize("content", [b"not excel", workbook([{"基金代码": "159919"}]),
    workbook([{**SZSE_ROWS[0], "统计日期": "2026-04-03"}]), workbook(SZSE_ROWS[:1] * 2)])
def test_szse_malformed_excel_rejected(content):
    """功能：非法深市列表拒绝成功；输入：损坏或重复Excel；输出：明确ProviderError。"""
    live = provider(lambda _: httpx.Response(200, content=content))
    try:
        with pytest.raises(ProviderError) as exc:
            fetch_catalogue(live, DAY, "sz")
        assert exc.value.source == "szse:catalogue"
    finally:
        live.close()


def test_szse_explicit_source_date_not_request_date():
    """功能：深市最新数据只保留源日期；输入：不同于请求日的统计日；输出：真实日期来源。"""
    live = provider(lambda _: httpx.Response(200, content=workbook([{**SZSE_ROWS[0], "统计日期": "2026-04-01"}])))
    try:
        assert fetch_catalogue(live, DAY, "sz")[0].catalogue_source == "szse:catalogue:2026-04-01"
    finally:
        live.close()


@pytest.mark.parametrize("as_of,exchange", [(date(2026, 4, 3), "sh"), (DAY, "invalid")])
def test_catalogue_validation_without_requests(as_of, exchange):
    """功能：非法输入不发请求；输入：未来日或市场；输出：validation错误。"""
    def handle(_):
        """功能：拒绝意外请求；输入：请求；输出：失败断言。"""
        raise AssertionError("不应请求")
    live = provider(handle)
    try:
        with pytest.raises(ProviderError) as exc:
            fetch_catalogue(live, as_of, exchange)
        assert exc.value.source == "validation"
    finally:
        live.close()
