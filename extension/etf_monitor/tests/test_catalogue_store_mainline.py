"""目录独立迁移、人工分类保护与全市场分页的离线回归。"""
import sqlite3
from datetime import timedelta

import pytest

from etf_monitor.config import default_etfs
from etf_monitor.demo import DEMO_NOW
from etf_monitor.models import ETF
from etf_monitor.storage import Repository


def store(tmp_path):
    """功能：创建临时独立库；输入：测试目录；输出：仓储。"""
    repo = Repository(tmp_path / "catalogue.sqlite")
    repo.initialize()
    return repo


def test_old_watchpool_migrates_once_without_overwrite(tmp_path):
    """功能：验证旧库只迁移缺项且重启不覆盖人工分类；输入：临时库；输出：独立表断言。"""
    path = tmp_path / "old.sqlite"
    item = default_etfs()[0]
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE etfs(code TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        db.execute("INSERT INTO etfs VALUES(?,?)", (item.code, item.model_dump_json()))
    repo = Repository(path)
    repo.initialize()
    assert repo.catalogue()[0] == item
    repo.classify_catalogue(item.code, group="人工组", asset_class="行业", enabled=False)
    repo.initialize()
    assert repo.catalogue()[0].group == "人工组"
    assert repo.catalogue()[0].manual_classification
    assert not repo.catalogue()[0].enabled
    assert repo.etfs() == [item]


def test_sync_keeps_manual_fields_and_enabled_but_updates_description(tmp_path):
    """功能：验证自动发现不覆盖人工确认/禁用并更新来源信息；输入：两个版本；输出：合并断言。"""
    repo = store(tmp_path)
    item = default_etfs()[0].model_copy(update={"catalogue_source": "sse", "discovered_at": DEMO_NOW})
    assert repo.sync_catalogue([item]) == 1
    repo.classify_catalogue(item.code, group="人工组", asset_class="主题", tracking_index="人工指数", enabled=False)
    revised = item.model_copy(update={"name": "更新名称", "group": "自动候选", "asset_class": "未分类",
        "classification_status": "candidate", "tracking_index": None, "discovered_at": DEMO_NOW + timedelta(days=1)})
    assert repo.sync_catalogue([revised]) == 1
    saved = repo.catalogue()[0]
    assert saved.name == "更新名称"
    assert saved.group == "人工组" and saved.asset_class == "主题" and saved.tracking_index == "人工指数"
    assert saved.classification_status == "confirmed" and saved.manual_classification
    assert not saved.enabled and saved.discovered_at == DEMO_NOW
    assert repo.sync_catalogue([revised]) == 0
    assert not repo.etfs()


def test_full_catalogue_above_watchpool_200_and_filters(tmp_path):
    """功能：验证目录大于精选池且5000分页上限与分母正确；输入：600产品；输出：分页筛选断言。"""
    repo = store(tmp_path)
    items = [ETF(code=f"{510000 + i:06}", name=f"目录{i}", group="A" if i % 2 else "B", exchange="sh",
                 asset_class="宽基", classification_status="candidate" if i % 3 else "confirmed", catalogue_source="sse")
             for i in range(600)]
    repo.sync_catalogue(items)
    assert len(repo.catalogue(limit=5000)) == 600
    assert len(repo.catalogue(limit=100, offset=100)) == 100
    assert repo.catalogue_summary(group="A")["total"] == 300
    assert repo.catalogue_summary()["coverage"]["sources"] == {"sse": 600}
    assert all(item.group == "B" for item in repo.catalogue(group="B", classification_status="confirmed", limit=5000))
    assert repo.catalogue(q="目录599")[0].code == "510599"
    assert repo.catalogue(q="%") == []
    with pytest.raises(ValueError):
        repo.catalogue(limit=5001)
    with pytest.raises(ValueError):
        repo.catalogue(offset=-1)
    assert not repo.etfs()


def test_sync_batch_invalid_duplicate_and_limit_are_atomic(tmp_path):
    """功能：验证批次非法或重复不写入及总目录上限；输入：异常批次；输出：零修改。"""
    repo = store(tmp_path)
    item = default_etfs()[0]
    for values in ([item, item], [item, {"code": "bad"}], [item] * 5001):
        with pytest.raises(ValueError):
            repo.sync_catalogue(values)
        assert repo.catalogue_summary()["total"] == 0
    items = [item.model_copy(update={"code": f"{510000 + i:06}"}) for i in range(5000)]
    repo.sync_catalogue(items)
    with pytest.raises(ValueError, match="最多5000"):
        repo.sync_catalogue([item.model_copy(update={"code": "159999"})])
    assert repo.catalogue_summary()["total"] == 5000


def test_put_watchpool_adds_only_missing_catalogue_and_shares_filter_5000(tmp_path):
    """功能：验证旧写入兼容不覆盖目录、shares代码过滤支持5000；输入：ETF和宽筛选；输出：断言。"""
    repo = store(tmp_path)
    item = default_etfs()[0]
    repo.put_etfs([item])
    repo.classify_catalogue(item.code, group="人工组", asset_class="行业")
    repo.put_etfs([item.model_copy(update={"group": "旧分组"})])
    assert repo.catalogue()[0].group == "人工组"
    assert repo.records("shares", codes=[f"{510000 + i:06}" for i in range(5000)]) == []
    with pytest.raises(ValueError):
        repo.records("navs", codes=[f"{510000 + i:06}" for i in range(201)])
    assert repo.classify_catalogue("000000", group="A", asset_class="宽基") is None
