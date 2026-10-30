"""真实数据门面。

独立实现规范化与校验；交易所字段名称和接口用途参考MIT许可AKShare文档，
AKShare仅作为隔离依赖调用，没有复制大库或Resonance代码。所有单位在边界转换。
"""
from datetime import date, datetime, time, timedelta
from io import BytesIO
from decimal import Decimal
import re
from zipfile import BadZipFile

from ..models import ShareRecord, QuoteRecord, BarRecord, NavRecord, HolderRecord, MarketRecord
from .base import ProviderError, SHANGHAI, number, parse_date, parse_time, require_rows
from .transport import AKRunner, BoundedHTTP

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.sse.com.cn/"}


class LiveProvider:
    """真实采集门面，保留交易日期、来源和质量，任何失败均显式异常。"""

    def __init__(self, settings, *, http=None, runner=None, clock=None):
        """功能：注入设置及测试替身；输入：Settings；输出：真实采集实例。"""
        self.settings = settings
        self.http = http or BoundedHTTP(settings)
        self.runner = runner or AKRunner(settings)
        self.clock = clock or (lambda: datetime.now(SHANGHAI))

    def _range(self, start, end):
        """功能：限制历史采集范围；输入：起止日期；输出：无，非法范围抛异常。"""
        if start > end or (end - start).days + 1 > self.settings.max_backfill_days:
            raise ProviderError("validation", "日期顺序错误或超过max_backfill_days")
        if end > self.clock().astimezone(SHANGHAI).date():
            raise ProviderError("validation", "禁止请求未来日期")

    def _meta(self, source, quality="valid"):
        """功能：生成来源元数据；输入：来源和质量；输出：模型公共字段。"""
        return {"source": source, "fetched_at": self.clock(), "quality": quality}

    def shares(self, start: date, end: date, etfs) -> list[ShareRecord]:
        """功能：采集沪深历史日份额；输入：日期范围、ETF列表；输出：份单位记录。"""
        self._range(start, end)
        selected = {e.code: e for e in etfs if e.enabled}
        records = []
        if any(e.exchange == "sh" for e in selected.values()):
            current = start
            while current <= end:
                payload = self.http.json("sse:shares", "https://query.sse.com.cn/commonQuery.do", params={
                    "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
                    "STAT_DATE": current.isoformat(), "isPagination": "true",
                    "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1",
                }, headers=HEADERS)
                if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
                    raise ProviderError("sse:shares", "缺少result数组")
                try:
                    total = int(payload.get("pageHelp", {}).get("total", len(payload["result"])))
                    if total > len(payload["result"]):
                        raise ProviderError("sse:shares", "交易所返回被截断，不能作为完整日份额")
                    for row in payload["result"]:
                        code = str(row.get("SEC_CODE", "")).zfill(6)
                        if code not in selected or selected[code].exchange != "sh":
                            continue
                        actual = parse_date(row["STAT_DATE"])
                        if actual != current:
                            raise ValueError("统计日期与请求不符，拒绝最新快照冒充历史")
                        raw_shares = number(row["TOT_VOL"])
                        records.append(ShareRecord(code=code, trade_date=actual,
                            shares=float(Decimal(str(raw_shares)) * 10000), **self._meta("sse:shares")))
                except (ValueError, KeyError, TypeError) as exc:
                    raise ProviderError("sse:shares", f"日份额格式错误: {exc}") from exc
                current += timedelta(days=1)
        if any(e.exchange == "sz" for e in selected.values()):
            current = start
            # 深交所单次最多六个月，使用180天闭区间避免跨月边界歧义。
            while current <= end:
                stop = min(current + timedelta(days=179), end)
                response = self.http.get("szse:shares", "https://www.szse.cn/api/report/ShowReport", params={
                    "SHOWTYPE": "xlsx", "CATALOGID": "scsj_fund_jjgm", "TABKEY": "tab1",
                    "txtStart": current.isoformat(), "txtEnd": stop.isoformat(), "jjlb": "ETF",
                }, headers={**HEADERS, "Referer": "https://www.szse.cn/market/fund/volume/etf/index.html"})
                try:
                    import pandas as pd
                    frame = pd.read_excel(BytesIO(response.content), dtype={"基金代码": str}, engine="openpyxl")
                    required = {"日期", "基金代码", "基金规模(份)"}
                    if not required.issubset(frame.columns):
                        raise ValueError("深市日频表字段缺失")
                    for row in frame.dropna(how="all").to_dict("records"):
                        raw = str(row["基金代码"]).strip()
                        if not re.fullmatch(r"\d{1,6}(?:\.0)?", raw):
                            continue  # 交易所表尾说明不是记录。
                        code = str(int(float(raw))).zfill(6)
                        if code not in selected or selected[code].exchange != "sz":
                            continue
                        actual = parse_date(row["日期"])
                        if not current <= actual <= stop:
                            raise ValueError("深市历史返回日期不匹配")
                        records.append(ShareRecord(code=code, trade_date=actual,
                            shares=number(row["基金规模(份)"]), **self._meta("szse:shares")))
                except (ValueError, KeyError, TypeError, ImportError, BadZipFile, OSError) as exc:
                    raise ProviderError("szse:shares", f"日份额Excel格式错误: {exc}") from exc
                current = stop + timedelta(days=1)
        require_rows(records, "exchange:shares")
        if set(selected) - {record.code for record in records}:
            raise ProviderError("exchange:shares", "部分ETF在指定范围无份额记录，不能标记完整成功")
        return self._deduplicate(records, "trade_date", "exchange:shares")

    def _deduplicate(self, records, field, source):
        """功能：拒绝同日冲突并消除重复；输入：记录、时间字段；输出：有序记录。"""
        result = {}
        for record in records:
            key = (record.code, getattr(record, field))
            previous = result.get(key)
            if previous and previous.model_dump(exclude={"fetched_at"}) != record.model_dump(exclude={"fetched_at"}):
                raise ProviderError(source, "同一标的同一日期出现冲突记录")
            result[key] = record
        return [result[key] for key in sorted(result)]

    def quotes(self, etfs) -> list[QuoteRecord]:
        """功能：优先东财、失败时腾讯HTTPS备用；输入：观察池；输出：带真实源标识快照。"""
        try:
            return self._quotes_primary(etfs)
        except ProviderError as primary:
            try:
                return self._quotes_backup(etfs)
            except ProviderError as backup:
                raise ProviderError("quotes", f"主源失败[{primary}]；备用失败[{backup}]", retryable=True) from backup

    def _quotes_backup(self, etfs) -> list[QuoteRecord]:
        """功能：腾讯HTTPS备用，缺IOPV不编造；输入：观察池；输出：部分字段快照。"""
        active = [etf for etf in etfs if etf.enabled]
        symbols = ",".join(etf.exchange + etf.code for etf in active)
        response = self.http.get("tencent:quotes", "https://qt.gtimg.cn/q=" + symbols)
        try:
            text = response.content.decode("gb18030", errors="strict")
        except UnicodeError as exc:
            raise ProviderError("tencent:quotes", "备用行情编码错误") from exc
        wanted = {etf.code for etf in active}
        rows = []
        try:
            for match in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]+)"', text):
                code, values = match.group(1), match.group(2).split("~")
                if code not in wanted:
                    continue
                if len(values) < 38 or values[2] != code:
                    raise ValueError("腾讯行情字段不完整或身份不匹配")
                stamp = datetime.strptime(values[30], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
                if stamp > self.clock() + timedelta(seconds=5):
                    raise ValueError("腾讯源时间在未来")
                # 备用源没有已核验IOPV，quality=partial，不能隐藏主源故障。
                rows.append(QuoteRecord(code=code, quote_time=stamp,
                    price=number(values[3], positive=True), previous_close=number(values[4], positive=True),
                    volume=number(values[6]) * 100, amount=number(values[37]) * 10000,
                    **self._meta("tencent:quotes:backup", "partial")))
            if {row.code for row in rows} != wanted:
                raise ValueError("腾讯备用返回标的缺失")
        except (ValueError, IndexError, UnicodeError) as exc:
            raise ProviderError("tencent:quotes", f"备用行情格式错误: {exc}") from exc
        return require_rows(rows, "tencent:quotes")

    def _quotes_primary(self, etfs) -> list[QuoteRecord]:
        """功能：读取带源时间行情；输入：ETF列表；输出：快照，成交量手转份。"""
        active = [e for e in etfs if e.enabled]
        records = []
        for offset in range(0, len(active), 100):
            batch = active[offset:offset + 100]
            expected = {e.code for e in batch}
            payload = self.http.json("eastmoney:quotes", "https://push2.eastmoney.com/api/qt/ulist.np/get", params={
                "secids": ",".join(f"{1 if e.exchange == 'sh' else 0}.{e.code}" for e in batch),
                "fltt": "2", "fields": "f2,f5,f6,f12,f18,f124,f297,f441",
            })
            try:
                rows = payload["data"]["diff"]
                if isinstance(rows, dict):
                    rows = list(rows.values())
                known_codes = {str(r.get("f12", "")) for r in rows}
                missing_codes = expected - known_codes
                if missing_codes:
                    raise ProviderError("eastmoney:quotes", "请求标的部分缺失，不能标记完整成功")
                for row in rows:
                    code = str(row["f12"])
                    if code not in expected:
                        continue
                    stamp = datetime.fromtimestamp(number(row["f124"], positive=True), SHANGHAI)
                    if stamp > self.clock() + timedelta(seconds=5):
                        raise ValueError("行情源时间在未来")
                    source_day = row.get("f297")
                    if source_day not in (None, "-", "") and parse_date(source_day) != stamp.date():
                        raise ValueError("行情日期与源时间冲突")
                    volume = number(row.get("f5"), optional=True)
                    iopv = number(row.get("f441"), positive=True, optional=True)
                    price = number(row["f2"], positive=True)
                    quality = "stale" if stamp.date() < self.clock().date() else "valid"
                    records.append(QuoteRecord(code=code, quote_time=stamp, price=price,
                        previous_close=number(row.get("f18"), positive=True, optional=True),
                        volume=None if volume is None else volume * 100,
                        amount=number(row.get("f6"), optional=True), iopv=iopv,
                        premium_pct=None if iopv is None else (price / iopv - 1) * 100,
                        **self._meta("eastmoney:quotes", quality)))
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderError("eastmoney:quotes", f"行情格式错误: {exc}") from exc
            if {r.code for r in records}.intersection(expected) != expected:
                raise ProviderError("eastmoney:quotes", "请求标的部分缺失，不能标记完整成功")
        return require_rows(records, "eastmoney:quotes")

    def bars(self, etf, start, end, interval="day") -> list[BarRecord]:
        """功能：读取不复权日/分钟线；输入：ETF、日期及day/1m/5m；输出：BarRecord。"""
        self._range(start, end)
        if interval not in {"day", "1m", "5m"}:
            raise ProviderError("validation", "interval只能为day/1m/5m")
        if interval == "day":
            rows = self.runner.call("fund_etf_hist_em", symbol=etf.code, period="daily", adjust="",
                start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
        else:
            rows = self.runner.call("fund_etf_hist_min_em", symbol=etf.code, period=interval[:-1], adjust="",
                start_date=f"{start} 09:00:00", end_date=f"{end} 15:30:00")
        records = []
        try:
            for row in rows:
                stamp = (datetime.combine(parse_date(row["日期"]), time(15), SHANGHAI)
                         if interval == "day" else parse_time(row["时间"]))
                if not start <= stamp.date() <= end:
                    continue
                if stamp > self.clock():
                    continue
                prices = {name: number(row[label], positive=True) for name, label in
                          (("open", "开盘"), ("high", "最高"), ("low", "最低"), ("close", "收盘"))}
                if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
                    raise ValueError("OHLC价格关系不合法")
                volume = number(row.get("成交量"), optional=True)
                records.append(BarRecord(code=etf.code, time=stamp, interval=interval, **prices,
                    volume=None if volume is None else volume * 100,
                    amount=number(row.get("成交额"), optional=True), **self._meta("eastmoney:bars")))
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("eastmoney:bars", f"K线格式错误: {exc}") from exc
        return self._deduplicate(require_rows(records, "eastmoney:bars"), "time", "eastmoney:bars")

    def navs(self, etf, start, end) -> list[NavRecord]:
        """功能：采集单位净值而非累计净值；输入：ETF及日期；输出：同日NAV记录。"""
        self._range(start, end)
        rows = self.runner.call("fund_open_fund_info_em", symbol=etf.code, indicator="单位净值走势")
        records = []
        try:
            for row in rows:
                actual = parse_date(row["净值日期"])
                if start <= actual <= end:
                    records.append(NavRecord(code=etf.code, trade_date=actual,
                        nav=number(row["单位净值"], positive=True), **self._meta("eastmoney:nav")))
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("eastmoney:nav", f"净值格式错误: {exc}") from exc
        return self._deduplicate(require_rows(records, "eastmoney:nav"), "trade_date", "eastmoney:nav")

    def calendar(self, start, end) -> list[date]:
        """功能：采集真实交易日历；输入：日期边界；输出：交易日列表，拒绝越过源覆盖期。"""
        self._range(start, end)
        rows = self.runner.call("tool_trade_date_hist_sina")
        try:
            days = sorted({parse_date(row["trade_date"]) for row in rows})
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("sina:calendar", "交易日历格式错误") from exc
        if not days or end > days[-1] and not (days[-1].weekday() == 4 and (end - days[-1]).days <= 2):
            raise ProviderError("sina:calendar", "交易日历未覆盖请求结束日期，不能推断休市")
        return require_rows([day for day in days if start <= day <= end], "sina:calendar")

    def holders(self, etf) -> list[HolderRecord]:
        """功能：从真实年/中报提取上市基金前十持有人；输入：ETF；输出：带已核验公告日期记录。"""
        payload = self.http.json("eastmoney:holders", "https://api.fund.eastmoney.com/f10/JJGG", params={
            "fundcode": etf.code, "pageIndex": 1, "pageSize": 20, "type": 3,
        }, headers={**HEADERS, "Referer": "https://fundf10.eastmoney.com/"})
        try:
            if payload.get("ErrCode") != 0 or not isinstance(payload.get("Data"), list):
                raise ValueError("公告列表格式错误")
            candidates = [r for r in payload["Data"] if r.get("FUNDCODE") == etf.code
                          and re.search(r"(?:年度报告|中期报告|半年度报告)", r.get("TITLE", ""))
                          and "摘要" not in r.get("TITLE", "")
                          and parse_date(r["PUBLISHDATE"]) <= self.clock().date()]
            if not candidates:
                raise ProviderError("eastmoney:holders", "最近20份定期报告没有已公告年/中报", status="empty")
            last_error = None
            for announcement in sorted(candidates, key=lambda r: parse_date(r["PUBLISHDATE"]), reverse=True)[:3]:
                try:
                    return self._holder_report(etf, announcement)
                except ProviderError as exc:
                    last_error = exc
            raise last_error or ProviderError("eastmoney:holders", "没有可解析前十持有人的定期报告")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("eastmoney:holders", f"持有人公告格式错误: {exc}") from exc

    def _holder_report(self, etf, announcement):
        """功能：读取一份年/中报持有人章节；输入：已筛选公告；输出：前十持有人或明确错误。"""
        try:
            art_code = announcement["ID"]
            if not re.fullmatch(r"AN\d{18}", art_code):
                raise ValueError("公告ID格式不合法")
            content_url = "https://np-cnotice-stock.eastmoney.com/api/content/ann"

            def page(index):
                """功能：获取单个有界公告页并核验基金身份；输入：页号；输出：公告数据。"""
                result = self.http.json("eastmoney:holders", content_url,
                    params={"art_code": art_code, "client_source": "web", "page_index": index})
                data = result["data"]
                if result.get("success") not in (True, 1) or data.get("art_code") != art_code:
                    raise ValueError("公告正文身份不匹配")
                if etf.code not in {str(r.get("stock")) for r in data.get("security", [])}:
                    raise ValueError("公告不是所请求的ETF")
                return data

            first = page(1)
            if "期末上市基金前十名持有人" not in first["notice_content"]:
                raise ProviderError("eastmoney:holders", "本定期报告目录没有前十持有人，尝试前一期报告", status="empty")
            published_on = parse_date(first["notice_date"])
            if published_on != parse_date(announcement["PUBLISHDATE"]):
                raise ValueError("公告日来源冲突")
            count = int(first["page_size"])
            if not 1 <= count <= 60:
                raise ValueError("公告正文分页超过60页安全上限")
            # 持有人章节位于财务/组合章节之后。倒序读取末段，最多12页，避免百页报告无界采集。
            collected = {1: first["notice_content"]}
            last_error = None
            for index in range(count, max(1, count - 12), -1):
                collected[index] = page(index)["notice_content"]
                merged = first["notice_content"] + "\n" + "\n".join(collected[i] for i in sorted(collected) if i != 1)
                try:
                    return parse_holders_text(merged, etf.code, self.clock(), published_on,
                        f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf")
                except ProviderError as exc:
                    last_error = exc
            if count == 1:
                return parse_holders_text(first["notice_content"], etf.code, self.clock(), published_on,
                    f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf")
            raise last_error or ProviderError("eastmoney:holders", "有界公告页未找到完整前十持有人")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("eastmoney:holders", f"持有人公告格式错误: {exc}") from exc

    def market(self, start, end) -> list[MarketRecord]:
        """功能：采集沪深股票成交额与融资余额；输入：日期；输出：双方完整相加的元指标。"""
        self._range(start, end)
        days = self.calendar(start, end)
        result = []
        payload = self.http.json("sse:margin", "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do",
            params={"beginDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"),
                    "isPagination": "true", "pageHelp.pageSize": "5000", "pageHelp.pageNo": "1",
                    "tabType": "", "stockCode": ""}, headers=HEADERS)
        try:
            margin_rows = payload["result"]
            if not isinstance(margin_rows, list):
                raise ValueError("沪市融资result不是数组")
            total = int(payload.get("pageHelp", {}).get("total", len(margin_rows)))
            if total > len(margin_rows):
                raise ValueError("沪市融资响应截断")
            sh_margin = {}
            for row in margin_rows:
                actual = parse_date(row["opDate"])
                if not start <= actual <= end or actual in sh_margin:
                    raise ValueError("沪市融资源日期范围错误或重复")
                sh_margin[actual] = number(row["rzye"])
            for day in days:
                sh_turnover = self.http.json("sse:turnover", "https://query.sse.com.cn/commonQuery.do",
                    params={"sqlId": "COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C", "PRODUCT_CODE": "01,02,03,11,17",
                            "type": "inParams", "SEARCH_DATE": day.isoformat()}, headers=HEADERS)
                rows = sh_turnover["result"]
                if not isinstance(rows, list) or not rows or any(parse_date(r["TRADE_DATE"]) != day for r in rows):
                    raise ValueError("沪市成交源日期错误/多日期")
                stocks = [r for r in rows if str(r.get("PRODUCT_CODE")) == "17"]
                if len(stocks) != 1:
                    raise ValueError("沪市股票成交汇总不唯一")
                sh_value = float(Decimal(str(number(stocks[0]["TRADE_AMT"]))) * 100000000)
                sz_turnover = self._sz_market_table("1803_sczm", day, "txtQueryDate")
                stock_rows = [r for r in sz_turnover["data"] if str(r.get("lbmc", "")).strip() == "股票"]
                if len(stock_rows) != 1:
                    raise ValueError("深市股票成交汇总不唯一")
                sz_value = amount_from_metadata(stock_rows[0]["cjje"], sz_turnover["metadata"]["cols"]["cjje"])
                sz_margin = self._sz_market_table("1837_xxpl", day, "txtDate")
                if len(sz_margin["data"]) != 1:
                    raise ValueError("深市融资汇总不唯一，不能取第一条")
                margin = amount_from_metadata(sz_margin["data"][0]["jrrzye"], sz_margin["metadata"]["cols"]["jrrzye"])
                result.append(MarketRecord(trade_date=day, metric="turnover", value=sh_value + sz_value,
                    **self._meta("sse+szse:turnover")))
                result.append(MarketRecord(trade_date=day, metric="margin",
                    value=sh_margin[day] + margin, **self._meta("sse+szse:margin")))
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise ProviderError("sse+szse:market", f"市场源日期/单位不完整或错误: {exc}") from exc
        return require_rows(result, "sse+szse:market")

    def _sz_market_table(self, catalog, day, date_parameter):
        """功能：核验深市原始报告元信息日期；输入：固定报告ID、日期；输出：唯一tab1报告表。"""
        payload = self.http.json("szse:market", "https://www.szse.cn/api/report/ShowReport/data",
            params={"SHOWTYPE": "JSON", "CATALOGID": catalog, date_parameter: day.isoformat()},
            headers={**HEADERS, "Referer": "https://www.szse.cn/"})
        if not isinstance(payload, list):
            raise ValueError("深市市场报告不是数组")
        tables = [table for table in payload if table.get("metadata", {}).get("tabkey") == "tab1"]
        if len(tables) != 1:
            raise ValueError("深市tab1报告不唯一")
        table = tables[0]
        metadata = table["metadata"]
        if metadata.get("catalogid") != catalog or parse_date(metadata["subname"]) != day:
            raise ValueError("深市源统计日期与请求不符，拒绝旧报告冒充今日")
        if table.get("error") or not isinstance(table.get("data"), list):
            raise ValueError("深市报告错误或无data数组")
        for row in table["data"]:
            for key in ("日期", "trade_date", "TRADE_DATE", "opDate"):
                if key in row and parse_date(row[key]) != day:
                    raise ValueError("深市行日期与元信息冲突/多日期")
        return table

    def close(self):
        """功能：关闭网络连接；输入：无；输出：无。"""
        self.http.close()


def classify_institution(name):
    """功能：按公开名称归类而非验证账户身份；输入：持有人名；输出：标签或None。"""
    for label, keywords in (("汇金资管", ("中央汇金资产管理", "汇金资产管理")),
                            ("中央汇金", ("中央汇金投资",)),
                            ("社保/养老", ("社保基金", "社会保障基金", "基本养老保险")),
                            ("证金", ("中国证券金融",))):
        if any(keyword in name for keyword in keywords):
            return label
    return None


def amount_from_metadata(value, label):
    """功能：按原始列头明确金额单位转元；输入：值与列头；输出：元金额，未知单位拒绝。"""
    if "亿元" in label:
        multiplier = 100000000
    elif "万元" in label:
        multiplier = 10000
    elif re.search(r"[（(]元[）)]", label):
        multiplier = 1
    else:
        raise ValueError("金额单位未知，不沿用AKShare历史文档假定元")
    return float(Decimal(str(number(value))) * multiplier)


def parse_holders_text(text, code, fetched_at, published_on, source_url):
    """功能：解析公告前十持有人原始文本；输入：分页合并正文和公告元数据；输出：准确份额记录。

    表格行列来自公告PDF文本，按原始空格列边界拼接跨行名称；严格要求序号1~10及完整章节。
    联接基金常单列第11项，不计入前十；绝不解析股票组合表或仅有机构/个人比例的结构表。
    """
    report = re.search(r"本报告期自[\s\S]{0,100}?至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not report:
        raise ProviderError("eastmoney:holders", "公告未找到明确报告期结束日期")
    report_date = date(*(int(x) for x in report.groups()))
    if published_on is None or not report_date <= published_on <= fetched_at.date():
        raise ProviderError("eastmoney:holders", "报告期与公告日不合法")
    headings = list(re.finditer(r"(?m)^\s*\d+\.\d+\s+期末上市基金前十名持有人\s*$", text))
    if not headings:
        raise ProviderError("eastmoney:holders", "正文无前十持有人章节（目录不是数据）", status="empty")
    section = text[headings[-1].end():]
    boundary = re.search(r"(?m)^\s*(?:注[：:]|\d+\.\d+\s+期末基金管理人)", section)
    if not boundary:
        raise ProviderError("eastmoney:holders", "前十持有人章节不完整")
    section = section[:boundary.start()]
    if not re.search(r"持有份额[（(]份[）)]", section):
        raise ProviderError("eastmoney:holders", "公告份额单位不是明确的份")
    lines = section.splitlines()
    matches = []
    pattern = re.compile(r"^(\s*)(\d{1,2})\s+(.+?)\s{2,}([\d,]+\.\d+)\s{2,}([\d.]+)\s*%?\s*$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            matches.append((index, match))
    if [int(m.group(2)) for _, m in matches[:10]] != list(range(1, 11)):
        raise ProviderError("eastmoney:holders", "持有人序号1~10不完整")
    result = []
    # 名称列通常窄于份额列，保留跨行位置；遇新条目名称在序号行前开始时按缩进识别。
    start_column = max(m.start(3) for _, m in matches)
    for position, (index, match) in enumerate(matches[:10]):
        stop = matches[position + 1][0] if position + 1 < len(matches) else len(lines)
        name = match.group(3).strip()
        continuation = []
        for line in lines[index + 1:stop]:
            if not line.strip() or not re.search(r"[一-鿿A-Za-z]", line):
                continue
            indent = len(line) - len(line.lstrip())
            if indent >= start_column:
                continuation.append(line.strip())
        if position > 0:
            prev_index = matches[position - 1][0]
            prefix = [line.strip() for line in lines[prev_index + 1:index]
                      if line.strip() and len(line) - len(line.lstrip()) < start_column
                      and re.search(r"[一-鿿A-Za-z]", line)]
            name = "".join(prefix) + name
        name += "".join(continuation)
        if not name or len(name) > 200:
            raise ProviderError("eastmoney:holders", "持有人名称无法可靠拼接")
        try:
            result.append(HolderRecord(code=code, report_date=report_date, published_on=published_on,
                holder=name, shares=number(match.group(4)), ratio_pct=number(match.group(5)),
                source="eastmoney:holders", fetched_at=fetched_at, source_url=source_url,
                institution_group=classify_institution(name)))
        except ValueError as exc:
            raise ProviderError("eastmoney:holders", f"公告持有人数值不合法: {exc}") from exc
    return result


def parse_holders_html(html, code, fetched_at, source_url):
    """功能：严格解析十大持有人表；输入：HTML、代码、采集时间和URL；输出：持有人列表。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for table in soup.find_all("table"):
        headers = [cell.get_text("", strip=True) for cell in table.select("thead th")]
        if not headers:
            first = table.find("tr")
            headers = [cell.get_text("", strip=True) for cell in first.find_all(["th", "td"])] if first else []
        holder_column = next((i for i, h in enumerate(headers) if "持有人名称" in h or "持有人姓名" in h), None)
        if holder_column is None:
            continue  # 不解析股票名称/证券代码等基金持股表。
        context = table.find_previous(["h3", "h4", "h2", "caption", "div"])
        text = (context.get_text(" ", strip=True) if context else "") + " " + table.get_text(" ", strip=True)
        report_match = re.search(r"(?:报告期|截止日期|截至)[：:\s]*(\d{4}-\d{2}-\d{2})", text)
        if not report_match:
            raise ProviderError("eastmoney:holders", "持有人表缺少明确报告期")
        report_date = parse_date(report_match.group(1))
        published = re.search(r"(?:公告日期|披露日期)[：:\s]*(\d{4}-\d{2}-\d{2})", text)
        published_on = parse_date(published.group(1)) if published else None
        if report_date > fetched_at.date() or (published_on and (published_on < report_date or published_on > fetched_at.date())):
            raise ProviderError("eastmoney:holders", "持有人报告期/公告日期非法")
        share_column = next((i for i, h in enumerate(headers) if "持有份额" in h), None)
        ratio_column = next((i for i, h in enumerate(headers) if "比例" in h), None)
        if share_column is not None:
            unit = headers[share_column]
            if "万份" in unit:
                multiplier = 10000
            elif "亿份" in unit:
                multiplier = 1e8
            elif "(份)" in unit or "（份）" in unit:
                multiplier = 1
            else:
                raise ProviderError("eastmoney:holders", "持有份额单位未知")
        try:
            for tr in table.find_all("tr"):
                cells = [cell.get_text("", strip=True) for cell in tr.find_all("td")]
                if len(cells) != len(headers) or cells == headers:
                    continue
                holder = cells[holder_column]
                quantity = number(cells[share_column], optional=True) if share_column is not None else None
                ratio = number(cells[ratio_column], optional=True) if ratio_column is not None else None
                records.append(HolderRecord(code=code, report_date=report_date, published_on=published_on,
                    holder=holder, shares=None if quantity is None else quantity * multiplier,
                    ratio_pct=ratio, source_url=source_url, source="eastmoney:holders", fetched_at=fetched_at,
                    quality="valid" if published_on else "partial"))
        except (ValueError, IndexError, TypeError) as exc:
            raise ProviderError("eastmoney:holders", f"持有人格式错误: {exc}") from exc
    return require_rows(records, "eastmoney:holders")
