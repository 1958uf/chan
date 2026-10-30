"""真实沪深ETF目录与保守分类，不读取净值、行情或持有人报告。

目录只是交易所发现结果，名称推断保留候选状态；分类确认不等于机构身份判断。
接口字段参考交易所公开清单，独立实现且不复制上游库代码。
"""
from datetime import date
from io import BytesIO
import re
from zipfile import BadZipFile

from pydantic import ValidationError

from ..models import ETF
from .base import ProviderError, parse_date
from .live import HEADERS, LiveProvider

# 仅收录已核对的核心产品代码，不能用名称包含“300”等数字扩大同指数成员。
_CORE_CODES = {
    "510050": "上证50", "510300": "沪深300", "510310": "沪深300",
    "510330": "沪深300", "159919": "沪深300", "510500": "中证500",
    "159922": "中证500", "512100": "中证1000", "159845": "中证1000",
    "159338": "中证A500", "159352": "中证A500", "563880": "中证A500",
    "563300": "中证2000", "588000": "科创50", "588080": "科创50",
    "159915": "创业板", "159949": "创业板50", "510880": "上证红利",
    "515080": "中证红利",
}
_INDEXES = {
    "上证50": ("上证50指数", "宽基", ("上证50", "上证50指数", "000016")),
    "沪深300": ("沪深300指数", "宽基", ("沪深300", "沪深300指数", "000300", "399300")),
    "中证500": ("中证500指数", "宽基", ("中证500", "中证500指数", "000905", "399905")),
    "中证1000": ("中证1000指数", "宽基", ("中证1000", "中证1000指数", "000852")),
    "中证A500": ("中证A500指数", "宽基", ("中证A500", "中证A500指数", "000510")),
    "中证2000": ("中证2000指数", "宽基", ("中证2000", "中证2000指数", "932000")),
    "科创50": ("上证科创板50成份指数", "宽基", ("科创50", "科创50指数", "科创板50", "科创板50指数", "上证科创板50成份指数", "000688")),
    "创业板": ("创业板指数", "宽基", ("创业板", "创业板指", "创业板指数", "399006")),
    "创业板50": ("创业板50指数", "宽基", ("创业板50", "创业板50指数", "399673")),
    "科创创业50": ("中证科创创业50指数", "宽基", ("科创创业50", "中证科创创业50指数", "双创50", "931643")),
    "上证红利": ("上证红利指数", "风格", ("上证红利", "上证红利指数", "000015")),
    "中证红利": ("中证红利指数", "风格", ("中证红利", "中证红利指数", "000922")),
}
# 名称中这些变体不得归入基础指数；即使代码命中也应显式报告身份冲突。
_VARIANTS = ("增强", "联接", "红利", "低波", "价值", "成长", "ESG", "质量", "等权", "动量", "行业")
_ASSETS = (
    ("货币", ("货币", "现金", "添富快钱", "日利", "银华日利")),
    ("跨境", ("纳斯达克", "标普", "恒生", "港股", "香港", "日经", "德国", "法国", "美国", "海外", "全球", "QDII", "中概", "道琼斯", "亚太")),
    ("债券", ("国债", "政金债", "信用债", "债券", "可转债", "公司债", "地方债", "城投债", "短债")),
    ("商品", ("黄金", "白银", "原油", "豆粕", "有色期货", "能源化工期货", "商品")),
    ("风格", ("红利", "低波", "价值", "成长", "质量", "动量", "等权", "增强", "ESG")),
    ("行业", ("证券", "银行", "保险", "金融", "医药", "医疗", "半导体", "芯片", "电子", "地产", "房地产", "煤炭", "钢铁", "有色", "农业", "食品", "酒", "消费", "军工", "电力", "汽车", "通信", "传媒", "计算机", "化工", "建材")),
    ("主题", ("新能源", "光伏", "智能", "机器人", "人工智能", "AI", "数字", "互联网", "环保", "碳", "科技", "创新", "一带一路", "央企", "国企", "航天", "低空", "云计算")),
)


def _text(value) -> str:
    """功能：清理交易所文本和Excel空值；输入：原始值；输出：无HTML、无空白文本。"""
    if value is None or str(value).strip().lower() in {"", "nan", "nat", "none", "-", "--"}:
        return ""
    return re.sub(r"\s+", "", re.sub(r"<[^>]*>", "", str(value))).strip()


def _index_text(value) -> str:
    """功能：统一精确指数别名供名称冲突与指数字段共用；输入：原始文本；输出：规范大写文本。"""
    return re.sub(r"科创板50(?!\d)", "科创50", _text(value).upper())


def _asset(text: str) -> tuple[str, str]:
    """功能：保守识别资产类别；输入：名称或指数文本；输出：资产类和命中词。"""
    for asset, words in _ASSETS:
        for word in words:
            if word.upper() in text.upper():
                return asset, word
    return "未分类", ""


def classify_etf(code: str, name: str, exchange: str, *, tracking_index: str | None = None,
                 index_source: str | None = None, **metadata) -> dict:
    """功能：用精确代码/可核指数确认、名称仅候选；输入：身份和指数；输出：ETF分类字段。

    跟踪指数需来自可核交易所字段或人工证据，普通名称不是跟踪指数证据。
    index_source可注明证据来源，metadata预留兼容目录字段，不用于持有人推断。
    """
    code, text = str(code), _index_text(name)
    if not re.fullmatch(r"\d{6}", code) or exchange not in {"sh", "sz"}:
        raise ValueError("代码必须六位，交易所必须sh或sz")
    result = {"asset_class": "未分类", "group": "未分类", "tracking_index": None,
              "classification_status": "unclassified", "classification_evidence": "交易所目录发现，尚无可核分类依据"}
    if "联接" in text:
        result["classification_evidence"] = "名称为联接产品，不能作为同指数ETF成员"
        return result
    index = _index_text(tracking_index)
    indexed_group = next((group for group, (_, _, aliases) in _INDEXES.items()
                          if index and index in {_index_text(alias) for alias in aliases}), None)
    core = _CORE_CODES.get(code)
    # 防止深沪错码和已知核心代码搭配不一致指数/变体名称。
    identity_ok = exchange == ("sz" if code.startswith("15") else "sh")
    named_index = next((group for group in ("科创创业50", "科创100", "科创200", "创业板50", "中证A500", "中证2000", "中证1000",
                                           "中证500", "沪深300", "上证50", "科创50", "上证红利", "中证红利")
                        if re.search(re.escape(group.upper()) + r"(?!\d)", text)), None)
    if "双创50" in text:
        named_index = "科创创业50"
    elif named_index is None and "创业板" in text:
        named_index = "创业板"
    # 行业/主题/跨境等修饰也是不同指数，不能只排除红利和增强。
    modifiers = [word for _, words in _ASSETS for word in words if word.upper() in text
                 and not (word == "红利" and core in {"上证红利", "中证红利"})]
    foreign_asset = bool(modifiers)
    variant = foreign_asset or any(word in text for word in _VARIANTS if not (word == "红利" and core in {"上证红利", "中证红利"}))
    if core and named_index and named_index != core:
        result["classification_evidence"] = f"核心代码{code}与名称指数{named_index}冲突，须人工核对"
        return result
    if core and identity_ok and not variant and (not index or indexed_group == core):
        canonical, asset, _ = _INDEXES[core]
        result.update(group=core, asset_class=asset, tracking_index=canonical,
                      classification_status="confirmed", classification_evidence=f"已核核心代码{code}；跟踪{canonical}")
        return result
    if core and (not identity_ok or variant or index and indexed_group != core):
        result["classification_evidence"] = f"核心代码{code}与交易所、名称变体或跟踪指数冲突，须人工核对"
        return result
    if indexed_group and named_index and named_index != indexed_group:
        result["classification_evidence"] = f"跟踪指数{tracking_index}与名称指数{named_index}冲突，须人工核对"
        return result
    index_asset_conflict = any(word.upper() in text for _, words in _ASSETS for word in words
                               if not (word == "红利" and indexed_group in {"上证红利", "中证红利"}))
    if indexed_group and not index_asset_conflict and not any(word in text for word in _VARIANTS
                                  if not (word == "红利" and "红利" in indexed_group)):
        canonical, asset, _ = _INDEXES[indexed_group]
        result.update(group=indexed_group, asset_class=asset, tracking_index=canonical,
                      classification_status="confirmed",
                      classification_evidence=f"{index_source or '交易所跟踪指数字段'}：{tracking_index}，精确匹配{canonical}")
        return result
    if index:
        # 非核心指数保留完整身份，禁止宽泛行业词把不同指数合并为“同指数”总体。
        asset, word = _asset(index)
        result.update(group=_text(tracking_index)[:40], asset_class=asset, tracking_index=_text(tracking_index)[:100],
                      classification_status="candidate",
                      classification_evidence=f"{index_source or '交易所跟踪指数字段'}：{tracking_index}；非核心指数待核对{word}"[:300])
        return result
    # 先处理变体和双创/科创等相近名称，再考虑基础指数，绝不以数字子串匹配。
    asset, word = _asset(text)
    candidate = None
    for token, group in (("科创创业50", "科创创业50"), ("双创50", "科创创业50"),
                         ("创业板50", "创业板50"), ("科创100", "科创100"),
                         ("科创200", "科创200"), ("科创50", "科创50"), ("科创板50", "科创50")):
        if token in text:
            candidate = group
            break
    if candidate is None:
        for group in ("中证A500", "中证2000", "中证1000", "中证500", "沪深300", "上证50", "上证红利", "中证红利"):
            if re.search(re.escape(group.upper()) + r"(?!\d)", text):
                candidate = group
                break
    if candidate is None and "创业板" in text:
        candidate = "创业板"
    variants = [term for term in _VARIANTS if term in text and not (term == "红利" and candidate and "红利" in candidate)]
    expected_asset = _INDEXES.get(candidate, (None, "宽基", ()))[1]
    if candidate and word and asset != expected_asset and word not in variants:
        variants.append(word)
    if candidate:
        asset = asset if variants else expected_asset
        group = candidate + ("·" + "·".join(variants) if variants else "")
        result.update(group=group[:40], asset_class=asset, classification_status="candidate",
                      classification_evidence=f"仅名称命中{candidate}{'及变体' + '、'.join(variants) if variants else ''}，未核跟踪指数")
    elif word:
        result.update(group=f"{asset}·{word}", asset_class=asset, classification_status="candidate",
                      classification_evidence=f"仅名称命中{word}，不同跟踪指数不可视为完整同指数成员")
    return result


def _build_etf(row: dict, exchange: str, provider: LiveProvider, source: str, source_date: date | None) -> ETF:
    """功能：规范目录行且记录真实日期来源；输入：交易所行；输出：兼容旧模型的ETF。"""
    raw = _text(row.get("SEC_CODE") if exchange == "sh" else row.get("基金代码"))
    if not re.fullmatch(r"\d{1,6}(?:\.0)?", raw):
        raise ValueError("基金代码格式错误")
    code = str(int(float(raw))).zfill(6)
    if (exchange == "sh" and not code.startswith("5")) or (exchange == "sz" and not code.startswith("15")):
        raise ValueError("ETF代码与交易所不符")
    name = _text(row.get("SEC_NAME") if exchange == "sh" else row.get("基金简称"))
    if not name:
        raise ValueError("基金简称缺失")
    index = _text(row.get("TRACKING_INDEX") or row.get("INDEX_NAME") or row.get("跟踪指数")) or None
    listed = _text(row.get("LIST_DATE") or row.get("上市日期"))
    manager = _text(row.get("MANAGER") or row.get("基金管理人")) or None
    fields = classify_etf(code, name, exchange, tracking_index=index, index_source=source)
    dated_source = source + (f":{source_date.isoformat()}" if source_date else ":latest（源未提供统计日）")
    return ETF(code=code, name=name, exchange=exchange, listed_on=parse_date(listed) if listed else None,
               manager=manager, catalogue_source=dated_source, discovered_at=provider.clock(), **fields)


def _sse_catalogue(provider: LiveProvider, as_of: date) -> list[ETF]:
    """功能：有界分页读取沪市指定日份额目录；输入：提供器和日期；输出：完整沪市目录。"""
    source = "sse:catalogue"
    result, seen = [], set()
    total = None
    # 页大小500、最多10页，拒绝截断或重复页，不把部分目录标记成完整同步。
    for page in range(1, 11):
        payload = provider.http.json(source, "https://query.sse.com.cn/commonQuery.do", params={
            "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": as_of.isoformat(),
            "isPagination": "true", "pageHelp.pageSize": "500", "pageHelp.pageNo": str(page),
        }, headers=HEADERS)
        try:
            if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
                raise ValueError("缺少result数组")
            rows = payload["result"]
            reported = payload.get("pageHelp", {}).get("total")
            if reported is not None:
                count = int(reported)
                if count < 0 or count > 5000 or total is not None and count != total:
                    raise ValueError("目录总数非法、超过5000或分页总数变化")
                total = count
            if len(rows) > 5000 or len(result) + len(rows) > 5000:
                raise ValueError("目录超过5000上限")
            for row in rows:
                actual = parse_date(row["STAT_DATE"])
                if actual != as_of:
                    raise ValueError("目录统计日期与请求不符，不可冒充历史")
                etf = _build_etf(row, "sh", provider, source, actual)
                if etf.code in seen:
                    raise ValueError("目录重复代码或分页重复")
                seen.add(etf.code)
                result.append(etf)
            if total is not None and len(result) > total:
                raise ValueError("返回数量超过目录总数")
            if total is not None and len(result) == total or total is None and len(rows) < 500:
                return result
            if not rows:
                raise ValueError("分页提前为空，目录被截断")
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
            raise ProviderError(source, f"沪市目录格式错误：{exc}") from exc
    raise ProviderError(source, "目录分页超过10页或被截断")


def _szse_catalogue(provider: LiveProvider, as_of: date) -> list[ETF]:
    """功能：读取深市最新ETF工作簿；输入：提供器和请求日期；输出：源日期明确的目录。"""
    source = "szse:catalogue"
    response = provider.http.get(source, "https://fund.szse.cn/api/report/ShowReport", params={
        "SHOWTYPE": "xlsx", "CATALOGID": "1000_lf", "TABKEY": "tab1",
    }, headers={**HEADERS, "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html"})
    try:
        import pandas as pd
        frame = pd.read_excel(BytesIO(response.content), dtype={"基金代码": str}, engine="openpyxl")
        if not {"基金代码", "基金简称", "基金类别"}.issubset(frame.columns):
            raise ValueError("深市最新ETF列表字段缺失")
        if len(frame) > 5000:
            raise ValueError("目录超过5000上限")
        result, seen = [], set()
        for row in frame.dropna(how="all").to_dict("records"):
            raw = _text(row.get("基金代码"))
            if not re.fullmatch(r"\d{1,6}(?:\.0)?", raw):
                if raw and raw not in {"说明", "合计", "总计"} and not raw.startswith("注"):
                    raise ValueError("深市目录含非法基金代码")
                continue
            if "ETF" not in _text(row.get("基金类别")).upper():
                continue  # 同一报表中的LOF和封闭式基金不是ETF。
            source_date = next((parse_date(row[key]) for key in ("统计日期", "数据日期", "日期")
                                if _text(row.get(key))), None)
            if source_date and source_date > provider.clock().date():
                raise ValueError("深市目录提供未来统计日期")
            etf = _build_etf(row, "sz", provider, source, source_date)
            if etf.code in seen:
                raise ValueError("深市目录重复代码")
            seen.add(etf.code)
            result.append(etf)
        return result
    except (ValueError, KeyError, TypeError, ImportError, BadZipFile, OSError, ValidationError) as exc:
        raise ProviderError(source, f"深市目录Excel格式错误：{exc}") from exc


def fetch_catalogue(provider: LiveProvider, as_of: date, exchange: str | None = None) -> list[ETF]:
    """功能：真实发现沪深ETF目录；输入：有界LiveProvider、日期、可选市场；输出：ETF列表。

    单市场失败抛ProviderError，上层可分别调用隔离提交；不返回静默部分成功。
    深市只提供最新清单，来源明确标注latest而不冒充as_of历史目录。
    """
    if exchange not in {None, "sh", "sz"}:
        raise ProviderError("validation", "exchange只能sh或sz")
    as_of = parse_date(as_of)
    if as_of > provider.clock().date():
        raise ProviderError("validation", "不能请求未来目录")
    result = []
    if exchange in {None, "sh"}:
        result.extend(_sse_catalogue(provider, as_of))
    if exchange in {None, "sz"}:
        result.extend(_szse_catalogue(provider, as_of))
    if not result:
        source = {"sh": "sse:catalogue", "sz": "szse:catalogue"}.get(exchange, "exchange:catalogue")
        raise ProviderError(source, "目录查询成功但没有ETF", status="empty")
    if len(result) > 5000:
        raise ProviderError("exchange:catalogue", "沪深总目录超过5000上限")
    return sorted(result, key=lambda etf: etf.code)
