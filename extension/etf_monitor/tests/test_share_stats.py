"""新纯份额统计测试，不提供NAV/行情且默认完全离线。"""
from datetime import date, datetime, timedelta

import pytest

from etf_monitor.analysis.shares import share_history, share_overview
from etf_monitor.models import ETF, ShareRecord
from etf_monitor.providers.base import SHANGHAI

NOW = datetime(2026, 4, 30, 17, tzinfo=SHANGHAI)
D1, D2, D3 = date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)


def etf(code="510300", **fields):
    """功能：构建向后兼容ETF样本；输入：代码和字段；输出：ETF模型。"""
    return ETF(code=code, name=code + "ETF", group="沪深300", exchange="sh", **fields)


def record(code, day, shares, quality="valid"):
    """功能：构造纯日份额模型；输入：代码、统计日、份额和质量；输出：ShareRecord。"""
    return ShareRecord(code=code, trade_date=day, shares=shares, quality=quality,
                       source="sse:shares", fetched_at=NOW)


def item(snapshot, code):
    """功能：检索单成员；输入：快照和代码；输出：成员字典。"""
    return next(row for row in snapshot["items"] if row["code"] == code)


def trading_days(start, count):
    """功能：固定模拟已知交易日历；输入：起始日和数量；输出：测试用交易日，不用于生产猜日历。"""
    days = []
    while len(days) < count:
        if start.weekday() < 5:
            days.append(start)
        start += timedelta(days=1)
    return days


def test_same_day_same_comparable_members_no_nav_price_needed():
    """功能：仅同日成员及可比首尾计算变化；输入：一成员缺基线、一成员缺末日；输出：同集合分母。"""
    etfs = [etf("510300"), etf("510310"), etf("510330")]
    records = [record("510300", D1, 100), record("510300", D2, 110),
               record("510310", D2, 1000), record("510330", D1, 200)]
    result = share_overview(etfs, records, [D1, D2], D2)
    group = result["groups"][0]
    assert group["total_shares"] == 1110
    assert group["delta_shares"] == 10
    assert group["delta_pct"] == pytest.approx(10)  # 不用全组1110或异日200当分母。
    assert group["total_count"] == 3 and group["available_count"] == 2
    assert group["comparable_count"] == 1 and group["missing_count"] == 1
    assert group["coverage_pct"] == pytest.approx(100 / 3)
    assert group["availability_pct"] == pytest.approx(200 / 3)
    assert group["quality"] == "partial"
    assert item(result, "510330")["shares"] is None
    assert item(result, "510330")["quality"] == "missing"
    assert item(result, "510310")["delta_shares"] is None
    assert all(row["trade_date"] == D2.isoformat() for row in result["items"])
    assert "NAV" in result["notice"] and "持有人" in result["notice"]


def test_candidates_unclassified_excluded_confirmed_aggregate():
    """功能：候选单列不参与确认总体；输入：相同组不同确认状态；输出：分母及存量仅confirmed。"""
    etfs = [etf(), etf("510310", classification_status="candidate"), etf("510330", classification_status="unclassified")]
    records = [record(product.code, day, value) for product in etfs for day, value in [(D1, 100), (D2, 110)]]
    result = share_overview(etfs, records, [D1, D2], D2)
    group = result["groups"][0]
    assert len(result["items"]) == 3
    assert group["total_shares"] == 110 and group["delta_shares"] == 10
    assert group["total_count"] == group["comparable_count"] == 1
    assert group["candidate_count"] == group["unclassified_count"] == 1
    assert result["coverage"]["candidate_count"] == 1
    assert group["quality"] == "valid"


def test_candidate_only_group_no_fake_zero_or_confirmed_count():
    """功能：仅候选组无确认总体；输入：候选份额；输出：None总量和明确候选数。"""
    result = share_overview([etf(classification_status="candidate")],
                            [record("510300", D1, 100), record("510300", D2, 110)], [D1, D2], D2)
    group = result["groups"][0]
    assert group["total_shares"] is None and group["delta_shares"] is None
    assert group["coverage_pct"] is None and group["total_count"] == 0
    assert group["candidate_count"] == 1


def test_new_etf_listing_not_in_comparable_set_and_not_before_listing():
    """功能：新上市成员存量单列，上市前不计分母；输入：新ETF；输出：不伪造新增申购。"""
    etfs = [etf(), etf("510310", listed_on=D2)]
    records = [record("510300", D1, 100), record("510300", D2, 110),
               record("510310", D1, 900), record("510310", D2, 1000)]
    result = share_overview(etfs, records, [D1, D2], D2)
    group = result["groups"][0]
    assert group["total_shares"] == 1110 and group["delta_shares"] == 10
    assert group["new_count"] == 1 and group["comparable_count"] == 1
    assert item(result, "510310")["delta_shares"] is None
    assert "新上市" in item(result, "510310")["reason"]
    previous = share_overview(etfs, records, [D1, D2], D1)
    assert previous["groups"][0]["total_count"] == 1


def test_delisted_member_is_explicit_exit_not_negative_flow():
    """功能：显式退出成员不当赎回；输入：真实ETF退出字段；输出：退出数和同可比变化。"""
    retired = etf("510310", delisted_on=D2)
    etfs = [etf(), retired]
    records = [record("510300", D1, 100), record("510300", D2, 110), record("510310", D1, 900)]
    group = share_overview(etfs, records, [D1, D2], D2)["groups"][0]
    assert group["total_shares"] == 110 and group["delta_shares"] == 10
    assert group["exited_count"] == 1 and group["total_count"] == 1


def test_exited_only_group_still_reports_exit():
    """功能：全部退出组不消失且不伪造负变化；输入：退出日；输出：空存量和退出数。"""
    retired = etf(delisted_on=D2)
    result = share_overview([retired], [record("510300", D1, 900)], [D1, D2], D2)
    assert result["items"] == []
    assert result["groups"][0]["exited_count"] == 1
    assert result["groups"][0]["total_shares"] is None
    assert result["groups"][0]["delta_shares"] is None


def test_missing_current_does_not_guess_exit_or_use_latest():
    """功能：缺末日不能猜退出或填旧值；输入：旧份额；输出：missing且分母保留。"""
    group = share_overview([etf()], [record("510300", D1, 900)], [D1, D2], D2)["groups"][0]
    assert group["total_shares"] is None and group["delta_shares"] is None
    assert group["exited_count"] == 0 and group["missing_count"] == 1
    assert group["total_count"] == 1 and group["coverage_pct"] == 0


@pytest.mark.parametrize("current", [200, 50, 1000, 10])
def test_suspected_split_not_counted_as_valid_change(current):
    """功能：两倍跳变提示未复权异常；输入：拆分/合并样本；输出：suspect不参与delta。"""
    result = share_overview([etf()], [record("510300", D1, 100), record("510300", D2, current)], [D1, D2], D2)
    row, group = result["items"][0], result["groups"][0]
    assert row["quality"] == "suspect" and row["delta_shares"] is None
    assert row["increase_streak"] == row["decrease_streak"] == 0
    assert "疑似拆分" in row["reason"]
    assert group["comparable_count"] == 0 and group["quality"] == "suspect"
    assert group["total_shares"] == current  # 原始日终存量保留，但不当可比变化。


def test_split_inside_long_window_invalidates_only_affected_window():
    """功能：5日路径拆分不能按首尾掩盖；输入：窗口内拆分后平稳；输出：日有效而5日suspect。"""
    days = trading_days(D1, 6)
    values = [100, 110, 220, 230, 240, 250]
    result = share_overview([etf()], [record("510300", day, value) for day, value in zip(days, values)], days, days[-1])
    row = result["items"][0]
    assert row["delta_shares"] == 10 and row["quality"] == "valid"
    assert row["delta_5d"] is None and row["quality_5d"] == "suspect"
    assert row["increase_streak"] == 3


def test_exact_5_20_trading_days_and_insufficient_windows():
    """功能：5/20使用交易日偏移而非自然日；输入：跨周日历；输出：准确变化与不足None。"""
    days = trading_days(D1, 21)
    records = [record("510300", day, 1000 + position * 10) for position, day in enumerate(days)]
    last = share_overview([etf()], records, days, days[-1])["items"][0]
    assert last["delta_shares"] == 10
    assert last["delta_5d"] == 50 and last["delta_20d"] == 200
    assert last["delta_20d_pct"] == 20
    assert last["increase_streak"] == 20 and last["decrease_streak"] == 0
    early = share_overview([etf()], records, days, days[4])["items"][0]
    assert early["delta_5d"] is None and early["delta_20d"] is None
    assert early["quality_5d"] == "partial"


def test_new_etf_5_20_windows_are_not_synthetic():
    """功能：不足上市交易日的窗口不计算；输入：提前记录的新ETF；输出：长窗口None。"""
    days = trading_days(D1, 21)
    records = [record("510300", day, 1000 + position * 10) for position, day in enumerate(days)]
    row = share_overview([etf(listed_on=days[-3])], records, days, days[-1])["items"][0]
    assert row["delta_shares"] == 10
    assert row["delta_5d"] is None and row["delta_20d"] is None
    assert row["increase_streak"] == 2  # 不能把上市前的错误样本算入连续增减。


def test_holiday_and_nontrading_as_of_are_calendar_aligned():
    """功能：真实日历跳过节日，不猜工作日；输入：节假日与周末；输出：同统计日与前交易日。"""
    before, after = date(2026, 4, 3), date(2026, 4, 7)
    records = [record("510300", before, 100), record("510300", after, 110)]
    result = share_overview([etf()], records, [before, after], date(2026, 4, 11))
    assert result["coverage"]["trade_date"] == after.isoformat()
    assert result["coverage"]["baseline_date"] == before.isoformat()
    assert result["items"][0]["delta_shares"] == 10


def test_calendar_missing_does_not_infer_from_records_or_weekdays():
    """功能：没有日历不由份额日期猜统计日；输入：日历空；输出：日期未知和明确提示。"""
    result = share_overview([etf()], [record("510300", D1, 100), record("510300", D2, 110)], [], D2)
    assert result["coverage"]["calendar_available"] is False
    assert result["items"][0]["shares"] is None
    assert result["coverage"]["trade_date"] is None
    assert "缺少真实交易日历" in result["notice"]


def test_daily_gap_breaks_streak_and_5d_window_without_old_fill():
    """功能：缺失交易日中断连续变化和长窗核验；输入：断档份额；输出：日有效、窗口partial。"""
    days = trading_days(D1, 6)
    records = [record("510300", day, 1000 + position * 10) for position, day in enumerate(days) if position != 2]
    row = share_overview([etf()], records, days, days[-1])["items"][0]
    assert row["delta_shares"] == 10 and row["increase_streak"] == 2
    assert row["delta_5d"] is None and row["quality_5d"] == "partial"
    assert "断档" in row["reason_5d"]


@pytest.mark.parametrize("values,increase,decrease", [([100, 110, 120], 2, 0), ([100, 90, 80], 0, 2),
    ([100, 100, 110], 1, 0), ([100, 110, 100], 0, 1), ([100, 110, 110], 0, 0)])
def test_continuous_change_streak_zero_and_reversal(values, increase, decrease):
    """功能：连续变化平值及反向截断；输入：三日序列；输出：增减次数。"""
    row = share_overview([etf()], [record("510300", day, value) for day, value in zip([D1, D2, D3], values)],
                         [D1, D2, D3], D3)["items"][0]
    assert row["increase_streak"] == increase and row["decrease_streak"] == decrease


def test_week_month_end_stocks_not_daily_sum():
    """功能：周月为期末存量而非日份额加总；输入：跨月跨周每日份额；输出：正确期末及前周期变化。"""
    days = [date(2026, 3, 27), date(2026, 3, 30), date(2026, 3, 31), D1, D2, D3,
            date(2026, 4, 7), date(2026, 4, 8), date(2026, 4, 9), date(2026, 4, 10)]
    records = [record("510300", day, 1000 + position * 10) for position, day in enumerate(days)]
    weeks = share_history([etf()], records, days, D1, days[-1], "week")
    assert [row["date"] for row in weeks] == [D3.isoformat(), "2026-04-10"]
    assert [row["total_shares"] for row in weeks] == [1050, 1090]
    assert [row["delta_shares"] for row in weeks] == [50, 40]
    assert weeks[0]["baseline_date"] == "2026-03-27"
    months = share_history([etf()], records, days, date(2026, 3, 30), days[-1], "month")
    assert [row["date"] for row in months] == ["2026-03-31", "2026-04-10"]
    assert [row["total_shares"] for row in months] == [1020, 1090]
    assert months[1]["delta_shares"] == 70 and months[1]["baseline_date"] == "2026-03-31"
    assert share_overview([etf()], records, days, days[-1], "month")["items"][0]["delta_shares"] == 70


def test_group_history_same_member_comparable_denominator():
    """功能：历史不使用全组存量差而用同集合；输入：新上市ETF；输出：期末存量与变化分开。"""
    etfs = [etf(), etf("510310", listed_on=D2)]
    records = [record("510300", D1, 100), record("510300", D2, 110), record("510310", D2, 1000)]
    rows = share_history(etfs, records, [D1, D2], D1, D2)
    assert rows[0]["total_count"] == 1 and rows[0]["delta_shares"] is None
    assert rows[1]["total_shares"] == 1110 and rows[1]["delta_shares"] == 10
    assert rows[1]["delta_pct"] == 10 and rows[1]["comparable_count"] == 1


def test_conflicting_duplicates_suspect_identical_duplicates_allowed():
    """功能：同日冲突不能取后覆盖前；输入：重复/冲突份额；输出：异常可见。"""
    records = [record("510300", D1, 100), record("510300", D2, 110)]
    same = share_overview([etf()], records + [records[-1]], [D1, D2], D2)
    assert same["items"][0]["delta_shares"] == 10
    conflict = share_overview([etf()], records + [record("510300", D2, 120), records[-1]], [D1, D2], D2)
    assert conflict["items"][0]["quality"] == "suspect"
    assert conflict["items"][0]["shares"] is None and conflict["groups"][0]["delta_shares"] is None


@pytest.mark.parametrize("quality", ["suspect", "missing", "error", "stale", "partial"])
def test_nonvalid_source_quality_not_comparable(quality):
    """功能：源质量非有效不可比；输入：带质量份额；输出：无伪造零或有效变化。"""
    records = [record("510300", D1, 100), record("510300", D2, 110, quality)]
    result = share_overview([etf()], records, [D1, D2], D2)
    assert result["items"][0]["shares"] is None and result["items"][0]["delta_shares"] is None
    assert result["groups"][0]["comparable_count"] == 0


def test_demo_quality_and_zero_denominator():
    """功能：演示标记保留，零基数百分比未知；输入：演示/零份额；输出：demo和None百分比。"""
    records = [record("510300", D1, 100, "demo"), record("510300", D2, 110, "demo")]
    result = share_overview([etf()], records, [D1, D2], D2)
    assert result["items"][0]["quality"] == result["groups"][0]["quality"] == "demo"
    zero = share_overview([etf()], [record("510300", D1, 0), record("510300", D2, 10)], [D1, D2], D2)
    assert zero["groups"][0]["delta_shares"] == 10
    assert zero["groups"][0]["delta_pct"] is None


def test_asset_group_identity_and_disabled_etf_excluded():
    """功能：资产类别同名组不混且禁用ETF不算成员；输入：跨类别字典；输出：独立分组。"""
    first = etf().model_dump()
    second = etf("510310", asset_class="风格").model_dump()
    disabled = etf("510330", enabled=False)
    records = [record(code, day, value) for code in ["510300", "510310", "510330"] for day, value in [(D1, 100), (D2, 110)]]
    result = share_overview([first, second, disabled], records, [D1, D2], D2)
    assert len(result["groups"]) == 2 and result["coverage"]["total_count"] == 2
    assert {group["asset_class"] for group in result["groups"]} == {"宽基", "风格"}


@pytest.mark.parametrize("frequency", ["day", "week", "month"])
def test_disabled_current_watch_member_keeps_existing_history(frequency):
    """功能：停用只改变当前观察，不删除日周月历史；输入：同份额停用前后ETF；输出：历史完全一致。"""
    product = etf(listed_on=D1)
    disabled = product.model_copy(update={"enabled": False})
    records = [record("510300", D1, 100), record("510300", D2, 110), record("510300", D3, 120)]
    expected = share_history([product], records, [D1, D2, D3], D1, D3, frequency)
    actual = share_history([disabled], records, [D1, D2, D3], D1, D3, frequency)
    assert actual == expected and actual
    assert actual[-1]["total_shares"] == 120
    current = share_overview([disabled], records, [D1, D2, D3], D3)
    assert current["items"] == [] and current["groups"] == []
    assert current["coverage"]["total_count"] == 0


def test_disabled_model_history_uses_real_exit_date_not_watch_switch():
    """功能：停用的已退市ETF仍保留退市前历史，退出日真实生效；输入：模型上市/退出日期；输出：正确在册分母。"""
    disabled = etf("510310", enabled=False, listed_on=D1, delisted_on=D3)
    records = [record("510300", D1, 100), record("510300", D2, 110), record("510300", D3, 120),
               record("510310", D1, 900), record("510310", D2, 910)]
    rows = share_history([etf(), disabled], records, [D1, D2, D3], D1, D3)
    assert [row["total_count"] for row in rows] == [2, 2, 1]
    assert [row["total_shares"] for row in rows] == [1000, 1020, 120]
    assert rows[1]["delta_shares"] == 20 and rows[1]["comparable_count"] == 2
    assert rows[2]["exited_count"] == 1 and rows[2]["delta_shares"] == 10
    assert rows[2]["delta_pct"] == pytest.approx(10 / 110 * 100)


def test_pure_inputs_not_mutated_and_generator_compatible():
    """功能：纯函数不修改输入且兼容迭代器；输入：字典与生成器；输出：稳定字典。"""
    product = etf().model_dump()
    raw = [record("510300", D1, 100).model_dump(), record("510300", D2, 110).model_dump()]
    expected_product = dict(product)
    result = share_overview(iter([product]), iter(raw), iter([D2, D1, D1]), D2)
    assert product == expected_product and result["items"][0]["delta_shares"] == 10
    assert "_baseline_shares" not in result["items"][0]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, None])
def test_invalid_raw_shares_marked_suspect(value):
    """功能：字典非法数值显式suspect；输入：模型外原始数据；输出：不产生非有限总量。"""
    raw = {"code": "510300", "trade_date": D2, "shares": value, "source": "test"}
    result = share_overview([etf()], [record("510300", D1, 100), raw], [D1, D2], D2)
    assert result["items"][0]["quality"] == "suspect"
    assert result["groups"][0]["total_shares"] is None


def test_future_records_ignored_and_no_calendar_outside_range():
    """功能：未来记录不能泄露到历史；输入：超出截止的记录和日历；输出：截止快照。"""
    result = share_overview([etf()], [record("510300", D1, 100), record("510300", D2, 110), record("510300", D3, 120)], [D1, D2, D3], D2)
    assert result["items"][0]["shares"] == 110 and result["items"][0]["trade_date"] == D2.isoformat()
    assert share_history([etf()], [], [], D1, D2) == []


@pytest.mark.parametrize("period", ["year", "", "DAY"])
def test_invalid_period_rejected(period):
    """功能：限制周期枚举；输入：非法周期；输出：ValueError。"""
    with pytest.raises(ValueError):
        share_overview([], [], [], D1, period)
    with pytest.raises(ValueError):
        share_history([], [], [], D1, D2, period)


def test_missing_previous_natural_period_not_using_older_calendar_latest():
    """功能：前自然周期无日历不能退到更早周期；输入：跨空月空周；输出：基线未知。"""
    days = [date(2026, 1, 30), D1]
    records = [record("510300", days[0], 100), record("510300", D1, 110)]
    for period in ("week", "month"):
        result = share_overview([etf()], records, days, D1, period)
        assert result["coverage"]["baseline_date"] is None
        assert result["items"][0]["delta_shares"] is None
        assert result["groups"][0]["quality"] == "partial"


def test_empty_calendar_filters_not_listed_and_already_exited_members():
    """功能：缺日历时仍按请求日在册分母，不将未来产品纳入；输入：未来/退出ETF；输出：仅在册成员。"""
    retired = etf("510330").model_dump()
    retired["delisted_on"] = D1
    result = share_overview([etf(), etf("510310", listed_on=D3), retired], [], [], D2)
    assert result["coverage"]["total_count"] == 1
    assert [row["code"] for row in result["items"]] == ["510300"]


def test_invalid_history_range_rejected():
    """功能：拒绝倒序历史范围；输入：逆序日期；输出：ValueError。"""
    with pytest.raises(ValueError):
        share_history([], [], [], D2, D1)
