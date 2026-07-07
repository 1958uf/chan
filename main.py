import os
import sys
import time

import baostock as bs

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataAPI.csvAPI import CSV_API
from Plot.AnimatePlotDriver import CAnimateDriver
from Plot.PlotDriver import CPlotDriver

# 本地 K 线缓存目录（存放 {code}_day.csv，供 /scan 增量复用）
_CACHE_DIR = "chan_cache"


def _bs_login(max_retry: int = 3) -> None:
    """带重试的 BaoStock 登录。
    功能：调用 bs.login() 并检查返回码，失败时最多重试 max_retry 次。
    输入：max_retry - 最大重试次数，默认 3
    输出：无（成功则返回，全部失败则抛 RuntimeError）
    """
    import time as _time
    for attempt in range(1, max_retry + 1):
        lg = bs.login()
        if lg.error_code == '0':
            return
        if attempt < max_retry:
            sys.stdout.write(f"\n  BaoStock 登录失败（第{attempt}次），2秒后重试 ...\n")
            sys.stdout.flush()
            _time.sleep(2)
    raise RuntimeError(f"BaoStock 登录失败，已重试 {max_retry} 次，请检查网络后重试。")


def _last_business_day():
    """返回最近一个已收盘的交易日（忽略节假日，仅排除周末）。
    若今天是工作日且已过 15:30（A股收盘），返回今天；否则返回上一个工作日。
    周一/周六/周日未收盘时返回上周五，周二~周五未收盘时返回昨天。
    """
    from datetime import date, datetime, timedelta
    today = date.today()
    now = datetime.now()
    wd = today.weekday()   # 0=周一 … 6=周日
    # 工作日且已过收盘时间，今天数据已可用
    if wd < 5 and (now.hour > 15 or (now.hour == 15 and now.minute >= 30)):
        return today
    if wd == 0:            # 周一未收盘 → 上周五
        return today - timedelta(days=3)
    elif wd == 6:          # 周日 → 上周五
        return today - timedelta(days=2)
    elif wd == 5:          # 周六 → 上周五
        return today - timedelta(days=1)
    else:                  # 周二~周五未收盘 → 昨天
        return today - timedelta(days=1)


def _needs_cache_update(code: str) -> bool:
    """检查股票缓存是否需要更新（文件不存在 or 最后一条数据日期 < 上一个交易日）"""
    cache_file = os.path.join(_CACHE_DIR, f"{code}_day.csv")
    if not os.path.exists(cache_file):
        return True
    with open(cache_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    if len(lines) <= 1:  # 只有标题行或空文件
        return True
    last_date_str = lines[-1].strip().split(',')[0]
    return last_date_str < _last_business_day().isoformat()


def _update_cache(code: str, begin_time: str) -> None:
    """增量（或全量）更新 chan_cache/{code}_day.csv。
    输入：
        code       - 归一化后的股票代码，如 sh.600519
        begin_time - 全量拉取的起始日期，如 "2024-01-01"
    输出：
        在 _CACHE_DIR 目录下写入/追加 {code}_day.csv（格式：time,open,high,low,close）
    """
    from datetime import date, timedelta

    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(_CACHE_DIR, f"{code}_day.csv")
    append = False
    start = begin_time

    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        if len(lines) > 1:
            last_date = lines[-1].strip().split(',')[0]
            start = (date.fromisoformat(last_date) + timedelta(days=1)).isoformat()
            append = True

    rs = bs.query_history_k_data_plus(
        code=code,
        fields="date,open,high,low,close",
        start_date=start,
        end_date=None,
        frequency='d',
        adjustflag='2',  # 前复权，与 AUTYPE.QFQ 对应
    )
    if rs.error_code != '0':
        raise Exception(rs.error_msg)

    mode = 'a' if append else 'w'
    with open(cache_file, mode, encoding='utf-8') as f:
        if not append:
            f.write("time,open,high,low,close\n")
        while rs.next():
            row = rs.get_row_data()
            # 跳过 OHLC 任一字段为空的行（停牌日 BaoStock 返回空字符串，会导致缠论计算越界）
            if any(v == '' for v in row[1:]):
                continue
            f.write(','.join(row) + '\n')


def _print_progress(i: int, total: int, code: str, start_time: float) -> None:
    """打印单行覆盖式进度条，显示百分比、当前股票代码和已用时间"""
    pct = i / total
    bar_w = 20
    filled = int(bar_w * pct)
    bar = '█' * filled + '░' * (bar_w - filled)
    elapsed = time.time() - start_time
    elapsed_str = time.strftime('%H:%M:%S', time.gmtime(elapsed))
    line = f"\r扫描进度: [{bar}] {pct*100:5.1f}% ({i:>3}/{total}) | {code:<12} | 已用 {elapsed_str}"
    sys.stdout.write(line)
    sys.stdout.flush()


def normalize_code(code: str) -> str:
    """自动识别并补全 baostock 股票代码前缀（sh./sz.）"""
    code = code.strip()
    if '.' in code:
        return code  # 已有前缀，直接返回
    if code.startswith('6'):
        return f"sh.{code}"   # 沪市：60xxxx / 68xxxx
    return f"sz.{code}"       # 深市：00xxxx / 30xxxx


def get_board(code: str) -> str:
    """根据归一化后的股票代码判断所属板块"""
    num = code.split('.')[-1]
    if num.startswith('688'):
        return 'kechuang'   # 科创板
    if num.startswith('300') or num.startswith('301'):
        return 'chuangye'   # 创业板
    if num.startswith('8'):
        return 'bse'        # 北交所
    return 'zhuban'         # 主板


def run_terminal_query(code, begin_time, end_time, data_src, lv_list, config):
    """对单只股票运行缠论计算并打印买卖点行"""
    chan = CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=data_src,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )
    kl_data = chan[0]
    bsp_map = {bsp.klu.idx: bsp for bsp in kl_data.bs_point_lst.bsp_iter()}
    bi_end_map = {bi.get_end_klu().idx: bi for bi in kl_data.bi_list}

    cols = f"{'时间':<12} {'股票':<10} {'开盘':>8} {'收盘':>8} {'最高':>8} {'最低':>8} {'涨跌幅':>8} {'状态':<4} {'买卖点':<8} {'笔向':<5} {'笔幅%':>7}"
    print(cols)
    print("-" * len(cols))

    for klc in kl_data:
        for klu in klc.lst:
            if klu.idx not in bsp_map:
                continue
            chg = (klu.close - klu.open) / klu.open * 100 if klu.open else 0
            limit = {1: "涨停", -1: "跌停"}.get(klu.limit_flag, "-")
            bsp = bsp_map[klu.idx]
            bsp_str = bsp.type2str() + ("B" if bsp.is_buy else "S")
            if klu.idx in bi_end_map:
                bi = bi_end_map[klu.idx]
                bi_dir = "UP" if bi.is_up() else "DN"
                bi_amp = f"{bi.amp() * 100:.2f}"
            else:
                bi_dir, bi_amp = "-", "-"
            print(
                f"{str(klu.time):<12} {code:<10} "
                f"{klu.open:>8.3f} {klu.close:>8.3f} "
                f"{klu.high:>8.3f} {klu.low:>8.3f} "
                f"{chg:>+7.2f}% {limit:<4} "
                f"{bsp_str:<8} {bi_dir:<5} {bi_amp:>7}"
            )


def _fetch_stock_names(codes: list) -> dict:
    """批量查询股票名称（需在 BaoStock 登录状态下调用）。
    输入：
        codes - 归一化代码列表，如 ['sh.600519', 'sz.000001']
    输出：
        {code: name} 字典，查询失败时对应 code 映射为空字符串
    """
    code_set = set(codes)
    name_map = {c: '' for c in codes}
    # 一次性拉取全市场基本信息，避免逐只查询导致 543 次 API 调用
    rs = bs.query_stock_basic()
    while rs.error_code == '0' and rs.next():
        row = rs.get_row_data()  # [code, code_name, ipoDate, outDate, stock_type, status]
        if row[0] in code_set:
            name_map[row[0]] = row[1]
    return name_map


def run_scan_pool(pool_file, begin_time, end_time, lv_list, config, days=30, board_filter=None):
    """批量扫描股票池，汇总输出近期有买点的股票"""
    from datetime import datetime, timedelta

    # 读取股票池
    if not os.path.exists(pool_file):
        print(f"股票池文件不存在：{pool_file}")
        print("请新建 stock_pool.txt，每行写一个股票代码（如 600150 或 sz.000001）")
        return

    codes = []
    with open(pool_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                codes.append(normalize_code(line))

    if not codes:
        print("股票池为空，请在 stock_pool.txt 中添加股票代码")
        return

    # 板块过滤
    _BOARD_NAME = {'zhuban': '主板', 'kechuang': '科创板', 'chuangye': '创业板', 'bse': '北交所'}
    if board_filter:
        codes = [c for c in codes if get_board(c) == board_filter]
        if not codes:
            print(f"股票池中无 {_BOARD_NAME.get(board_filter, board_filter)} 标的")
            return

    cutoff = (datetime.now() - timedelta(days=days)).date() if days > 0 else None
    tip = f"最近 {days} 天" if days > 0 else "全部历史"
    board_tip = f"，板块：{_BOARD_NAME.get(board_filter, board_filter)}" if board_filter else ""
    print(f"股票池共 {len(codes)} 只{board_tip}，扫描范围：{begin_time} 至今，买点时间：{tip}")
    print()

    # === 阶段1：增量更新本地 K 线缓存 + 查询股票名称 ===
    needs_update = [c for c in codes if _needs_cache_update(c)]
    name_map = {}
    if needs_update:
        print(f"需更新缓存：{len(needs_update)} 只（其余 {len(codes) - len(needs_update)} 只命中缓存）")
        _bs_login()
        try:
            for i, code in enumerate(needs_update, 1):
                sys.stdout.write(f"\r  缓存更新 [{i:>3}/{len(needs_update)}] {code:<12} ...")
                sys.stdout.flush()
                try:
                    _update_cache(code, begin_time)
                except Exception as e:
                    # 网络断连时自动重连一次再重试
                    if '10057' in str(e) or '网络' in str(e):
                        sys.stdout.write('\n')
                        sys.stdout.write("  网络断连，正在重连 BaoStock ...\n")
                        sys.stdout.flush()
                        try:
                            bs.logout()
                        except Exception:
                            pass
                        _bs_login()
                        try:
                            _update_cache(code, begin_time)
                        except Exception as e2:
                            print(f"  {code} 缓存失败（重连后）：{e2}")
                    else:
                        sys.stdout.write('\n')
                        print(f"  {code} 缓存失败：{e}")
            print(f"\r  缓存更新完成{' ' * 40}")
            # 登录期间顺带查询全部股票名称
            sys.stdout.write("  正在查询股票名称 ...")
            sys.stdout.flush()
            name_map = _fetch_stock_names(codes)
            sys.stdout.write(f"\r  股票名称查询完成{' ' * 30}\n")
        finally:
            bs.logout()
    else:
        print("全部命中本地缓存，正在查询股票名称 ...")
        _bs_login()
        try:
            name_map = _fetch_stock_names(codes)
        finally:
            bs.logout()
        print(f"股票名称查询完成")

    # === 阶段2：从本地 CSV 缓存计算缠论买卖点 ===
    CSV_API.base_dir = os.path.abspath(_CACHE_DIR)
    try:
        results = []
        start_time = time.time()
        for i, code in enumerate(codes, 1):
            _print_progress(i, len(codes), code, start_time)
            try:
                # 数据行数过少（退市/长期停牌），跳过避免缠论计算报错
                cache_file = os.path.join(_CACHE_DIR, f"{code}_day.csv")
                with open(cache_file, 'r', encoding='utf-8') as _f:
                    row_count = sum(1 for _ in _f) - 1  # 去掉标题行
                if row_count < 30:
                    continue
                chan = CChan(
                    code=code, begin_time=begin_time, end_time=end_time,
                    data_src=DATA_SRC.CSV, lv_list=lv_list, config=config,
                )
                kl_data = chan[0]
                for bsp in kl_data.bs_point_lst.bsp_iter():
                    if not bsp.is_buy:
                        continue
                    t = bsp.klu.time
                    bsp_date = datetime(t.year, t.month, t.day).date()
                    if cutoff and bsp_date < cutoff:
                        continue
                    results.append({
                        'code': code,
                        'name': name_map.get(code, ''),
                        'time': str(bsp.klu.time),
                        'close': bsp.klu.close,
                        'raw_type': bsp.type2str(),
                        'type': bsp.type2str() + 'B',
                    })
            except Exception as e:
                sys.stdout.write('\n')
                print(f"  {code} 失败：{e}")
    finally:
        CSV_API.base_dir = None  # 恢复默认，不影响单只查询

    _TYPE_ORDER = {'1': 0, '1p': 1, '2': 2, '2s': 3, '3a': 4, '3b': 5}
    results.sort(key=lambda r: (r['time'], _TYPE_ORDER.get(r['raw_type'], 99)))
    print(f"\n扫描完成，共找到 {len(results)} 个近期买点：\n")
    if results:
        cols = f"{'时间':<12} {'名称':<10} {'代码':<14} {'收盘价':>8} {'买点类型'}"
        print(cols)
        print("-" * 52)
        for r in results:
            print(f"{r['time']:<12} {r['name']:<10} {r['code']:<14} {r['close']:>8.3f} {r['type']}")
    else:
        print("（股票池中无近期买点）")


if __name__ == "__main__":
    output_mode = "terminal"  # "plot" 或 "terminal"

    code = "sh.603688"
    begin_time = "2024-01-01"
    end_time = None
    data_src = DATA_SRC.BAO_STOCK
    lv_list = [KL_TYPE.K_DAY]

    # scan 模式配置
    scan_pool_file = "stock_pool.txt"  # 股票池文件路径
    scan_days = 5                      # 只看最近 N 天的买点（0=全部历史）

    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": '1,2,3a,1p,2s,3b',
        "print_warning": True,
        "zs_algo": "normal",
    })

    plot_config = {
        "plot_kline": True,
        "plot_kline_combine": True,
        "plot_bi": True,
        "plot_seg": True,
        "plot_eigen": False,
        "plot_zs": True,
        "plot_macd": False,
        "plot_mean": False,
        "plot_channel": False,
        "plot_bsp": True,
        "plot_extrainfo": False,
        "plot_demark": False,
        "plot_marker": False,
        "plot_rsi": False,
        "plot_kdj": False,
    }

    plot_para = {
        "seg": {},
        "bi": {},
        # "figure": {"x_range": 200},
        "marker": {}
    }

    if output_mode == "plot":
        chan = CChan(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            data_src=data_src,
            lv_list=lv_list,
            config=config,
            autype=AUTYPE.QFQ,
        )
        if not config.trigger_step:
            plot_driver = CPlotDriver(
                chan,
                plot_config=plot_config,
                plot_para=plot_para,
            )
            plot_driver.figure.show()
            plot_driver.save2img("./test.png")
            import matplotlib.pyplot as plt
            plt.show()
        else:
            CAnimateDriver(
                chan,
                plot_config=plot_config,
                plot_para=plot_para,
            )
    else:
        print("缠论买卖点查询（直接回车查默认股票，/scan 选股，q 退出）")
        print(f"默认股票：{code}  起始：{begin_time}  股票池：{scan_pool_file}")
        while True:
            user_input = input("\n请输入代码：").strip()
            if user_input.lower() == 'q':
                print("退出。")
                break
            elif user_input.lower().startswith('/scan'):
                parts = user_input.lower().split()
                if '-clearcache' in parts:
                    import shutil
                    if os.path.exists(_CACHE_DIR):
                        shutil.rmtree(_CACHE_DIR)
                        print("缓存已清空，下次扫描将重新拉取全量数据。")
                    else:
                        print("无缓存目录，无需清理。")
                    continue
                board_filter = None
                if '-zhuban' in parts:
                    board_filter = 'zhuban'
                elif '-kechuang' in parts:
                    board_filter = 'kechuang'
                elif '-chuangye' in parts:
                    board_filter = 'chuangye'
                run_scan_pool(scan_pool_file, begin_time, end_time, lv_list, config, scan_days, board_filter)
            else:
                query_code = normalize_code(user_input if user_input else code)
                print(f"查询 {query_code} ...")
                try:
                    # 检查缓存是否需要更新
                    if _needs_cache_update(query_code):
                        print("本地无缓存或数据过期，正在从 BaoStock 拉取...")
                        bs.login()
                        try:
                            _update_cache(query_code, begin_time)
                        finally:
                            bs.logout()
                    else:
                        print("命中本地缓存，跳过网络请求。")
                    # 从本地 CSV 缓存读取并计算缠论
                    CSV_API.base_dir = os.path.abspath(_CACHE_DIR)
                    try:
                        run_terminal_query(query_code, begin_time, end_time, DATA_SRC.CSV, lv_list, config)
                    finally:
                        CSV_API.base_dir = None  # 恢复默认，不影响其他逻辑
                except Exception as e:
                    print(f"查询失败：{e}")
