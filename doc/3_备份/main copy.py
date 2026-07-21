from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.AnimatePlotDriver import CAnimateDriver
from Plot.PlotDriver import CPlotDriver

if __name__ == "__main__":
    output_mode = "terminal"  # "plot" 或 "terminal"

    code = "sh.603688" #sz.
    begin_time = "2024-01-01"
    end_time = None
    data_src = DATA_SRC.BAO_STOCK #DATA_SRC.AKSHARE
    lv_list = [KL_TYPE.K_DAY]

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
        "seg": {
            # "plot_trendline": True,
        },
        "bi": {
            # "show_num": True,
            # "disp_end": True,
        },
        # "figure": {
        #     "x_range": 200,
        # },
        "marker": {
            # "markers": {  # text, position, color
            #     '2023/06/01': ('marker here', 'up', 'red'),
            #     '2023/06/08': ('marker here', 'down')
            # },
        }
    }
    chan = CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=data_src,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )

    if output_mode == "plot":
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
        # 终端模式：逐行打印K线与买卖点信息
        kl_data = chan[0]

        # 构建 klu.idx -> bsp 映射
        bsp_map = {}
        for bsp in kl_data.bs_point_lst.bsp_iter():
            bsp_map[bsp.klu.idx] = bsp

        # 构建笔末尾 klu.idx -> bi 映射（用于展示笔幅度）
        bi_end_map = {}
        for bi in kl_data.bi_list:
            bi_end_map[bi.get_end_klu().idx] = bi

        # 打印表头
        cols = f"{'时间':<12} {'股票':<8} {'开盘':>8} {'收盘':>8} {'最高':>8} {'最低':>8} {'涨跌幅':>8} {'状态':<4} {'买卖点':<8} {'笔向':<5} {'笔幅%':>7}"
        print(cols)
        print("-" * len(cols))

        for klc in kl_data:
            for klu in klc.lst:
                # 涨跌幅（当根K线 open->close）
                chg = (klu.close - klu.open) / klu.open * 100 if klu.open else 0

                # 涨跌停标记
                limit = {1: "涨停", -1: "跌停"}.get(klu.limit_flag, "-")

                # 买卖点：type2str() 返回如 "1","2","1p,2"，加 B/S 后缀
                if klu.idx in bsp_map:
                    bsp = bsp_map[klu.idx]
                    suffix = "B" if bsp.is_buy else "S"
                    bsp_str = bsp.type2str() + suffix
                else:
                    bsp_str = "No"

                # 笔信息（仅笔末尾K线显示）
                if klu.idx in bi_end_map:
                    bi = bi_end_map[klu.idx]
                    bi_dir = "UP" if bi.is_up() else "DN"
                    bi_amp = f"{bi.amp() * 100:.2f}"
                else:
                    bi_dir = "-"
                    bi_amp = "-"

                if bsp_str != "No":
                    print(
                        f"{str(klu.time):<12} {code:<8} "
                        f"{klu.open:>8.3f} {klu.close:>8.3f} "
                        f"{klu.high:>8.3f} {klu.low:>8.3f} "
                        f"{chg:>+7.2f}% {limit:<4} "
                        f"{bsp_str:<8} {bi_dir:<5} {bi_amp:>7}"
                    )
