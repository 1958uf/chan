"""独立SQLite仓储，所有业务批次采用显式事务。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from ..models import ETF, BarRecord, HolderRecord, MarketRecord, NavRecord, QuoteRecord, ShareRecord

RECORD_MODELS = {"shares": ShareRecord, "quotes": QuoteRecord, "bars": BarRecord,
                 "navs": NavRecord, "holders": HolderRecord, "market": MarketRecord}


def encode(value):
    """功能：稳定序列化；输入：JSON兼容对象；输出：UTF-8 JSON文本。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


class Repository:
    """本地仓储；构造不产生文件，initialize才创建独立数据库。"""

    def __init__(self, path: Path):
        """功能：保存独立路径；输入：数据库路径；输出：仓储实例。"""
        self.path = Path(path)

    @contextmanager
    def connection(self):
        """功能：开启事务连接；输入：无；输出：提交或回滚的连接。"""
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        """功能：创建WAL表结构；输入：无；输出：无，异常直接抛出。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS etfs(code TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS catalogue(code TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(
                    kind TEXT NOT NULL, business_key TEXT NOT NULL, source TEXT NOT NULL,
                    code TEXT NOT NULL, day TEXT NOT NULL, payload TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(kind,business_key,source));
                CREATE INDEX IF NOT EXISTS records_lookup ON records(kind,code,day);
                CREATE TABLE IF NOT EXISTS revisions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    business_key TEXT NOT NULL, source TEXT NOT NULL,
                    revision INTEGER NOT NULL, payload TEXT NOT NULL, changed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY, dedup_key TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS alerts_dedup ON alerts(dedup_key,created_at);
                CREATE TABLE IF NOT EXISTS sources(source TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calendar(day TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS calendar_coverage(
                    start TEXT NOT NULL,end TEXT NOT NULL,source TEXT NOT NULL,fetched_at TEXT NOT NULL,
                    PRIMARY KEY(start,end,source));
            """)
            # 目录独立迁移只补不存在的代码，绝不回写精选观察池或覆盖人工分类。
            db.execute("INSERT OR IGNORE INTO catalogue(code,payload) SELECT code,payload FROM etfs")
            # 升级既有独立库，旧数据知识边界只能依据已保留的采集/修订时刻恢复。
            for table in ("records", "revisions"):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if "known_from" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN known_from TEXT")
                    db.execute(f"UPDATE {table} SET known_from=json_extract(payload,'$.fetched_at') WHERE known_from IS NULL")
            db.execute("UPDATE records SET known_from=(SELECT MAX(changed_at) FROM revisions r WHERE r.kind=records.kind AND r.business_key=records.business_key AND r.source=records.source) "
                       "WHERE EXISTS(SELECT 1 FROM revisions r WHERE r.kind=records.kind AND r.business_key=records.business_key AND r.source=records.source) "
                       "AND julianday(known_from)<(SELECT MAX(julianday(changed_at)) FROM revisions r WHERE r.kind=records.kind AND r.business_key=records.business_key AND r.source=records.source)")

    def etfs(self):
        """功能：读观察池；输入：无；输出：代码排序ETF列表。"""
        with self.connection() as db:
            return [ETF.model_validate_json(r[0]) for r in db.execute("SELECT payload FROM etfs ORDER BY code")]

    def put_etfs(self, etfs: Iterable[ETF]):
        """功能：原子保存观察池；输入：ETF序列；输出：无。"""
        values = [(item.code, item.model_dump_json()) for item in etfs]
        with self.connection() as db:
            db.executemany("INSERT INTO etfs VALUES(?,?) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload", values)
            db.executemany("INSERT OR IGNORE INTO catalogue VALUES(?,?)", values)

    def catalogue(self, *, asset_class=None, group=None, classification_status=None, q=None,
                  enabled=None, exchange=None, limit=100, offset=0):
        """功能：分页检索独立全市场目录；输入：分类、关键词、状态及≤5000分页；输出：ETF列表。"""
        if not 1 <= limit <= 5000 or not 0 <= offset <= 100000:
            raise ValueError("目录分页范围非法")
        clauses, args = self._catalogue_filter(asset_class, group, classification_status, q, enabled, exchange)
        with self.connection() as db:
            return [ETF.model_validate_json(row[0]) for row in db.execute(
                f"SELECT payload FROM catalogue WHERE {' AND '.join(clauses)} ORDER BY code LIMIT ? OFFSET ?",
                args + [limit, offset])]

    @staticmethod
    def _catalogue_filter(asset_class, group, classification_status, q, enabled, exchange):
        """功能：构造参数化目录条件；输入：受控筛选字段；输出：SQL条件和绑定值。"""
        clauses, args = ["1=1"], []
        for key, value in (("asset_class", asset_class), ("group", group),
                           ("classification_status", classification_status), ("enabled", enabled), ("exchange", exchange)):
            if value is not None:
                clauses.append(f"json_extract(payload,'$.{key}')=?")
                args.append(value)
        if q:
            clauses.append("(instr(code,?)>0 OR instr(json_extract(payload,'$.name'),?)>0)")
            args.extend([q, q])
        return clauses, args

    def catalogue_summary(self, **filters):
        """功能：统计分页外的目录总数和来源覆盖；输入：同目录筛选；输出：总数和来源分类分母。"""
        clauses, args = self._catalogue_filter(*(filters.get(key) for key in
            ("asset_class", "group", "classification_status", "q", "enabled", "exchange")))
        with self.connection() as db:
            rows = db.execute(f"SELECT payload FROM catalogue WHERE {' AND '.join(clauses)}", args)
            values = [json.loads(row[0]) for row in rows]
        sources, statuses = {}, {"confirmed": 0, "candidate": 0, "unclassified": 0}
        for item in values:
            source = item.get("catalogue_source") or "legacy-watchpool"
            sources[source] = sources.get(source, 0) + 1
            status = item.get("classification_status", "confirmed")
            statuses[status] += 1
        return {"total": len(values), "coverage": {"sources": sources, **statuses,
                "enabled": sum(item.get("enabled", True) for item in values),
                "notice": "目录为已发现产品，不代表上游全市场完整覆盖；候选未经人工或指数证据确认。"}}

    def sync_catalogue(self, etfs):
        """功能：事务合并目录保留人工分类及启用开关；输入：≤5000规范ETF；输出：发生变化的产品数。"""
        items = [ETF.model_validate(item.model_dump() if hasattr(item, "model_dump") else item) for item in etfs]
        if len(items) > 5000 or len({item.code for item in items}) != len(items):
            raise ValueError("目录批次超限或代码重复")
        changed = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COUNT(*) FROM catalogue").fetchone()[0]
            existing_codes = {row[0] for row in db.execute("SELECT code FROM catalogue")}
            if total + len({item.code for item in items} - existing_codes) > 5000:
                raise ValueError("全市场目录最多5000个产品")
            for item in items:
                old = db.execute("SELECT payload FROM catalogue WHERE code=?", (item.code,)).fetchone()
                value = item.model_dump(mode="json")
                if old:
                    previous = ETF.model_validate_json(old[0]).model_dump(mode="json")
                    value["enabled"] = previous["enabled"]
                    value["discovered_at"] = previous["discovered_at"] or value["discovered_at"]
                    if previous["manual_classification"]:
                        for key in ("group", "asset_class", "tracking_index", "classification_status",
                                    "classification_evidence", "manual_classification"):
                            value[key] = previous[key]
                    if previous == value:
                        continue
                db.execute("INSERT INTO catalogue VALUES(?,?) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload",
                           (item.code, encode(value)))
                changed += 1
        return changed

    def classify_catalogue(self, code, **classification):
        """功能：原子人工确认目录成员；输入：代码及已校验分类字段；输出：保存的ETF或None。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM catalogue WHERE code=?", (code,)).fetchone()
            if row is None:
                return None
            value = ETF.model_validate({**json.loads(row[0]), **classification, "manual_classification": True,
                                       "classification_status": "confirmed", "classification_evidence": "用户人工核对确认"})
            db.execute("UPDATE catalogue SET payload=? WHERE code=?", (value.model_dump_json(), code))
            return value

    def set_catalogue_enabled(self, code, enabled):
        """功能：兼容旧观察池禁用开关；输入：代码及布尔开关；输出：无，不覆盖目录分类。"""
        with self.connection() as db:
            db.execute("UPDATE catalogue SET payload=json_set(payload,'$.enabled',json(?)) WHERE code=?",
                       ("true" if enabled else "false", code))

    def share_latest_dates(self, codes, end):
        """功能：读取每个目录成员已提交份额日期；输入：≤5000代码、截止日；输出：代码到日期映射。"""
        if not codes:
            return {}
        if len(codes) > 5000:
            raise ValueError("份额成员超限")
        with self.connection() as db:
            rows = db.execute(f"SELECT code,MAX(day) FROM records WHERE kind='shares' AND day<=? "
                              f"AND code IN ({','.join('?' for _ in codes)}) AND json_extract(payload,'$.quality') IN ('valid','demo') GROUP BY code",
                              [str(end)] + list(codes))
            return {row[0]: date.fromisoformat(row[1]) for row in rows}

    @staticmethod
    def identity(kind, record):
        """功能：建立业务键；输入：类别与记录；输出：唯一键、标的、日期。"""
        code = getattr(record, "code", "")
        if kind in ("shares", "navs", "market"):
            stamp = record.trade_date.isoformat()
            key = f"{code}:{stamp}:{getattr(record, 'metric', '')}"
        elif kind == "holders":
            stamp = record.report_date.isoformat()
            key = encode([code, stamp, record.holder])
        else:
            stamp = (record.quote_time if kind == "quotes" else record.time).isoformat()
            key = f"{code}:{stamp}:{getattr(record, 'interval', '')}"
        return key, code, stamp[:10]

    def save_records(self, batches: dict, changed_at: datetime, *, calendar=None, calendar_request=None):
        """功能：原子保存记录、日历覆盖和修订；输入：批次、保存时钟、可选日历；输出：变化数。"""
        # 提前验证全部数据，避免一半成功后遇到非法记录。
        validated = [(kind, RECORD_MODELS[kind].model_validate(record.model_dump() if hasattr(record, "model_dump") else record))
                     for kind, records in batches.items() for record in records]
        changed = 0
        with self.connection() as db:
            for kind, record in validated:
                key, code, day = self.identity(kind, record)
                value = record.model_dump(mode="json")
                existing = db.execute("SELECT payload,revision,known_from FROM records WHERE kind=? AND business_key=? AND source=?",
                                      (kind, key, record.source)).fetchone()
                revision = 1
                if existing:
                    old = json.loads(existing["payload"])
                    # 仅采集时刻不同属于重试，不产生数据修订。
                    if {k: v for k, v in old.items() if k != "fetched_at"} == {k: v for k, v in value.items() if k != "fetched_at"}:
                        continue
                    revision = existing["revision"] + 1
                    db.execute("INSERT INTO revisions(kind,business_key,source,revision,payload,changed_at,known_from) VALUES(?,?,?,?,?,?,?)",
                               (kind, key, record.source, existing["revision"], existing["payload"], changed_at.isoformat(), existing["known_from"]))
                # demo为固定虚构历史；真实数据首次可知时刻不早于本地首次保存。
                known_from = record.fetched_at if record.quality == "demo" and not existing else max(record.fetched_at, changed_at)
                db.execute("INSERT INTO records(kind,business_key,source,code,day,payload,revision,known_from) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(kind,business_key,source) "
                           "DO UPDATE SET payload=excluded.payload,revision=excluded.revision,day=excluded.day,known_from=excluded.known_from",
                           (kind, key, record.source, code, day, encode(value), revision, known_from.isoformat()))
                changed += 1
            if calendar is not None:
                self._save_calendar(db, calendar, calendar_request, changed_at)
        return changed

    def records(self, kind, code=None, start=None, end=None, limit=1000, offset=0, newest=False, codes=None, known_at=None, day_known=False, interval=None):
        """功能：有界查询记录；输入：过滤与分页；输出：规范化模型列表。"""
        if kind not in RECORD_MODELS:
            raise ValueError("未知记录类别")
        if not 1 <= limit <= 10000 or offset < 0:
            raise ValueError("分页范围非法")
        clauses, args = ["kind=?"], [kind]
        for column, value, operator in (("code", code, "="), ("day", start, ">="), ("day", end, "<=")):
            if value is not None:
                clauses.append(f"{column}{operator}?")
                args.append(str(value))
        if codes is not None:
            if not codes:
                return []
            if len(codes) > (5000 if kind == "shares" else 200):
                raise ValueError("标的过滤超出上限")
            clauses.append(f"code IN ({','.join('?' for _ in codes)})")
            args.extend(codes)
        if interval is not None:
            if kind != "bars" or interval not in ("day", "1m", "5m"):
                raise ValueError("周期过滤非法")
            clauses.append("json_extract(payload,'$.interval')=?")
            args.append(interval)
        order = "DESC" if newest else "ASC"
        with self.connection() as db:
            if known_at is not None:
                if not isinstance(known_at, datetime) or known_at.tzinfo is None:
                    raise ValueError("known_at必须是带时区时间")
                # 从当前与修订版本联合选择当时已知的最高版本，分页在版本选择后执行。
                boundary = "MIN(julianday(?),julianday(day||'T23:59:59.999999+08:00'))" if day_known else "julianday(?)"
                rows = db.execute(f"""WITH versions AS (
                    SELECT kind,business_key,source,code,day,payload,revision,known_from,NULL AS known_until FROM records
                    UNION ALL
                    SELECT kind,business_key,source,json_extract(payload,'$.code') AS code,
                           substr(COALESCE(json_extract(payload,'$.trade_date'),json_extract(payload,'$.report_date'),
                               json_extract(payload,'$.quote_time'),json_extract(payload,'$.time')),1,10) AS day,
                           payload,revision,known_from,changed_at AS known_until FROM revisions),
                    eligible AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY kind,business_key,source ORDER BY revision DESC) AS rank
                        FROM versions WHERE julianday(known_from)<={boundary}
                        AND julianday(json_extract(payload,'$.fetched_at'))<={boundary}
                        AND (known_until IS NULL OR julianday(known_until)>{boundary}))
                    SELECT payload FROM eligible WHERE rank=1 AND {' AND '.join(clauses)}
                    ORDER BY day {order},business_key {order},source LIMIT ? OFFSET ?""",
                    [known_at.isoformat()] * 3 + args + [limit, offset]).fetchall()
            else:
                rows = db.execute(f"SELECT payload FROM records WHERE {' AND '.join(clauses)} ORDER BY day {order},business_key {order},source LIMIT ? OFFSET ?",
                                  args + [limit, offset]).fetchall()
        return [RECORD_MODELS[kind].model_validate_json(r[0]) for r in rows]

    def record_health(self, now):
        """功能：汇总真实源最近业务日和标的覆盖；输入：带时区当前时刻；输出：有界健康摘要。"""
        with self.connection() as db:
            rows = db.execute("""WITH eligible AS (
                SELECT *,COALESCE(json_extract(payload,'$.interval'),'') AS interval,
                    COALESCE(json_extract(payload,'$.metric'),'') AS metric,
                    json_extract(payload,'$.quality') AS quality FROM records
                WHERE day<=? AND julianday(known_from)<=julianday(?)
                    AND julianday(json_extract(payload,'$.fetched_at'))<=julianday(?)
                    AND (kind NOT IN ('quotes','bars') OR julianday(COALESCE(
                        json_extract(payload,'$.quote_time'),json_extract(payload,'$.time')))<=julianday(?))),
                ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY source,kind,code,interval,metric ORDER BY day DESC,business_key DESC) AS rank
                           FROM eligible)
                SELECT source,kind,code,day,interval,metric,quality,payload FROM ranked WHERE rank=1
                ORDER BY source,kind,code LIMIT 10000""", (now.date().isoformat(),) + (now.isoformat(),) * 3)
            return [dict(row) for row in rows]

    def revision_count(self):
        """功能：查询审计条数；输入：无；输出：修订计数。"""
        with self.connection() as db:
            return db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]

    def put_document(self, table, key, value):
        """功能：原子保存内部文档；输入：受控表、键、JSON；输出：无。"""
        columns = {"tasks": "id", "sources": "source", "metadata": "key"}
        if table not in columns:
            raise ValueError("不允许的文档表")
        column = columns[table]
        with self.connection() as db:
            db.execute(f"INSERT INTO {table}({column},payload) VALUES(?,?) ON CONFLICT({column}) DO UPDATE SET payload=excluded.payload", (key, encode(value)))

    def documents(self, table, limit=100, offset=0):
        """功能：读取有界内部文档；输入：受控表与分页；输出：JSON列表。"""
        if table not in ("tasks", "sources", "metadata") or not 1 <= limit <= 10000 or offset < 0:
            raise ValueError("不允许的查询")
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset))]

    def document(self, table, key):
        """功能：读单个内部文档；输入：受控表与键；输出：文档或None。"""
        columns = {"tasks": "id", "sources": "source", "metadata": "key"}
        if table not in columns:
            raise ValueError("不允许的文档表")
        with self.connection() as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE {columns[table]}=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    @staticmethod
    def _save_calendar(db, days, request, fetched_at):
        """功能：事务内保存日期与明确请求覆盖；输入：连接、日期、请求区间、时钟；输出：无。"""
        if request is not None:
            start, end, source = request
            if start > end or not source or any(not isinstance(day, date) or not start <= day <= end for day in days):
                raise ValueError("日历覆盖区间非法")
            # 真实空结果只有在源明确成功返回时才可声明该区间没有交易日。
            db.execute("INSERT INTO calendar_coverage VALUES(?,?,?,?) ON CONFLICT(start,end,source) DO UPDATE SET fetched_at=excluded.fetched_at",
                       (start.isoformat(), end.isoformat(), source, fetched_at.isoformat()))
        db.executemany("INSERT OR IGNORE INTO calendar VALUES(?)", [(day.isoformat(),) for day in days])

    def save_calendar(self, days: list[date], *, start=None, end=None, source="", fetched_at=None):
        """功能：幂等保存日期与可验证覆盖；输入：交易日、显式请求边界和来源；输出：无。"""
        request = (start, end, source) if start is not None and end is not None else None
        if request is not None and fetched_at is None:
            raise ValueError("日历覆盖必须提供采集时间")
        with self.connection() as db:
            self._save_calendar(db, days, request, fetched_at)

    def calendar_coverage(self, known_at=None):
        """功能：读有界覆盖元数据；输入：可选知识截止时间；输出：来源完整区间列表。"""
        with self.connection() as db:
            rows = db.execute("SELECT start,end,source,fetched_at FROM calendar_coverage WHERE (? IS NULL OR julianday(fetched_at)<=julianday(?)) ORDER BY start,end LIMIT 10000",
                              (known_at.isoformat() if known_at else None,) * 2)
            return [dict(row) for row in rows]

    def calendar_covers(self, start, end, known_at=None):
        """功能：确认请求区间完整覆盖不跨缺口；输入：起止日期、知识边界；输出：布尔值。"""
        from datetime import timedelta
        cursor = start
        for interval in self.calendar_coverage(known_at):
            left, right = date.fromisoformat(interval["start"]), date.fromisoformat(interval["end"])
            if right < cursor:
                continue
            if left > cursor:
                return False
            cursor = right + timedelta(days=1)
            if cursor > end:
                return True
        return False

    def calendar_days(self, start=None, end=None, limit=3650):
        """功能：有界读真实缓存交易日历；输入：日期过滤和上限；输出：日期列表。"""
        if not 1 <= limit <= 10000:
            raise ValueError("日历查询上限非法")
        with self.connection() as db:
            rows = db.execute("SELECT day FROM calendar WHERE (? IS NULL OR day>=?) AND (? IS NULL OR day<=?) ORDER BY day DESC LIMIT ?",
                              (str(start) if start else None, str(start) if start else None,
                               str(end) if end else None, str(end) if end else None, limit))
            return sorted(date.fromisoformat(row[0]) for row in rows)

    def is_trading_day(self, day):
        """功能：判断明确已知交易日；输入：日期；输出：是否在日历中。"""
        with self.connection() as db:
            return db.execute("SELECT 1 FROM calendar WHERE day=?", (str(day),)).fetchone() is not None

    def emit_alert(self, alert, dedup_key, cooldown):
        """功能：事务内告警去重；输入：告警、业务键、冷却秒；输出：是否保存。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT created_at FROM alerts WHERE dedup_key=? ORDER BY created_at DESC LIMIT 1", (dedup_key,)).fetchone()
            if previous and (datetime.fromisoformat(alert["created_at"]) - datetime.fromisoformat(previous[0])).total_seconds() < cooldown:
                return False
            db.execute("INSERT INTO alerts VALUES(?,?,?,?)", (alert["id"], dedup_key, alert["created_at"], encode(alert)))
            return True

    def alerts(self, limit=100, offset=0):
        """功能：分页读告警；输入：分页；输出：最新告警列表。"""
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM alerts ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))]

    def acknowledge(self, identifier):
        """功能：确认本地告警；输入：告警ID；输出：是否存在并更新。"""
        with self.connection() as db:
            row = db.execute("SELECT payload FROM alerts WHERE id=?", (identifier,)).fetchone()
            if not row:
                return False
            value = json.loads(row[0])
            value["acknowledged"] = True
            db.execute("UPDATE alerts SET payload=? WHERE id=?", (encode(value), identifier))
            return True
