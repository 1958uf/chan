import sys
import time

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.AnimatePlotDriver import CAnimateDriver
from Plot.PlotDriver import CPlotDriver


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


def run_scan_pool(pool_file, begin_time, end_time, data_src, lv_list, config, days=30, board_filter=None):
    """批量扫描股票池，汇总输出近期有买点的股票"""
    from datetime import datetime, timedelta

    # 读取股票池
    if not __import__('os').path.exists(pool_file):
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

    results = []
    start_time = time.time()
    for i, code in enumerate(codes, 1):
        _print_progress(i, len(codes), code, start_time)
        try:
            chan = CChan(
                code=code, begin_time=begin_time, end_time=end_time,
                data_src=data_src, lv_list=lv_list, config=config, autype=AUTYPE.QFQ,
            )
            kl_data = chan[0]
            for bsp in kl_data.bs_point_lst.bsp_iter():
                if not bsp.is_buy:
                    continue
                t = bsp.klu.time
                bsp_date = __import__('datetime').date(t.year, t.month, t.day)
                if cutoff and bsp_date < cutoff:
                    continue
                results.append({
                    'code': code,
                    'time': str(bsp.klu.time),
                    'close': bsp.klu.close,
                    'raw_type': bsp.type2str(),
                    'type': bsp.type2str() + 'B',
                })
        except Exception as e:
            sys.stdout.write('\n')
            print(f"  {code} 失败：{e}")

    _TYPE_ORDER = {'1': 0, '1p': 1, '2': 2, '2s': 3, '3a': 4, '3b': 5}
    results.sort(key=lambda r: (r['time'], _TYPE_ORDER.get(r['raw_type'], 99)))
    print(f"\n扫描完成，共找到 {len(results)} 个近期买点：\n")
    if results:
        cols = f"{'时间':<12} {'股票':<12} {'收盘价':>8} {'买点类型'}"
        print(cols)
        print("-" * 44)
        for r in results:
            print(f"{r['time']:<12} {r['code']:<12} {r['close']:>8.3f} {r['type']}")
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
            user_input = input("\n请输入股票代码：").strip()
            if user_input.lower() == 'q':
                print("退出。")
                break
            elif user_input.lower().startswith('/scan'):
                parts = user_input.lower().split()
                board_filter = None
                if '-zhuban' in parts:
                    board_filter = 'zhuban'
                elif '-kechuang' in parts:
                    board_filter = 'kechuang'
                elif '-chuangye' in parts:
                    board_filter = 'chuangye'
                run_scan_pool(scan_pool_file, begin_time, end_time, data_src, lv_list, config, scan_days, board_filter)
            else:
                query_code = normalize_code(user_input if user_input else code)
                print(f"查询 {query_code} ...")
                try:
                    run_terminal_query(query_code, begin_time, end_time, data_src, lv_list, config)
                except Exception as e:
                    print(f"查询失败：{e}")
