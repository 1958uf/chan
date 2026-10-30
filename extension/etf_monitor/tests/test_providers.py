"""提供器固定原始样本、网络模拟、子进程模拟，默认完全离线。"""
from datetime import date, datetime, timedelta
from io import BytesIO
import json
import subprocess
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from etf_monitor.config import Settings
from etf_monitor.models import ETF
from etf_monitor.providers import LiveProvider, ProviderError
from etf_monitor.providers.base import number, parse_date, parse_time
from etf_monitor.providers.live import parse_holders_html
from etf_monitor.providers.transport import AKRunner, BoundedHTTP
from etf_monitor.providers import worker

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 4, 2, 16, tzinfo=TZ)
D1, D2 = date(2026, 4, 1), date(2026, 4, 2)
SH = ETF(code="510300", name="沪深300ETF", group="宽基", exchange="sh")
SZ = ETF(code="159919", name="沪深300ETF", group="宽基", exchange="sz")
SETTINGS = Settings(request_timeout=1, max_retries=2)
SSE_RAW = {"result": [{"SEC_CODE": "510300", "STAT_DATE": "2026-04-01", "TOT_VOL": "125,000.25"}]}


def make_provider(handler, runner=None, settings=SETTINGS, clock=lambda: NOW):
    """功能：创建mock真实门面；输入：HTTP处理器和隔离mock；输出：提供器。"""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LiveProvider(settings, http=BoundedHTTP(settings, client=client, sleeper=lambda _: None),
                        runner=runner, clock=clock)


def excel_bytes(rows):
    """功能：构造固定深市原始工作簿；输入：原始表行；输出：xlsx字节。"""
    output = BytesIO()
    pd.DataFrame(rows, columns=["日期", "基金代码", "基金规模(份)"]).to_excel(output, index=False)
    return output.getvalue()


def test_sse_raw_unit_and_date():
    """功能：沪市万份正确转份；输入：固定原始JSON；输出：单位与源断言。"""
    requests = []
    def handler(request):
        """功能：记录沪市请求；输入：请求；输出：原始JSON。"""
        requests.append(request)
        return httpx.Response(200, json=SSE_RAW)
    provider = make_provider(handler)
    record = provider.shares(D1, D1, [SH])[0]
    assert record.shares == 1250002500
    assert record.trade_date == D1 and record.source == "sse:shares"
    assert requests[0].url.params["STAT_DATE"] == "2026-04-01"
    assert "ETFGM" in requests[0].url.params["sqlId"]
    provider.close()


@pytest.mark.parametrize("payload", [{}, {"result": None}, {"result": [{"SEC_CODE": "510300", "STAT_DATE": "2026-04-02", "TOT_VOL": "1"}]},
    {"result": [{"SEC_CODE": "510300", "STAT_DATE": "2026-04-01", "TOT_VOL": "nan"}]},
    {**SSE_RAW, "pageHelp": {"total": 10001}}])
def test_sse_invalid_or_latest_snapshot_rejected(payload):
    """功能：拒绝错误日期、非法单位和截断；输入：损坏源；输出：ProviderError。"""
    provider = make_provider(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(ProviderError):
        provider.shares(D1, D1, [SH])


def test_szse_history_not_snapshot_and_real_units():
    """功能：深市历史接口及份单位；输入：带千分位xlsx；输出：规范份额。"""
    content = excel_bytes([{"日期": "2026-04-01", "基金代码": "159919", "基金规模(份)": "1,234,567"},
                           {"日期": "2026-04-02", "基金代码": "159919", "基金规模(份)": 1300000},
                           {"日期": None, "基金代码": "说明", "基金规模(份)": None}])
    requests = []
    def handler(request):
        """功能：检查深市参数；输入：请求；输出：固定Excel。"""
        requests.append(request)
        return httpx.Response(200, content=content)
    records = make_provider(handler).shares(D1, D2, [SZ])
    assert [r.shares for r in records] == [1234567, 1300000]
    assert requests[0].url.params["CATALOGID"] == "scsj_fund_jjgm"
    assert requests[0].url.params["jjlb"] == "ETF"
    assert requests[0].url.params["txtStart"] == "2026-04-01"


def test_szse_180_day_chunking():
    """功能：超过六个月自动分段；输入：一年范围；输出：每请求不超180日。"""
    requests = []
    def handler(request):
        """功能：按请求边界返回历史样本；输入：HTTP请求；输出：Excel。"""
        params = request.url.params
        requests.append(params)
        content = excel_bytes([{"日期": params["txtStart"], "基金代码": SZ.code, "基金规模(份)": 1000000}])
        return httpx.Response(200, content=content)
    start = date(2025, 4, 3)
    records = make_provider(handler).shares(start, D2, [SZ])
    assert len(records) == 3
    for params in requests:
        assert (parse_date(params["txtEnd"]) - parse_date(params["txtStart"])).days < 180


@pytest.mark.parametrize("content", [b"not excel", excel_bytes([{"日期": "2026-04-03", "基金代码": "159919", "基金规模(份)": 1}])])
def test_szse_bad_xlsx_and_wrong_date(content):
    """功能：无效Excel/未来快照拒绝；输入：损坏字节；输出：来源错误。"""
    with pytest.raises(ProviderError) as error:
        make_provider(lambda _: httpx.Response(200, content=content)).shares(D1, D1, [SZ])
    assert error.value.source == "szse:shares"


def test_empty_selected_and_duplicate_conflict():
    """功能：有效空可见、重复冲突拒绝；输入：空/冲突样本；输出：明确错误状态。"""
    with pytest.raises(ProviderError) as error:
        make_provider(lambda _: httpx.Response(200, json={"result": []})).shares(D1, D1, [SH])
    assert error.value.status == "empty"
    payload = {"result": SSE_RAW["result"] * 2}
    assert len(make_provider(lambda _: httpx.Response(200, json=payload)).shares(D1, D1, [SH])) == 1
    payload = {"result": SSE_RAW["result"] + [{**SSE_RAW["result"][0], "TOT_VOL": 20}]}
    with pytest.raises(ProviderError, match="冲突"):
        make_provider(lambda _: httpx.Response(200, json=payload)).shares(D1, D1, [SH])


@pytest.mark.parametrize("start,end", [(D2, D1), (D1, D2 + timedelta(days=1)), (date(2020, 1, 1), D2)])
def test_date_validation_no_network(start, end):
    """功能：无效范围不发网络；输入：未来/超量日期；输出：validation异常。"""
    def handler(_):
        """功能：防止意外联网；输入：请求；输出：断言失败。"""
        raise AssertionError("不应请求")
    with pytest.raises(ProviderError) as error:
        make_provider(handler).shares(start, end, [SH])
    assert error.value.source == "validation"


def test_quotes_source_time_units_and_premium():
    """功能：快照保留源时间、手转份、IOPV溢价；输入：固定行情；输出：规范模型。"""
    payload = {"data": {"diff": [{"f12": "510300", "f2": 3, "f5": 100, "f6": 1000,
        "f18": 2.9, "f124": int(NOW.timestamp()), "f297": 20260402, "f441": 2.5}]}}
    result = make_provider(lambda _: httpx.Response(200, json=payload)).quotes([SH])[0]
    assert result.quote_time == NOW and result.volume == 10000
    assert result.premium_pct == pytest.approx(20)
    assert result.amount == 1000
    payload["data"]["diff"][0]["f441"] = "-"
    payload["data"]["diff"][0]["f124"] = int((NOW - timedelta(days=1)).timestamp())
    payload["data"]["diff"][0]["f297"] = 20260401
    payload["data"]["diff"] = {"0": payload["data"]["diff"][0]}
    result = make_provider(lambda _: httpx.Response(200, json=payload)).quotes([SH])[0]
    assert result.premium_pct is None and result.quality == "stale"


@pytest.mark.parametrize("row", [{"f12": "510300", "f2": 0, "f124": int(NOW.timestamp())},
    {"f12": "510300", "f2": 2, "f124": int((NOW + timedelta(minutes=1)).timestamp())},
    {"f12": "510300", "f2": 2, "f124": int(NOW.timestamp()), "f297": 20260401},
    {"f12": "510300", "f2": 2}, {"f12": "159919", "f2": 2, "f124": int(NOW.timestamp())}])
def test_quotes_invalid_future_time_or_partial(row):
    """功能：没有真实时间/缺标的拒绝；输入：损坏行情；输出：ProviderError。"""
    with pytest.raises(ProviderError):
        make_provider(lambda _: httpx.Response(200, json={"data": {"diff": [row]}})).quotes([SH])


class FakeRunner:
    """固定AKShare原始行mock。"""
    def __init__(self, results):
        """功能：配置白名单结果；输入：函数到结果映射；输出：mock。"""
        self.results, self.calls = results, []
    def call(self, function, **kwargs):
        """功能：记录函数参数；输入：名称参数；输出：原始行。"""
        self.calls.append((function, kwargs))
        value = self.results[function]
        return value(kwargs) if callable(value) else value


@pytest.mark.parametrize("interval", ["day", "1m", "5m"])
def test_bars_intervals_unadjusted_volume(interval):
    """功能：日分钟线不复权、手转份；输入：原始AKShare行；输出：准确时间。"""
    row = {"日期": "2026-04-01T00:00:00.000", "时间": "2026-04-01 09:31:00",
           "开盘": 2, "最高": 3, "最低": 1, "收盘": 2.5, "成交量": 100, "成交额": 25000}
    function = "fund_etf_hist_em" if interval == "day" else "fund_etf_hist_min_em"
    runner = FakeRunner({function: [row]})
    result = make_provider(lambda _: None, runner).bars(SH, D1, D2, interval)[0]
    assert result.volume == 10000 and result.close == 2.5
    assert result.time.tzinfo == TZ and result.interval == interval
    assert runner.calls[0][1]["adjust"] == ""
    if interval == "day":
        assert result.time.hour == 15


def test_bars_bad_ohlc_filter_future_and_interval():
    """功能：过滤范围外线并拒绝OHLC；输入：错误线；输出：异常。"""
    row = {"日期": "2026-04-01", "开盘": 2, "最高": 1, "最低": 1, "收盘": 2}
    runner = FakeRunner({"fund_etf_hist_em": [row]})
    provider = make_provider(lambda _: None, runner)
    with pytest.raises(ProviderError, match="OHLC"):
        provider.bars(SH, D1, D2)
    with pytest.raises(ProviderError, match="interval"):
        provider.bars(SH, D1, D2, "15m")
    runner.results["fund_etf_hist_em"] = [{**row, "日期": "2026-03-31"}]
    with pytest.raises(ProviderError) as error:
        provider.bars(SH, D1, D2)
    assert error.value.status == "empty"
    runner.results["fund_etf_hist_em"] = [{**row, "日期": "2026-04-02"}]
    provider.clock = lambda: NOW.replace(hour=10)
    with pytest.raises(ProviderError):
        provider.bars(SH, D1, D2)


def test_nav_unit_and_date_range():
    """功能：单位NAV不累计替代；输入：原始净值样本；输出：正确NAV。"""
    runner = FakeRunner({"fund_open_fund_info_em": [{"净值日期": "2026-04-01T00:00:00.000", "单位净值": 2.345},
                                                  {"净值日期": "2026-03-31", "单位净值": 2}]})
    result = make_provider(lambda _: None, runner).navs(SH, D1, D2)
    assert len(result) == 1 and result[0].nav == 2.345
    assert runner.calls[0][1]["indicator"] == "单位净值走势"
    runner.results["fund_open_fund_info_em"] = [{"净值日期": "2026-04-01", "单位净值": "NaN"}]
    with pytest.raises(ProviderError, match="净值"):
        make_provider(lambda _: None, runner).navs(SH, D1, D2)


def test_calendar_real_dates_and_source_coverage():
    """功能：真实日历不推断工作日；输入：固定日历；输出：仅源交易日。"""
    runner = FakeRunner({"tool_trade_date_hist_sina": [{"trade_date": "2026-04-01"}, {"trade_date": "2026-04-02"}]})
    provider = make_provider(lambda _: None, runner)
    assert provider.calendar(D1, D2) == [D1, D2]
    runner.results["tool_trade_date_hist_sina"] = [{"trade_date": "2026-03-01"}]
    with pytest.raises(ProviderError, match="覆盖"):
        provider.calendar(D1, D2)
    runner.results["tool_trade_date_hist_sina"] = [{"bad": "x"}]
    with pytest.raises(ProviderError, match="格式"):
        provider.calendar(D1, D2)


HOLDER_RAW = '''<h3>报告期：2026-03-31 {published}</h3><table><thead><tr>
<th>序号</th><th>持有人名称</th><th>持有份额(万份)</th><th>占总份额比例</th></tr></thead>
<tbody><tr><td>1</td><td>中央汇金投资有限责任公司</td><td>1,000.5</td><td>15.2%</td></tr></tbody></table>'''


def test_holders_not_portfolio_and_unknown_publication():
    """功能：十大持有人单位转换且未知公告partial；输入：固定HTML；输出：持有人不是股票。"""
    result = parse_holders_html(HOLDER_RAW.format(published=""), SH.code, NOW, "https://example.test")
    assert result[0].holder == "中央汇金投资有限责任公司"
    assert result[0].shares == 10005000 and result[0].ratio_pct == 15.2
    assert result[0].published_on is None and result[0].quality == "partial"
    html = HOLDER_RAW.format(published="公告日期：2026-04-01")
    result = parse_holders_html(html, SH.code, NOW, "https://example.test")
    assert result[0].quality == "valid" and result[0].published_on == D1
    stock_html = "<table><tr><th>股票名称</th><th>持股数量</th></tr><tr><td>贵州茅台</td><td>100</td></tr></table>"
    with pytest.raises(ProviderError) as error:
        parse_holders_html(stock_html, SH.code, NOW, "")
    assert error.value.status == "empty"


@pytest.mark.parametrize("html", [HOLDER_RAW.format(published="").replace("报告期：2026-03-31", ""),
    HOLDER_RAW.format(published="").replace("(万份)", ""),
    HOLDER_RAW.format(published="公告日期：2026-05-01"),
    HOLDER_RAW.format(published="公告日期：2026-03-01"),
    HOLDER_RAW.format(published="").replace("15.2%", "120%"),
    HOLDER_RAW.format(published="").replace("2026-03-31", "2026-05-01")])
def test_holders_bad_metadata(html):
    """功能：报告日期、单位和比例严格；输入：错误HTML；输出：ProviderError。"""
    with pytest.raises(ProviderError):
        parse_holders_html(html, SH.code, NOW, "")


@pytest.mark.parametrize("unit,multiplier", [("(份)", 1), ("（份）", 1), ("(亿份)", 1e8)])
def test_holder_units_without_thead(unit, multiplier):
    """功能：兼容普通首行表头；输入：明确单位HTML；输出：准确份额。"""
    html = HOLDER_RAW.format(published="").replace("(万份)", unit).replace("<thead>", "").replace("</thead>", "")
    assert parse_holders_html(html, SH.code, NOW, "")[0].shares == 1000.5 * multiplier


def test_market_complete_aggregation_no_missing_zero():
    """功能：沪深完整合计且单位元；输入：固定市场表；输出：准确指标。"""
    from test_providers_market import raw_handler
    runner = FakeRunner({"tool_trade_date_hist_sina": [{"trade_date": "2026-04-01"}, {"trade_date": "2026-04-02"}]})
    provider = make_provider(raw_handler(), runner)
    result = provider.market(D1, D2)
    assert len(result) == 4
    assert result[0].value == 15e9 and result[0].metric == "turnover"
    assert result[1].value == 1800 and result[3].value == 2000
    provider = make_provider(raw_handler("empty_sz_margin"), runner)
    with pytest.raises(ProviderError, match="不完整"):
        provider.market(D1, D2)


@pytest.mark.parametrize("codes,expected_calls", [([500, 502, 200], 3), ([429, 200], 2), ([404], 1)])
def test_http_bounded_retries(codes, expected_calls):
    """功能：网络重试有限且仅暂时错误；输入：状态码序列；输出：准确次数。"""
    calls = []
    def handler(request):
        """功能：模拟HTTP状态序列；输入：请求；输出：对应响应。"""
        status = codes[min(len(calls), len(codes) - 1)]
        calls.append(request)
        return httpx.Response(status, json={"ok": True})
    http = BoundedHTTP(SETTINGS, client=httpx.Client(transport=httpx.MockTransport(handler)), sleeper=lambda _: None)
    if codes[-1] == 200:
        assert http.json("test", "https://example.test")["ok"]
    else:
        with pytest.raises(ProviderError) as error:
            http.get("test", "https://example.test")
        assert not error.value.retryable
    assert len(calls) == expected_calls
    assert all(c.extensions["timeout"]["read"] == 1 for c in calls)


def test_http_timeout_invalid_json_and_response_limit():
    """功能：超时次数、非JSON与大响应可诊断；输入：网络mock；输出：来源错误。"""
    calls = []
    def handler(request):
        """功能：模拟持续读取超时；输入：请求；输出：ReadTimeout。"""
        calls.append(request)
        raise httpx.ReadTimeout("timeout")
    http = BoundedHTTP(SETTINGS, client=httpx.Client(transport=httpx.MockTransport(handler)), sleeper=lambda _: None)
    with pytest.raises(ProviderError) as error:
        http.get("test", "https://example.test")
    assert len(calls) == 3 and error.value.retryable
    http = BoundedHTTP(SETTINGS, client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"html"))))
    with pytest.raises(ProviderError, match="JSON"):
        http.json("test", "https://example.test")
    http = BoundedHTTP(SETTINGS, client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (32 * 1024 * 1024 + 1)))))
    with pytest.raises(ProviderError, match="32MiB"):
        http.get("test", "https://example.test")


def test_akrunner_timeout_and_json_protocol():
    """功能：AKShare硬超时与白名单JSON；输入：隔离运行mock；输出：超时错误/准确参数。"""
    calls = []
    def run(args, **kwargs):
        """功能：记录子进程参数；输入：命令参数；输出：成功协议。"""
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "rows": [{"x": 1}]}))
    assert AKRunner(SETTINGS, run=run).call("fund_etf_hist_em", symbol=SH.code) == [{"x": 1}]
    assert calls[0][1]["timeout"] == 1
    assert json.loads(calls[0][1]["input"])["kwargs"]["symbol"] == SH.code
    def timeout(*args, **kwargs):
        """功能：模拟硬超时；输入：参数；输出：TimeoutExpired。"""
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    with pytest.raises(ProviderError, match="已终止"):
        AKRunner(SETTINGS, run=timeout).call("x")
    def os_error(*args, **kwargs):
        """功能：模拟启动失败；输入：参数；输出：OSError。"""
        raise OSError("no executable")
    with pytest.raises(ProviderError, match="启动"):
        AKRunner(SETTINGS, run=os_error).call("x")


@pytest.mark.parametrize("stdout,code", [("not json", 0), ('{"ok":false,"error":"接口缺失"}', 1), ('{"ok":true,"rows":42}', 0)])
def test_akrunner_bad_payload(stdout, code):
    """功能：损坏协议不当空列表；输入：错误stdout；输出：ProviderError。"""
    with pytest.raises(ProviderError):
        AKRunner(SETTINGS, run=lambda *a, **k: SimpleNamespace(stdout=stdout, returncode=code)).call("x")


def test_worker_whitelist_and_output(monkeypatch, capsys):
    """功能：工作进程拒绝任意函数；输入：非法白名单JSON；输出：失败协议。"""
    monkeypatch.setattr(worker.sys, "stdin", __import__("io").StringIO('{"function":"eval"}'))
    assert worker.main() == 1
    assert "不允许" in json.loads(capsys.readouterr().out)["error"]
    fake = SimpleNamespace(tool_trade_date_hist_sina=lambda: pd.DataFrame({"trade_date": [D1], "missing": [float("nan")]}))
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake)
    monkeypatch.setattr(worker.sys, "stdin", __import__("io").StringIO('{"function":"tool_trade_date_hist_sina"}'))
    assert worker.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] and payload["rows"][0]["missing"] is None


@pytest.mark.parametrize("value,optional,expected", [("1,234", False, 1234), (None, True, None), ("NaN", True, None), ("inf", True, None), ("--", True, None)])
def test_numeric_normalization(value, optional, expected):
    """功能：缺失不变零与有限校验；输入：原值；输出：规范值。"""
    assert number(value, optional=optional) == expected
    assert parse_date("20260401") == D1
    assert parse_date(NOW) == D2
    assert parse_date(D1) == D1
    assert parse_time("2026-04-01T01:00:00Z").hour == 9
    assert parse_time(datetime(2026, 4, 1)).tzinfo == TZ


@pytest.mark.parametrize("interval", ["1m", "5m"])
def test_minute_failure_never_replaced_with_daily(interval):
    """功能：分钟故障不得用日线伪造成功；输入：分钟源断连mock；输出：原来源错误，无日线调用。"""
    calls = []

    class BrokenMinuteRunner:
        """仅分钟源断连的隔离调用替身。"""

        def call(self, function, **kwargs):
            """功能：模拟分钟源断连；输入：函数与参数；输出：明确ProviderError。"""
            calls.append(function)
            if function == "fund_etf_hist_min_em":
                raise ProviderError("akshare:fund_etf_hist_min_em", "RemoteDisconnected")
            raise AssertionError("不能用日线替代分钟")

    provider = make_provider(lambda _: None, BrokenMinuteRunner())
    with pytest.raises(ProviderError) as error:
        provider.bars(SZ, D1, D2, interval)
    assert error.value.source == "akshare:fund_etf_hist_min_em"
    assert error.value.status == "error"
    assert calls == ["fund_etf_hist_min_em"]


@pytest.mark.parametrize("value", [None, "NaN", "inf", -1, 0])
def test_required_positive_numbers(value):
    """功能：必填有限正数约束；输入：非法数字；输出：ValueError。"""
    with pytest.raises(ValueError):
        number(value, positive=True)
