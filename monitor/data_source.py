"""
akshare 数据源封装

功能说明：
    - 屏蔽 akshare 各接口字段差异，对外提供统一的两类数据：
        1) 周线收盘序列（用于计算 MA50 等均线）
        2) 实时现价（用于盘中模式近似"当前价"）
    - 自动区分指数与个股，走不同接口分支
    - 内置多源重试与字段名兼容，提高网络波动下的健壮性

设计要点：
    - 指数周线：stock_zh_index_daily 取日线 -> resample('W-FRI') 取每周收盘
    - 个股周线：stock_zh_a_hist(period='weekly') 直接取
    - 实时价：stock_zh_a_spot 一次拉全市场再按代码过滤
    - 所有网络调用均带重试，单只失败不影响整体

使用示例：
    from monitor.data_source import get_weekly_close, get_realtime_price
    closes = get_weekly_close("sh000016", kind="index", adjust="qfq")
    price = get_realtime_price("sh600519")
"""
from __future__ import annotations

import time
from typing import List, Optional

import akshare as ak
import pandas as pd


# ---- 字段名兼容映射 ------------------------------------------------
# 不同数据源/版本返回的中文列名可能不同，统一映射为英文内部名
_STOCK_WEEKLY_CLOSE_COLS = ["收盘", "close", "CLOSE"]
_INDEX_DAILY_CLOSE_COLS = ["close", "收盘", "CLOSE"]
_SPOT_CODE_COLS = ["代码", "code", "symbol"]
_SPOT_PRICE_COLS = ["最新价", "price", "现价"]


def _resample_weekly(df: pd.DataFrame, close_col: str, date_col: str) -> List[float]:
    """把日线数据按周五重采样为周线收盘序列。
    功能：日线收盘按 W-FRI 取每周最后一根，dropna 保证连续
    输入：df - 日线 DataFrame；close_col - 收盘列名；date_col - 日期列名
    输出：周线收盘价列表（旧->新）
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    weekly = df[close_col].resample("W-FRI").last().dropna()
    return weekly.tolist()


def _pick(df: pd.DataFrame, candidates: List[str]):
    """从 DataFrame 中按候选列名顺序取第一个存在的列。
    功能：兼容不同数据源返回的列名差异
    输入：df - 数据源返回的 DataFrame；candidates - 候选列名列表
    输出：找到的列名；都没找到则返回 None
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _retry(fn, max_retry: int, desc: str = ""):
    """带重试的函数调用。
    功能：调用 fn，失败时间隔 1 秒重试，最多 max_retry 次
    输入：fn - 无参可调用对象；max_retry - 最大尝试次数；desc - 描述（用于日志）
    输出：fn 的返回值；全部失败则抛最后一次异常
    """
    last_err = None
    for i in range(1, max_retry + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - 网络层异常统一重试
            last_err = e
            if i < max_retry:
                time.sleep(1)
    raise RuntimeError(f"数据获取失败({desc})：{last_err}")


def get_weekly_close(code: str, kind: str = "index",
                     adjust: str = "qfq", max_retry: int = 3) -> List[float]:
    """获取某标的的周线收盘价序列。
    功能：拉取历史 K 线并整理为按周排序的收盘价列表
    输入：
        code      - akshare 简写代码，如 'sh000016' / 'sh600519'
        kind      - 'index' 指数 或 'stock' 个股
        adjust    - 复权方式，仅个股生效：'qfq'/'hfq'/''
        max_retry - 失败重试次数
    输出：周线收盘价列表（从旧到新）；数据不足返回空列表
    """
    if kind == "index":
        # 指数：取日线后按周五重采样，取每周最后一根的收盘
        df = _retry(lambda: ak.stock_zh_index_daily(symbol=code),
                    max_retry, f"指数日线 {code}")
        close_col = _pick(df, _INDEX_DAILY_CLOSE_COLS)
        date_col = "date" if "date" in df.columns else _pick(df, ["日期"])
        return _resample_weekly(df, close_col, date_col)
    else:
        # 个股：优先东财周线接口；失败则降级到 sina 日线重采样，保证可用性
        pure = code[2:] if code[:2] in ("sh", "sz") else code
        try:
            df = _retry(
                lambda: ak.stock_zh_a_hist(symbol=pure, period="weekly",
                                           adjust=adjust if adjust else ""),
                max_retry, f"个股周线(东财) {code}",
            )
            close_col = _pick(df, _STOCK_WEEKLY_CLOSE_COLS)
            date_col = _pick(df, ["日期", "date"]) or "日期"
            df = df.sort_values(date_col)
            return df[close_col].astype(float).tolist()
        except Exception as e:  # noqa: BLE001 - 东财失败降级 sina 源
            df = _retry(
                lambda: ak.stock_zh_a_daily(symbol=code, adjust=adjust if adjust else ""),
                max_retry, f"个股日线(降级sina) {code}",
            )
            close_col = _pick(df, _INDEX_DAILY_CLOSE_COLS) or "close"
            date_col = "date" if "date" in df.columns else _pick(df, ["日期"])
            return _resample_weekly(df, close_col, date_col)


def get_realtime_prices(codes: List[str], max_retry: int = 3) -> dict:
    """批量获取个股/指数的实时现价。
    功能：调用 sina 实时行情接口，按代码过滤返回现价
    输入：codes - akshare 简写代码列表；max_retry - 失败重试次数
    输出：{code: 现价(float)}；取不到的代码不出现或值为 None
    说明：指数与个股都在同一个 spot 接口里（sina 源包含指数行）。
    """
    df = _retry(lambda: ak.stock_zh_a_spot(), max_retry, "实时行情")
    code_col = _pick(df, _SPOT_CODE_COLS)
    price_col = _pick(df, _SPOT_PRICE_COLS)
    if code_col is None or price_col is None:
        return {c: None for c in codes}
    # 建立代码 -> 现价 的查找表（sina 代码列即为 sh600519 形式）
    lookup = {}
    for _, row in df.iterrows():
        c = str(row[code_col]).strip()
        try:
            lookup[c] = float(row[price_col])
        except (ValueError, TypeError):
            continue
    return {c: lookup.get(c) for c in codes}


def get_realtime_price(code: str, max_retry: int = 3) -> Optional[float]:
    """获取单个标的的实时现价（内部调用批量接口）。
    功能：取一只标的的实时价格
    输入：code - akshare 简写代码；max_retry - 失败重试次数
    输出：现价 float；取不到返回 None
    """
    return get_realtime_prices([code], max_retry=max_retry).get(code)
