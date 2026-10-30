"""真实公告JSON协议与原始上市基金前十持有人文本固定测试。"""
from datetime import date

import httpx
import pytest

from etf_monitor.providers import ProviderError
from etf_monitor.providers.live import parse_holders_text
from test_providers import SH, NOW, D1, make_provider

ART = "AN202603301820868083"
FIRST = "本报告期自 2025 年 01 月 01 日起至 2025 年 12 月 31 日止。\n9.2 期末上市基金前十名持有人 ......75"
# 原始格式来自510300基金2025年报公告27页抽查，不是第三方仓库代码。
REAL_ROWS = '''
9.2 期末上市基金前十名持有人
    序号          持有人名称      持有份额（份）      占上市总份额比例（%）
      1        中央汇金资产管理有  37,858,474,974.00                        42.62
                  限责任公司
      2        中央汇金投资有限责  35,654,598,859.00                        40.14
                    任公司
      3        太平人寿保险有限公    272,999,551.00                        0.31
                      司
      4        友邦人寿保险有限公    259,346,074.00                        0.29
                    司－传统
      5        香港中央结算有限公    199,140,914.00                        0.22
                      司
      6        大家人寿保险股份有    190,696,200.00                        0.21
                限公司－传统产品
              北京诚旸投资有限公
      7        司－诚旸灵活配置私    179,399,890.00                        0.20
                募证券投资基金
      8        友邦人寿保险有限公    175,553,694.00                        0.20
                    司－分红
      9        中国人寿再保险有限    146,856,665.00                        0.17
                    责任公司
      10      中国人寿保险股份有    119,018,700.00                        0.13
                    限公司
              华泰柏瑞沪深 300 交
      11      易型开放式指数证券    665,052,468.00                        0.75
                投资基金联接基金
注：前十名持有人为除本基金的联接基金之外的前十名持有人。
9.3 期末基金管理人的从业人员持有本基金的情况
'''


def test_announcement_raw_table_and_wrapped_names():
    """功能：原始年报准确拼接名称且剔除联接基金；输入：真实格式固定样本；输出：十持有人。"""
    result = parse_holders_text(FIRST + REAL_ROWS, SH.code, NOW, date(2026, 3, 31), "https://pdf.dfcfw.com/example.pdf")
    assert len(result) == 10
    assert result[0].holder == "中央汇金资产管理有限责任公司"
    assert result[0].shares == 37858474974
    assert result[1].holder == "中央汇金投资有限责任公司"
    assert result[5].holder == "大家人寿保险股份有限公司－传统产品"
    assert result[6].holder == "北京诚旸投资有限公司－诚旸灵活配置私募证券投资基金"
    assert result[9].holder == "中国人寿保险股份有限公司"
    assert result[0].report_date == date(2025, 12, 31)
    assert result[0].published_on == date(2026, 3, 31)
    assert all(r.quality == "valid" for r in result)


@pytest.mark.parametrize("text,published", [
    (REAL_ROWS, D1), (FIRST, D1), (FIRST + REAL_ROWS.replace("注：", "无边界").split("9.3")[0], D1),
    (FIRST + REAL_ROWS.replace("持有份额（份）", "持有份额"), D1),
    (FIRST + REAL_ROWS.replace("      3", "      12"), D1),
    (FIRST + REAL_ROWS, None), (FIRST + REAL_ROWS, date(2025, 1, 1)),
    (FIRST + REAL_ROWS.replace("42.62", "142.62"), D1),
])
def test_announcement_requires_complete_valid_metadata(text, published):
    """功能：不完整公告/错误单位不产虚假持有人；输入：损坏正文；输出：ProviderError。"""
    with pytest.raises(ProviderError):
        parse_holders_text(text, SH.code, NOW, published, "")


def response_page(index, count=3):
    """功能：构造公告API原始包；输入：分页索引；输出：来源校验JSON。"""
    return {"success": 1, "data": {"art_code": ART, "notice_date": "2026-03-31 00:00:00",
        "security": [{"stock": "510300"}], "page_size": str(count),
        "notice_content": FIRST if index == 1 else REAL_ROWS if index == 2 else "§13 备查文件目录"}}


def list_payload():
    """功能：构造公告列表；输入：无；输出：固定年报JSON。"""
    return {"ErrCode": 0, "Data": [{"FUNDCODE": "510300", "TITLE": "华泰柏瑞沪深300ETF2025年年度报告",
        "PUBLISHDATE": "2026-03-31T00:00:00", "ID": ART}]}


def test_live_announcement_fetch_bounded_and_identity():
    """功能：获取真实公告式分页并核验基金；输入：mock公告API；输出：十记录。"""
    requests = []
    def handler(request):
        """功能：模拟真实公告API；输入：请求；输出：列表/正文。"""
        requests.append(request)
        payload = list_payload() if request.url.path.endswith("JJGG") else response_page(int(request.url.params["page_index"]))
        return httpx.Response(200, json=payload)
    result = make_provider(handler).holders(SH)
    assert len(result) == 10
    assert len(requests) == 4
    assert result[0].source_url == f"https://pdf.dfcfw.com/pdf/H2_{ART}_1.pdf"
    assert [r.url.params.get("page_index") for r in requests[1:]] == ["1", "3", "2"]


@pytest.mark.parametrize("mutation", ["wrong_code", "wrong_art", "wrong_date", "too_many_pages", "bad_id", "empty_list", "bad_list"])
def test_live_announcement_wrong_identity_and_bounds(mutation):
    """功能：身份/日期/分页错误明确拒绝；输入：坏公告包；输出：ProviderError。"""
    def handler(request):
        """功能：提供被修改公告包；输入：请求；输出：失败样本。"""
        listing = list_payload()
        page = response_page(1)
        if mutation == "wrong_code":
            page["data"]["security"] = [{"stock": "159919"}]
        elif mutation == "wrong_art":
            page["data"]["art_code"] = "AN000000000000000000"
        elif mutation == "wrong_date":
            page["data"]["notice_date"] = "2026-04-01"
        elif mutation == "too_many_pages":
            page["data"]["page_size"] = "100"
        elif mutation == "bad_id":
            listing["Data"][0]["ID"] = "../../etc/passwd"
        elif mutation == "empty_list":
            listing["Data"] = []
        elif mutation == "bad_list":
            listing["ErrCode"] = 1
        return httpx.Response(200, json=listing if request.url.path.endswith("JJGG") else page)
    with pytest.raises(ProviderError):
        make_provider(handler).holders(SH)


def test_missing_latest_report_falls_back_not_structure():
    """功能：最新中报只有结构时回溯年报；输入：两份公告；输出：准确上一报告前十。"""
    latest_art = "AN202608291828684524"
    def handler(request):
        """功能：模拟无前十中报与有前十年报；输入：请求；输出：对应公告正文。"""
        if request.url.path.endswith("JJGG"):
            listing = list_payload()
            listing["Data"].insert(0, {"FUNDCODE": "510300", "TITLE": "2026年中期报告",
                "PUBLISHDATE": "2026-04-01", "ID": latest_art})
            return httpx.Response(200, json=listing)
        payload = response_page(int(request.url.params["page_index"]), 3)
        if request.url.params["art_code"] == latest_art:
            payload["data"]["art_code"] = latest_art
            payload["data"]["notice_date"] = "2026-04-01"
            payload["data"]["notice_content"] = "§8 基金份额持有人结构（仅机构/个人比例）"
        return httpx.Response(200, json=payload)
    result = make_provider(handler).holders(SH)
    assert result[0].report_date == date(2025, 12, 31) and len(result) == 10


def test_one_page_report_and_missing_table():
    """功能：单页可用及多页无表显式失败；输入：固定包；输出：有效十行/异常。"""
    def handler(request):
        """功能：单页报告mock；输入：请求；输出：完整单页。"""
        page = response_page(1, 1)
        page["data"]["notice_content"] = FIRST + REAL_ROWS
        return httpx.Response(200, json=list_payload() if request.url.path.endswith("JJGG") else page)
    assert len(make_provider(handler).holders(SH)) == 10
    def missing_handler(request):
        """功能：无持有人正文mock；输入：请求；输出：目录页。"""
        return httpx.Response(200, json=list_payload() if request.url.path.endswith("JJGG") else response_page(1, 3))
    with pytest.raises(ProviderError):
        make_provider(missing_handler).holders(SH)
