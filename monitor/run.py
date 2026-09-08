"""
监控脚本 CLI 入口

功能说明：
    - 提供两种运行模式：
        eod  : 盘后跑一次，用最新周线收盘价判定，输出后退出（可挂计划任务）
        live : 盘中常驻，每隔 interval 秒轮询，用实时现价判定，仅交易时段工作
    - 自动合并 config.yaml 的指数/个股 targets 与 watchlist.txt 的自选个股
    - 数据获取失败的单只标的不中断整体流程

用法：
    python -m monitor.run --mode eod
    python -m monitor.run --mode live --interval 300
    python -m monitor.run --mode eod --watchlist watchlist.txt
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

# 强制标准输出/错误按 UTF-8 编码，避免 Windows 默认 GBK 下
# 输出 ↑↓★↳ 等 Unicode 字符时抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - 不支持 reconfigure 的环境忽略
        pass
from datetime import datetime, time as dtime
from typing import List

import yaml

from . import alerts
from .data_source import get_realtime_prices, get_weekly_close
from .indicators import MaCheckResult, check_near_ma


# 配置默认路径（相对 monitor 包所在目录）
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "config.yaml")
_DEFAULT_WATCHLIST = os.path.join(_HERE, "watchlist.txt")


@dataclass
class Target:
    """监控标的。
    属性：code-代码 name-名称 kind-'index'/'stock'
    """
    code: str
    name: str
    kind: str


def load_config(path: str) -> dict:
    """加载 yaml 配置。
    功能：读取并返回配置字典
    输入：path - config.yaml 路径
    输出：配置字典
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_targets(config: dict, watchlist_path: str) -> List[Target]:
    """合并配置中的 targets 与 watchlist.txt 自选个股。
    功能：读取 config.targets + watchlist 文件，去重后返回 Target 列表
    输入：config - 配置字典；watchlist_path - 自选清单路径
    输出：Target 列表（指数在前，个股在后；已去重）
    """
    targets: List[Target] = []
    seen = set()

    # 配置中的标的（含指数与个股）
    for t in config.get("targets", []):
        code = str(t["code"]).strip()
        if code in seen:
            continue
        seen.add(code)
        targets.append(Target(code=code,
                              name=str(t.get("name", code)).strip(),
                              kind=str(t.get("kind", "stock")).strip()))

    # watchlist.txt 自选个股（自动补 kind=stock）
    if watchlist_path and os.path.exists(watchlist_path):
        with open(watchlist_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                code = line.split("#")[0].strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                targets.append(Target(code=code, name=code, kind="stock"))

    return targets


def _in_session(config: dict, now: datetime) -> bool:
    """判断当前是否在 A 股交易时段内。
    功能：按配置的 session 时段判断；周末直接返回 False
    输入：config - 配置字典；now - 当前时间
    输出：是否在交易时段
    """
    if now.weekday() >= 5:  # 周六周日
        return False
    s = config.get("session", {})
    cur = now.time()
    try:
        am_s = dtime.fromisoformat(s.get("morning_start", "09:30"))
        am_e = dtime.fromisoformat(s.get("morning_end", "11:30"))
        pm_s = dtime.fromisoformat(s.get("afternoon_start", "13:00"))
        pm_e = dtime.fromisoformat(s.get("afternoon_end", "15:00"))
    except (ValueError, TypeError):
        return True  # 时段配置异常时放行，避免漏报
    return (am_s <= cur <= am_e) or (pm_s <= cur <= pm_e)


def _scan_once(targets: List[Target], config: dict, use_realtime: bool) -> List[MaCheckResult]:
    """执行一次全标的扫描。
    功能：逐标的取周线 -> 取当前价 -> 判定接近均线 -> 收集结果
    输入：targets - 标的列表；config - 配置；use_realtime - 是否用实时价(盘军模式)
    输出：判定结果列表
    """
    period = int(config.get("ma_period", 50))
    threshold = float(config.get("threshold", 0.02))
    adjust = str(config.get("adjust", "qfq"))
    max_retry = int(config.get("max_retry", 3))

    # live 模式：一次性批量取实时价，减少请求次数
    rt_prices = {}
    if use_realtime:
        rt_prices = get_realtime_prices([t.code for t in targets],
                                        max_retry=max_retry)

    results: List[MaCheckResult] = []
    for t in targets:
        try:
            closes = get_weekly_close(t.code, kind=t.kind,
                                      adjust=adjust, max_retry=max_retry)
        except Exception as e:  # noqa: BLE001 - 单只失败不影响整体
            alerts.warn(f"取周线失败 {t.code}: {e}")
            results.append(MaCheckResult(t.code, t.name, None, None,
                                         None, False, None, reason=f"取周线失败:{e}"))
            continue

        if use_realtime:
            price = rt_prices.get(t.code)
        else:
            # eod 模式：当前价取最新一根周线收盘
            price = closes[-1] if closes else None

        results.append(check_near_ma(t.code, t.name, closes, price,
                                     period, threshold))
    return results


def run_eod(config: dict, targets: List[Target]) -> None:
    """盘后模式：跑一次后退出。
    功能：用最新周线收盘价扫描全部标的并输出
    输入：config - 配置；targets - 标的列表
    输出：无
    """
    alerts.info(f"盘后扫描开始 {datetime.now():%Y-%m-%d %H:%M} "
                f"MA{config.get('ma_period',50)} 阈值±{config.get('threshold',0.02)*100:.1f}%")
    results = _scan_once(targets, config, use_realtime=False)
    triggered = alerts.render_table(results)
    if triggered:
        print()
        alerts.info("★ 有标的接近均线，请关注！")
    else:
        alerts.info("本轮无标的接近均线。")


def run_live(config: dict, targets: List[Target], interval: int) -> None:
    """盘中模式：常驻轮询。
    功能：仅交易时段内每隔 interval 秒扫描一次，实时价判定
    输入：config - 配置；targets - 标的列表；interval - 轮询间隔(秒)
    输出：无（常驻直到 Ctrl+C）
    """
    alerts.info(f"盘中监控启动，每 {interval}s 轮询一次（仅交易时段）。Ctrl+C 退出。")
    try:
        while True:
            now = datetime.now()
            if not _in_session(config, now):
                # 非交易时段：每 60 秒检查一次是否开盘
                alerts.info(f"[{now:%H:%M:%S}] 非交易时段，等待中...")
                time.sleep(60)
                continue

            alerts.info(f"[{now:%H:%M:%S}] 扫描中...")
            results = _scan_once(targets, config, use_realtime=True)
            triggered = alerts.render_table(results, beep=True)
            if triggered:
                print()
                alerts.info("★ 检测到接近均线信号！")

            time.sleep(interval)
    except KeyboardInterrupt:
        alerts.info("已退出盘中监控。")


def main(argv: List[str] = None) -> None:
    """CLI 主入口。
    功能：解析参数 -> 加载配置与标的 -> 按模式调度
    输入：argv - 命令行参数（测试用）
    输出：无
    """
    parser = argparse.ArgumentParser(description="K线均线接近监控")
    parser.add_argument("--mode", choices=["eod", "live"], default="eod",
                        help="运行模式：eod=盘后跑一次 live=盘中常驻轮询")
    parser.add_argument("--interval", type=int, default=None,
                        help="live 模式轮询间隔(秒)，默认读配置")
    parser.add_argument("--config", default=_DEFAULT_CONFIG,
                        help="配置文件路径")
    parser.add_argument("--watchlist", default=_DEFAULT_WATCHLIST,
                        help="自选个股清单路径")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    targets = load_targets(config, args.watchlist)
    if not targets:
        alerts.warn("未配置任何监控标的，请检查 config.yaml / watchlist.txt")
        return

    interval = args.interval or int(config.get("interval", 300))

    if args.mode == "eod":
        run_eod(config, targets)
    else:
        run_live(config, targets, interval)


if __name__ == "__main__":
    main()
