"""机构名称归类只是公开标签，不是实时账户识别。"""
import pytest

from etf_monitor.providers.live import classify_institution


@pytest.mark.parametrize("name,label", [
    ("中央汇金资产管理有限责任公司", "汇金资管"),
    ("中央汇金投资有限责任公司", "中央汇金"),
    ("全国社会保障基金", "社保/养老"),
    ("中国证券金融股份有限公司", "证金"),
    ("普通投资者", None),
])
def test_institution_name_tags(name, label):
    """功能：明确名称标签；输入：公开名称；输出：匹配或未知。"""
    assert classify_institution(name) == label
