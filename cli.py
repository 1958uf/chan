"""多策略统一 CLI。

功能：选择策略 + 参数 + 数据源，运行策略或回测。
设计：通过 Strategies.registry 按名称查找策略，DataBasis 获取数据，Backtest 引擎回测。
依赖：DataBasis、Strategies.registry/base、Backtest.engine。
使用：
    python cli.py --strategy example_ma --code sh.600008 --data-src sqlite --backtest
    python cli.py --strategy chan --code sh.600008 --data-src sqlite --backtest
    python cli.py --list
"""
import argparse
import sys
from typing import Optional

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from DataBasis.data_factory import create_data_api
from Strategies.registry import get_strategy, list_strategies


def _parse_args(argv=None):
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="多策略统一 CLI")
    parser.add_argument("--list", action="store_true", help="列出已注册策略")
    parser.add_argument("--strategy", type=str, default="example_ma", help="策略名称")
    parser.add_argument("--code", type=str, default="sh.600008", help="股票代码")
    parser.add_argument("--data-src", type=str, default="sqlite",
                        choices=["baostock", "akshare", "ccxt", "csv", "sqlite"], help="数据源")
    parser.add_argument("--k-type", type=str, default="K_DAY", help="K 线级别（如 K_DAY/K_60M）")
    parser.add_argument("--begin", type=str, default=None, help="起始日期")
    parser.add_argument("--end", type=str, default=None, help="结束日期")
    parser.add_argument("--autype", type=str, default="qfq", choices=["qfq", "hfq", "none"], help="复权方式")
    parser.add_argument("--cash", type=float, default=100000.0, help="初始资金（回测）")
    parser.add_argument("--backtest", action="store_true", help="运行回测")
    return parser.parse_args(argv)


def _data_src_from_str(s: str) -> DATA_SRC:
    """字符串 -> DATA_SRC 枚举。"""
    return {
        "baostock": DATA_SRC.BAO_STOCK,
        "akshare": DATA_SRC.AKSHARE,
        "ccxt": DATA_SRC.CCXT,
        "csv": DATA_SRC.CSV,
        "sqlite": DATA_SRC.SQLITE,
    }[s]


def _autype_from_str(s: str) -> AUTYPE:
    """字符串 -> AUTYPE 枚举。"""
    return {"qfq": AUTYPE.QFQ, "hfq": AUTYPE.HFQ, "none": AUTYPE.NONE}[s]


def _ktype_from_str(s: str) -> KL_TYPE:
    """字符串 -> KL_TYPE 枚举。"""
    return KL_TYPE[s.upper()]


def main(argv=None) -> int:
    """CLI 主入口。
    功能：解析参数，按策略名称查找并运行/回测
    输入：argv - 命令行参数（None 时取 sys.argv）
    输出：退出码
    """
    args = _parse_args(argv)

    if args.list:
        print("已注册策略：")
        for name, cls in list_strategies().items():
            print(f"  {name}: {cls.__doc__ or cls.__name__}")
        return 0

    data_src = _data_src_from_str(args.data_src)
    autype = _autype_from_str(args.autype)
    k_type = _ktype_from_str(args.k_type)

    # 查找策略类
    strategy_cls = get_strategy(args.strategy)

    # 构造策略实例
    strategy = strategy_cls(
        code=args.code,
        k_type=k_type,
        begin_date=args.begin,
        end_date=args.end,
        data_src=data_src,
        autype=autype,
    )

    if not args.backtest:
        print(f"策略 {args.strategy} 已创建，使用 --backtest 运行回测")
        return 0

    # 回测：获取数据 + 运行引擎
    from Backtest.engine import run_backtest

    api_cls = create_data_api(data_src)
    api_cls.do_init()
    try:
        api = api_cls(code=args.code, k_type=k_type, begin_date=args.begin,
                      end_date=args.end, autype=autype)
        data_iter = api.get_kl_data()
        result = run_backtest(strategy, data_iter, initial_cash=args.cash)
    finally:
        api_cls.do_close()

    print(result.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
