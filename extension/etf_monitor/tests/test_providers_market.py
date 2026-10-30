"""市场原始源日期和单位回归：不得把请求日冒认源日。"""
import httpx
import pytest

from etf_monitor.providers import ProviderError
from etf_monitor.providers.live import amount_from_metadata
from test_providers import D1, D2, FakeRunner, make_provider


def raw_handler(mutation=None):
    """功能：提供固定交易所原始包；输入：故障类型；输出：MockTransport处理器。"""
    def handler(request):
        """功能：模拟交易所原始日期/单位字段；输入：请求；输出：JSON响应。"""
        if request.url.path.endswith("queryMargin.do"):
            payload = {"result": [{"opDate": "20260401", "rzye": 1000}, {"opDate": "20260402", "rzye": 1200}]}
            if mutation == "wrong_sh_margin":
                payload["result"][0]["opDate"] = "20260326"
            elif mutation == "duplicate_sh_margin":
                payload["result"].append(payload["result"][0])
            elif mutation == "truncated_sh_margin":
                payload["pageHelp"] = {"total": 5001}
            return httpx.Response(200, json=payload)
        if request.url.host == "query.sse.com.cn":
            actual = request.url.params["SEARCH_DATE"]
            payload = {"result": [{"TRADE_DATE": actual, "PRODUCT_CODE": "17", "TRADE_AMT": 100}]}
            if mutation == "wrong_sh_turnover":
                payload["result"][0]["TRADE_DATE"] = "2026-03-26"
            elif mutation == "multi_sh_turnover":
                payload["result"].append({"TRADE_DATE": "2026-03-26", "PRODUCT_CODE": "01", "TRADE_AMT": 20})
            elif mutation == "duplicate_sh_turnover":
                payload["result"].append(payload["result"][0])
            return httpx.Response(200, json=payload)
        catalog = request.url.params["CATALOGID"]
        margin = catalog == "1837_xxpl"
        actual = request.url.params["txtDate" if margin else "txtQueryDate"]
        payload = [{"metadata": {"catalogid": catalog, "tabkey": "tab1", "subname": actual,
                    "cols": {"jrrzye": "融资余额<br>(亿元)", "cjje": "成交金额<br>(亿元)"}},
                    "data": [{"jrrzye": "0.000008"}] if margin else [{"lbmc": "股票", "cjje": "50"}], "error": None}]
        if mutation == "wrong_sz_margin" and margin or mutation == "wrong_sz_turnover" and not margin:
            payload[0]["metadata"]["subname"] = "2026-03-26"
        elif mutation == "missing_sz_date":
            payload[0]["metadata"].pop("subname")
        elif mutation == "duplicate_sz_tab":
            payload.append(payload[0])
        elif mutation == "multi_sz_margin" and margin:
            payload[0]["data"].append({"jrrzye": 800, "trade_date": "2026-03-26"})
        elif mutation == "duplicate_sz_margin" and margin:
            payload[0]["data"].append(payload[0]["data"][0])
        elif mutation == "empty_sz_margin" and margin:
            payload[0]["data"] = []
        elif mutation == "unknown_unit":
            payload[0]["metadata"]["cols"] = {"jrrzye": "融资余额", "cjje": "成交金额"}
        elif mutation == "wrong_sz_catalog":
            payload[0]["metadata"]["catalogid"] = "snapshot"
        elif mutation == "duplicate_sz_stocks" and not margin:
            payload[0]["data"].append(payload[0]["data"][0])
        return httpx.Response(200, json=payload)
    return handler


@pytest.mark.parametrize("mutation", ["wrong_sh_margin", "duplicate_sh_margin", "truncated_sh_margin",
    "wrong_sh_turnover", "multi_sh_turnover", "duplicate_sh_turnover", "wrong_sz_margin", "wrong_sz_turnover",
    "missing_sz_date", "duplicate_sz_tab", "multi_sz_margin", "duplicate_sz_margin", "empty_sz_margin",
    "unknown_unit", "wrong_sz_catalog", "duplicate_sz_stocks"])
def test_market_wrong_date_multidate_no_relabel(mutation):
    """功能：日期不匹配/多日/单位缺失一律拒绝；输入：坏源包；输出：显式ProviderError。"""
    runner = FakeRunner({"tool_trade_date_hist_sina": [{"trade_date": "2026-04-01"}, {"trade_date": "2026-04-02"}]})
    with pytest.raises(ProviderError):
        make_provider(raw_handler(mutation), runner).market(D1, D2)


@pytest.mark.parametrize("label,multiplier", [("金额(亿元)", 1e8), ("金额（万元）", 1e4), ("金额(元)", 1)])
def test_metadata_unit_not_stale_documentation(label, multiplier):
    """功能：实际列头决定单位；输入：原始列头；输出：正确元金额。"""
    assert amount_from_metadata("12,665.97", label) == 12665.97 * multiplier


def test_live_raw_margin_billion_unit_regression():
    """功能：防止深市亿元被当元；输入：实际列头和融资额；输出：万亿元不是万元。"""
    assert amount_from_metadata("12,665.97", "融资余额<br>(亿元)") == 1266597000000
