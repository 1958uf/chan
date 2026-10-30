"""任务串行互斥、有限排队、可见取消/超时/恢复与本地日历调度。"""
import queue
import threading
import time
import uuid
from datetime import timedelta


class TaskInterrupted(Exception):
    """任务已取消、关闭或超时，禁止提交任何任务结果。"""


class TaskManager:
    """单worker提交业务数据，外部调用有界等待且超时后不并发新调用。"""

    def __init__(self, repository, provider, settings, clock, queue_size=16, task_timeout=None):
        """功能：组装任务服务；输入：仓储、可注入源、配置、时钟和边界；输出：服务。"""
        self.repository, self.provider, self.settings, self.clock = repository, provider, settings, clock
        self.pending = queue.Queue(maxsize=queue_size)
        self.task_timeout = task_timeout if task_timeout is not None else getattr(settings, "task_timeout_seconds", 600)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.cancel_events = {}
        self.worker = None
        self.scheduler = None
        self.last_scheduled = None

    def start(self):
        """功能：恢复中断并启动本地线程；输入：无；输出：无。"""
        with self.lock:
            recovery_message = "进程中断，任务已恢复为失败；可重新提交"
            recovered = False
            for task in self.repository.documents("tasks", limit=10000):
                if task["status"] in ("pending", "running"):
                    task.update(status="failed", message=recovery_message, finished_at=self.clock().isoformat(), error="interrupted")
                    self.repository.put_document("tasks", task["id"], task)
                    recovered = True
            if recovered:
                self.alert("", "task_recovered", "warning", "发现中断任务", recovery_message)
            self.worker = threading.Thread(target=self._work, daemon=True, name="etf-task-worker")
            self.worker.start()
            self.scheduler = threading.Thread(target=self._schedule, daemon=True, name="etf-calendar-scheduler")
            self.scheduler.start()

    def close(self):
        """功能：有界关闭并取消未完成任务；输入：无；输出：无。"""
        self.stop_event.set()
        with self.lock:
            for identifier in list(self.cancel_events):
                self.cancel(identifier)
        if self.worker:
            self.worker.join(timeout=2)
        if self.scheduler:
            self.scheduler.join(timeout=2)

    def submit(self, kind, start=None, end=None, codes=None, *, quotes_only=False, interval="day",
               group=None, asset_class=None, schedule_key=None):
        """功能：有界创建兼容行情或目录份额任务；输入：类别、日期、成员筛选及周期；输出：持久化任务。"""
        if kind not in ("refresh", "backfill", "holders", "market", "calendar", "catalogue", "shares"):
            raise ValueError("未知任务类型")
        if interval not in ("day", "1m", "5m"):
            raise ValueError("周期只能为day/1m/5m")
        minute = interval != "day"
        if minute and (kind not in ("refresh", "backfill") or quotes_only):
            raise ValueError("分钟周期仅适用于refresh/backfill标的行情任务")
        today = self.clock().date()
        for value, maximum in ((group, 40), (asset_class, 30)):
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > maximum):
                raise ValueError("分类筛选非法")
        end = end or today
        explicit_start = start is not None
        start = start or (end if minute or kind == "catalogue" else end - timedelta(days=40 if kind in ("refresh", "shares") else 7))
        if start > end or end > today or (end - start).days + 1 > self.settings.max_backfill_days:
            raise ValueError("日期区间颠倒、包含未来或超出回补上限")
        if (group is not None or asset_class is not None) and kind != "shares":
            raise ValueError("分类筛选仅适用于纯份额任务")
        if kind == "catalogue" and codes is not None:
            raise ValueError("目录发现不接受观察池代码筛选")
        etfs = (self.repository.catalogue(classification_status="confirmed", enabled=True, group=group,
                                          asset_class=asset_class, limit=5000) if kind == "shares" else self.repository.etfs())
        if codes is not None and (len(codes) > (5000 if kind == "shares" else 200) or any(not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit() for code in codes)):
            raise ValueError("任务代码非法或超出上限")
        known = {etf.code for etf in etfs}
        if codes is not None and (not codes or len(codes) != len(set(codes)) or not set(codes).issubset(known)):
            raise ValueError("标的列表为空、重复或不存在")
        selected = sorted(codes) if codes is not None else [etf.code for etf in etfs if etf.enabled]
        if kind == "catalogue":
            selected = []
        if kind == "shares" and not selected:
            raise ValueError("目录没有符合筛选的已确认且启用成员")
        if len(selected) > (5000 if kind == "shares" else 200):
            raise ValueError("任务成员超出上限")
        if kind == "shares" and not explicit_start:
            latest = self.repository.share_latest_dates(selected, end)
            # 新成员补40自然日，已有成员最近7自然日重复采集，接受上游修订。
            start = min(max(start, latest[code] - timedelta(days=7)) if code in latest else start for code in selected)
        if minute and (codes is None or not selected or len(selected) > 3 or (end - start).days + 1 > 7):
            raise ValueError("分钟任务最多3个ETF、7个自然日，必须明确选择标的")
        task = {"id": uuid.uuid4().hex, "kind": kind, "status": "pending", "progress": 0,
                "message": "等待执行", "created_at": self.clock().isoformat(), "finished_at": None,
                "start": start.isoformat(), "end": end.isoformat(), "codes": selected,
                "errors": [], "count": 0, "interval": interval, "group": group, "asset_class": asset_class,
                "incremental": kind == "shares" and not explicit_start, "schedule_key": schedule_key,
                "scope": kind if kind in ("catalogue", "shares") else "minute" if minute else "quotes" if quotes_only else "full"}
        with self.lock:
            if kind in ("catalogue", "shares", "calendar"):
                for existing in self.repository.documents("tasks", limit=10000):
                    if existing.get("status") in ("pending", "running") and all(existing.get(key) == task.get(key) for key in
                            ("kind", "start", "end", "codes", "scope", "group", "asset_class", "schedule_key")):
                        return existing
            if self.stop_event.is_set():
                raise RuntimeError("任务服务已关闭")
            if self.pending.full():
                raise OverflowError("任务队列已满，请稍后重试")
            self.repository.put_document("tasks", task["id"], task)
            self.cancel_events[task["id"]] = threading.Event()
            self.pending.put_nowait(task["id"])
        return task

    def cancel(self, identifier):
        """功能：幂等取消；输入：任务ID；输出：是否存在。"""
        with self.lock:
            task = self.repository.document("tasks", identifier)
            if not task:
                return False
            if task["status"] in ("pending", "running"):
                event = self.cancel_events.get(identifier)
                if event:
                    event.set()
                task.update(status="cancelled", message="已取消；已安全提交的分市结果保留，后续结果不再提交" if task.get("kind") in ("shares", "catalogue") else "已取消；未提交采集结果", finished_at=self.clock().isoformat())
                self.repository.put_document("tasks", identifier, task)
            return True

    def _update(self, identifier, **values):
        """功能：互斥更新任务状态；输入：ID与变更；输出：当前任务。"""
        with self.lock:
            task = self.repository.document("tasks", identifier)
            if task["status"] == "cancelled":
                raise TaskInterrupted("已取消")
            task.update(values)
            self.repository.put_document("tasks", identifier, task)
            return task

    def _check(self, event, deadline):
        """功能：校验执行预算；输入：取消事件与单调截止；输出：无或中断异常。"""
        if self.stop_event.is_set() or event.is_set():
            raise TaskInterrupted("已取消")
        if time.monotonic() >= deadline:
            raise TimeoutError("任务执行超时")

    def _invoke(self, identifier, name, args, event, deadline, *, callback=None):
        """功能：隔离外部阻塞并保证互斥；输入：方法及预算；输出：源结果或真实异常。"""
        result = queue.Queue(maxsize=1)

        def call():
            """功能：执行注入源；输入：闭包方法参数；输出：结果进入队列。"""
            try:
                result.put((True, (callback or getattr(self.provider, name))(*args)))
            except Exception as exc:
                result.put((False, exc))

        caller = threading.Thread(target=call, daemon=True, name="etf-provider-call")
        caller.start()
        while caller.is_alive():
            try:
                self._check(event, deadline)
            except (TaskInterrupted, TimeoutError) as exc:
                if isinstance(exc, TimeoutError):
                    self._update(identifier, status="timeout", message=str(exc), error=str(exc), finished_at=self.clock().isoformat())
                    self._source(name, False, str(exc))
                # 无法安全终止Python线程。状态立即可见，保持单worker互斥直至外部有界调用结束。
                while caller.is_alive() and not self.stop_event.wait(.05):
                    pass
                raise
            caller.join(timeout=.05)
        self._check(event, deadline)
        success, value = result.get_nowait()
        if not success:
            raise value
        if not isinstance(value, list):
            raise ValueError(f"{name}返回非列表，违背provider契约")
        return value

    def _source(self, source, success, message="", count=0):
        """功能：保存源健康与本地故障告警；输入：状态和消息；输出：无。"""
        previous = self.repository.document("sources", source) or {}
        state = {"source": source, "status": "ok" if success and count else "empty" if success else "error",
                 "last_success": self.clock().isoformat() if success and count else previous.get("last_success"),
                 "checked_at": self.clock().isoformat(), "error": "" if success else message,
                 "message": message or ("有效空结果" if success and count == 0 else "采集成功"), "count": count}
        self.repository.put_document("sources", source, state)
        if not success:
            self.alert("", "source_error", "error", f"{source}数据源失败", message, source)

    def alert(self, code, kind, severity, title, message, suffix=""):
        """功能：发送带冷却去重的本地告警；输入：业务信息；输出：是否新建。"""
        value = {"id": uuid.uuid4().hex, "code": code, "kind": kind, "severity": severity,
                 "title": title, "message": message, "created_at": self.clock().isoformat(), "acknowledged": False}
        return self.repository.emit_alert(value, f"{code}:{kind}:{suffix}", self.settings.alert_cooldown_seconds)

    def _work(self):
        """功能：串行消费任务；输入：内部队列；输出：持久化状态和原子业务写入。"""
        while not self.stop_event.is_set():
            try:
                identifier = self.pending.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                self._execute(identifier)
            except TaskInterrupted:
                pass
            except Exception as exc:
                task = self.repository.document("tasks", identifier)
                if task and task["status"] not in ("cancelled", "timeout"):
                    self._update(identifier, status="timeout" if isinstance(exc, TimeoutError) else "failed", message=str(exc), error=str(exc), finished_at=self.clock().isoformat())
                    self.alert("", "task_error", "error", "后台任务失败", str(exc), task["kind"])
            finally:
                with self.lock:
                    self.cancel_events.pop(identifier, None)
                self.pending.task_done()

    def _execute(self, identifier):
        """功能：构建采集计划并原子提交；输入：任务ID；输出：任务完成状态。"""
        from datetime import date
        task = self._update(identifier, status="running", message="正在采集", started_at=self.clock().isoformat())
        event = self.cancel_events[identifier]
        deadline = time.monotonic() + self.task_timeout
        start, end = date.fromisoformat(task["start"]), date.fromisoformat(task["end"])
        if task["kind"] in ("shares", "catalogue"):
            return self._execute_shares_mainline(task, start, end, event, deadline)
        etfs = [item for item in self.repository.etfs() if item.code in task["codes"]]
        plan = []
        kind = task["kind"]
        if task.get("scope") == "minute":
            plan.extend(("bars", (etf, start, end, task["interval"])) for etf in etfs)
        elif kind == "refresh" and task.get("scope") == "quotes":
            plan.append(("quotes", (etfs,)))
        elif kind in ("refresh", "backfill"):
            # 完整刷新和回补必须自行闭环日历，不要求用户先手工初始化。
            plan.append(("calendar", (start, end)))
            plan.append(("shares", (start, end, etfs)))
            if kind == "refresh":
                plan.append(("quotes", (etfs,)))
            for etf in etfs:
                plan.extend([("bars", (etf, start, end)), ("navs", (etf, start, end))])
            plan.append(("market", (start, end)))
        elif kind == "holders":
            plan.extend(("holders", (etf,)) for etf in etfs)
        else:
            plan.append((kind, (start, end)))
        batches, errors, calendar = {}, [], None
        for index, (name, args) in enumerate(plan):
            self._check(event, deadline)
            try:
                records = self._invoke(identifier, name, args, event, deadline)
                if name == "calendar":
                    if any(not isinstance(day, date) or not start <= day <= end for day in records):
                        raise ValueError("日历源返回非法或区间外日期")
                    calendar = records
                else:
                    # 提前校验可见失败；整批写入前不允许未规范模型混入。
                    from ..storage.repository import RECORD_MODELS
                    records = [RECORD_MODELS[name].model_validate(record.model_dump() if hasattr(record, "model_dump") else record) for record in records]
                    if task.get("scope") == "minute" and len(records) > 1680:
                        raise ValueError("分钟源单标的返回超过7日×240条的有界上限")
                    allowed_codes = {item.code for item in etfs}
                    for record in records:
                        if not record.source.strip() or len(record.source) > 200 or (hasattr(record, "code") and not record.code.isascii()):
                            raise ValueError("源返回缺失来源或非法代码")
                        if hasattr(record, "code") and record.code not in allowed_codes:
                            raise ValueError("源返回非请求标的")
                        record_date = getattr(record, "trade_date", None)
                        if record_date and not start <= record_date <= end:
                            raise ValueError("源返回区间外日期")
                        stamp = getattr(record, "time", getattr(record, "quote_time", None))
                        if stamp and stamp.date() > self.clock().date():
                            raise ValueError("源返回未来行情")
                        if name == "bars" and not start <= record.time.date() <= end:
                            raise ValueError("源返回区间外K线")
                        if name == "bars" and record.interval != task.get("interval", "day"):
                            raise ValueError("源返回K线周期与任务请求不匹配")
                        if name == "bars" and record.interval != "day" and record.time > self.clock():
                            raise ValueError("源返回尚未发生的分钟K线")
                        if name == "holders" and (record.report_date > self.clock().date() or (record.published_on and record.published_on > self.clock().date())):
                            raise ValueError("源返回未来持有人报告")
                        if self.settings.mode == "live" and record.quality == "demo":
                            raise ValueError("真实模式禁止写入演示源记录")
                    batches.setdefault(name, []).extend(records)
                self._source(name, True, count=len(records))
                for source in {record.source for record in records if hasattr(record, "source")}:
                    self._source(source, True, count=sum(record.source == source for record in records))
            except (TaskInterrupted, TimeoutError):
                raise
            except Exception as exc:
                source = getattr(exc, "source", name)
                if getattr(exc, "status", "error") == "empty":
                    self._source(source, True, str(exc), count=0)
                else:
                    message = f"{name}: {exc}"
                    errors.append({"source": source, "message": message})
                    self._source(source, False, message)
            self._update(identifier, progress=round((index + 1) / max(1, len(plan)) * 90),
                         message=f"完成 {index + 1}/{len(plan)} 个采集步骤", errors=errors)
        for source in {error["source"] for error in errors}:
            self._source(source, False, "；".join(error["message"] for error in errors if error["source"] == source))
        with self.lock:
            self._check(event, deadline)
            calendar_request = (start, end, getattr(self.provider, "source", "provider.calendar")) if calendar is not None else None
            changed = self.repository.save_records(batches, self.clock(), calendar=calendar, calendar_request=calendar_request)
            total = sum(map(len, batches.values())) + len(calendar or [])
            status = "partial" if errors and total else "failed" if errors else "empty" if total == 0 else "completed"
            self._update(identifier, status=status, progress=100, count=total, changed=changed,
                         message="；".join(error["message"] for error in errors) if errors else "有效空结果" if total == 0 else "采集完成",
                         errors=errors, finished_at=self.clock().isoformat())
        self.check_share_alerts(etfs)

    def _execute_shares_mainline(self, task, start, end, event, deadline):
        """功能：逐市短窗口独立提交目录或纯份额；输入：任务、边界和预算；输出：终态，失败不丢已提交数据。"""
        from datetime import date
        from ..models import ETF, ShareRecord
        identifier, kind = task["id"], task["kind"]
        errors, results, changed, count = [], [], 0, 0
        if kind == "shares":
            etfs = [item for item in self.repository.catalogue(classification_status="confirmed", enabled=True,
                    group=task.get("group"), asset_class=task.get("asset_class"), limit=5000) if item.code in task["codes"]]
            if not etfs:
                raise ValueError("执行时目录没有仍确认且启用的请求成员")
            # 日历先闭环；未知或失败时不猜工作日、不继续份额采集。
            if not self.repository.calendar_covers(start, end):
                try:
                    days = self._invoke(identifier, "calendar", (start, end), event, deadline)
                    if any(type(day) is not date or not start <= day <= end for day in days):
                        raise ValueError("日历源返回非法或区间外日期")
                    with self.lock:
                        self._check(event, deadline)
                        self.repository.save_calendar(days, start=start, end=end,
                            source=getattr(self.provider, "source", "provider.calendar"), fetched_at=self.clock())
                    self._source("calendar", True, count=len(days))
                except (TaskInterrupted, TimeoutError):
                    raise
                except Exception as exc:
                    self._source(getattr(exc, "source", "calendar"), False, str(exc))
                    raise ValueError(f"交易日历未闭环，停止纯份额采集：{exc}") from exc
        else:
            etfs = []
        plan = []
        for exchange in ("sh", "sz"):
            members = [item for item in etfs if item.exchange == exchange]
            if kind == "catalogue":
                plan.append((exchange, end, end, []))
                continue
            if not members:
                continue
            left = start
            if task.get("incremental"):
                latest = self.repository.share_latest_dates([item.code for item in members], end)
                left = min(max(start, latest[item.code] - timedelta(days=7)) if item.code in latest else start for item in members)
            while left <= end:
                right = min(end, left + timedelta(days=6))
                window_members = [item for item in members if item.listed_on is None or right >= item.listed_on]
                if window_members and self.repository.calendar_days(start=left, end=right):
                    plan.append((exchange, left, right, window_members))
                left = right + timedelta(days=1)
        for index, (exchange, left, right, members) in enumerate(plan):
            self._check(event, deadline)
            source = f"{kind}.{exchange}"
            try:
                if kind == "catalogue":
                    if hasattr(self.provider, "catalogue"):
                        callback = self.provider.catalogue
                    else:
                        from ..providers.catalogue import fetch_catalogue
                        def callback(as_of, market):
                            """功能：调用逐市目录契约；输入：截止日、交易所；输出：规范目录列表。"""
                            return fetch_catalogue(self.provider, as_of, exchange=market)
                    values = self._invoke(identifier, source, (end, exchange), event, deadline, callback=callback)
                    values = [ETF.model_validate(item.model_dump() if hasattr(item, "model_dump") else item) for item in values]
                    if len(values) > 5000:
                        raise ValueError("目录源响应超过5000上限")
                    for item in values:
                        if item.exchange != exchange or not item.code.isascii() or not ((exchange == "sh" and item.code.startswith(("5", "6"))) or (exchange == "sz" and item.code.startswith("1"))):
                            raise ValueError("目录源代码与请求交易所不匹配")
                        if not item.catalogue_source or not item.catalogue_source.strip() or item.discovered_at is None or item.discovered_at.tzinfo is None or item.discovered_at > self.clock():
                            raise ValueError("目录缺少来源或有效发现时刻")
                        if self.settings.mode == "live" and item.catalogue_source.startswith("demo"):
                            raise ValueError("真实模式禁止演示目录")
                    with self.lock:
                        self._check(event, deadline)
                        batch_changed = self.repository.sync_catalogue(values)
                else:
                    values = self._invoke(identifier, source, (left, right, members), event, deadline, callback=self.provider.shares)
                    if len(values) > len(members) * 7 * 4:
                        raise ValueError("份额源单窗口响应超过有界上限")
                    values = [ShareRecord.model_validate(item.model_dump() if hasattr(item, "model_dump") else item) for item in values]
                    allowed = {item.code for item in members}
                    identities = set()
                    trading_days = set(self.repository.calendar_days(start=left, end=right))
                    for item in values:
                        identity = (item.code, item.trade_date, item.source)
                        if identity in identities:
                            raise ValueError("份额源返回重复业务键")
                        identities.add(identity)
                        if item.trade_date not in trading_days:
                            raise ValueError("份额源返回非已确认交易日记录")
                        if item.code not in allowed or not item.code.isascii() or not left <= item.trade_date <= right:
                            raise ValueError("份额源返回非请求成员或区间外日期")
                        if not item.source.strip() or len(item.source) > 200 or item.fetched_at > self.clock():
                            raise ValueError("份额来源或采集时刻非法")
                        if self.settings.mode == "live" and item.quality == "demo":
                            raise ValueError("真实模式禁止写入演示份额")
                    with self.lock:
                        self._check(event, deadline)
                        batch_changed = self.repository.save_records({"shares": values}, self.clock())
                changed += batch_changed
                count += len(values)
                results.append({"exchange": exchange, "start": str(left), "end": str(right), "status": "ok" if values else "empty", "count": len(values), "changed": batch_changed})
                self._source(source, True, count=len(values))
                if kind == "catalogue":
                    batch_sources = {getattr(item, "catalogue_source", None) for item in values} - {None}
                else:
                    batch_sources = {item.source for item in values}
                if not values:
                    raise ValueError("交易日请求返回空结果，不能标记日更成功")
                if kind == "shares":
                    expected = self.repository.calendar_days(start=left, end=right)[-1]
                    available = {(item.code, item.trade_date) for item in values if item.quality in ("valid", "demo")}
                    required = {(member.code, day) for member in members for day in trading_days
                                if member.listed_on is None or day >= member.listed_on}
                    if not required.issubset(available):
                        raise ValueError(f"窗口交易日缺少{len(required - available)}个有效成员日记录（末日{expected}）；已保存可用记录")
                for actual_source in batch_sources:
                    self._source(actual_source, True, count=len(values))
            except (TaskInterrupted, TimeoutError):
                raise
            except Exception as exc:
                actual_source = getattr(exc, "source", source)
                message = f"{exchange} {left}~{right}: {exc}"
                errors.append({"exchange": exchange, "start": str(left), "end": str(right), "source": actual_source, "message": message})
                results.append({"exchange": exchange, "start": str(left), "end": str(right), "status": "error", "message": message})
                self._source(actual_source, False, message)
            self._update(identifier, progress=round((index + 1) / max(1, len(plan)) * 90),
                         count=count, changed=changed, errors=errors, exchanges=results,
                         message=f"已安全处理{index + 1}/{len(plan)}个分市窗口")
        for failed_source in {item["source"] for item in errors}:
            self._source(failed_source, False, "；".join(item["message"] for item in errors if item["source"] == failed_source))
        with self.lock:
            self._check(event, deadline)
            status = "partial" if errors and count else "failed" if errors else "completed" if count or not plan else "empty"
            if status == "completed" and kind == "shares":
                self.repository.put_document("metadata", "shares_last_success", {"date": str(end),
                    "task_id": identifier, "codes": task["codes"], "completed_at": self.clock().isoformat()})
            if status == "completed" and task.get("schedule_key"):
                self.repository.put_document("metadata", "schedule_success:" + task["schedule_key"],
                    {"key": task["schedule_key"], "date": str(end), "kind": kind, "task_id": identifier, "completed_at": self.clock().isoformat()})
            self._update(identifier, status=status, progress=100, count=count, changed=changed,
                         errors=errors, exchanges=results, finished_at=self.clock().isoformat(),
                         message="；".join(item["message"] for item in errors) if errors else "分市采集并提交完成" if plan else "日历确认区间内无交易日")
        if kind == "shares":
            self.check_share_alerts(etfs)

    def check_share_alerts(self, etfs):
        """功能：只对相邻已核交易日有效份额告警；输入：目录成员；输出：日变化或异常提示。"""
        for etf in etfs:
            records = self.repository.records("shares", etf.code, end=self.clock().date(), limit=100, newest=True)
            if not records:
                continue
            latest = records[0]
            if latest.quality not in ("valid", "demo"):
                continue
            days = self.repository.calendar_days(end=latest.trade_date)
            if len(days) < 2 or days[-1] != latest.trade_date or not self.repository.calendar_covers(days[-2], latest.trade_date):
                continue
            previous = next((record for record in records if record.trade_date == days[-2] and record.source == latest.source), None)
            if not previous or previous.quality not in ("valid", "demo") or previous.shares <= 0:
                continue
            ratio = latest.shares / previous.shares
            if ratio >= 2 or ratio <= .5:
                self.alert(etf.code, "share_anomaly", "warning", "ETF份额异常跳变待核验",
                           f"{latest.trade_date} 与{previous.trade_date}份额比{ratio:.3f}，可能拆分/合并或大额申赎，不直接认定资金流。", str(latest.trade_date))
                continue
            change = (ratio - 1) * 100
            if abs(change) >= self.settings.shares_alert_pct:
                self.alert(etf.code, "share_change", "warning", "ETF相邻交易日份额变化超过阈值",
                           f"{previous.trade_date}→{latest.trade_date} 份额变化 {change:.2f}%；来源 {latest.source}，不代表实时申赎或机构身份", str(latest.trade_date))

    def schedule_once(self):
        """功能：18:17纯份额日更及次日有限核对；输入：真实时钟和持久结果；输出：是否入队，入队不等于成功。"""
        if not self.settings.scheduler_enabled or self.settings.mode != "live":
            return False
        now = self.clock()
        minutes = now.hour * 60 + now.minute
        daily_minute = self.settings.daily_update_hour * 60 + self.settings.daily_update_minute
        intraday = self.settings.intraday_enabled and (570 <= minutes <= 690 or 780 <= minutes <= 900)
        with self.lock:
            if any(task.get("status") in ("pending", "running") for task in self.repository.documents("tasks", limit=10000)):
                return False
            # 明确覆盖之前只安排有界日历闭环，不用weekday伪造交易日。
            if not self.repository.calendar_covers(now.date() - timedelta(days=40), now.date()):
                if minutes < 540 or minutes > 1380:
                    return False
                return self._schedule_bounded("calendar", now.date(), "calendar:" + str(now.date()),
                                              start=now.date() - timedelta(days=40))
            if intraday and self.repository.is_trading_day(now.date()):
                if self.last_scheduled and (now - self.last_scheduled).total_seconds() < self.settings.quote_interval:
                    return False
                self.submit("refresh", quotes_only=True)
                self.last_scheduled = now
                return True
            if daily_minute <= minutes <= 1380:
                if not self.repository.is_trading_day(now.date()):
                    return False
                target, phase = now.date(), "daily"
            elif 540 <= minutes < 720:
                days = self.repository.calendar_days(end=now.date() - timedelta(days=1))
                if not days or (now.date() - days[-1]).days > 7:
                    return False
                target, phase = days[-1], "verify"
            else:
                return False
            # 每日发现先执行；失败重试次数用尽后仍允许已有确认目录采份额。
            for kind in ("catalogue", "shares"):
                key = f"{phase}:{now.date()}:{target}:{kind}"
                if self.repository.document("metadata", "schedule_success:" + key):
                    continue
                if self._schedule_bounded(kind, target, key):
                    return True
            return False

    def _schedule_bounded(self, kind, end, key, start=None):
        """功能：持久化调度尝试及退避；输入：任务类型、业务日、幂等键；输出：是否成功入队，不写业务成功标记。"""
        from datetime import datetime
        now = self.clock()
        attempts = self.repository.document("metadata", "schedule_attempt:" + key) or {"attempts": 0}
        if attempts["attempts"] >= 3:
            return False
        if attempts.get("last_attempt") and (now - datetime.fromisoformat(attempts["last_attempt"])).total_seconds() < 900:
            return False
        try:
            self.submit(kind, start=start, end=end, schedule_key=key)
        except ValueError as exc:
            self.alert("", "scheduler_error", "warning", "日更任务尚不可执行", str(exc), key)
            # 目录暂无成员同样有限重试，避免秒级告警与无限尝试。
            self.repository.put_document("metadata", "schedule_attempt:" + key,
                {"attempts": attempts["attempts"] + 1, "last_attempt": now.isoformat(), "error": str(exc)})
            return False
        self.repository.put_document("metadata", "schedule_attempt:" + key,
            {"attempts": attempts["attempts"] + 1, "last_attempt": now.isoformat()})
        self.last_scheduled = now
        return True

    def _schedule(self):
        """功能：可关闭本地日历轮询；输入：内部事件；输出：按配置有限任务。"""
        while not self.stop_event.wait(1):
            try:
                self.schedule_once()
            except Exception as exc:
                self.alert("", "scheduler_error", "error", "调度失败", str(exc))
