"""缠论适配器。

功能：
    1. kbar_to_klu_dict：KBar（纯 OHLCV）-> CKLine_Unit 构造所需的 DATA_FIELD 字典
    2. autofix_for：保留各数据源原有 autofix 设定（仅 CCXT 为 True）
    3. ChanStrategyAdapter：把 CChan.trigger_step 步进模型包装成 CStrategy.on_bar 回调模型

设计：这是 KBar 与 CKLine_Unit 之间唯一的转换收口处，其他地方不再直接转换。
依赖：DataBasis.KBar、Common.CTime/CEnum、KLine.KLine_Unit（均在缠论包内）。

CTime 语义：统一传 auto=True。
    - 日线（hour=0 且 minute=0）自动把 ts 设为当日 23:59（多级别对齐关键）
    - 分钟级别用真实时分
    这与原数据源直接构造 CKLine_Unit 的行为一致。

autofix 语义：仅 CCXT 原用 autofix=True（OHLC 异常自动修正），其余数据源不传。
"""
from Common.CEnum import DATA_FIELD, DATA_SRC
from Common.CTime import CTime
from DataBasis.kbar import KBar

# 延迟 import，避免 Strategies.base 与 chan 内部循环依赖
from .KLine.KLine_Unit import CKLine_Unit


def autofix_for(data_src) -> bool:
    """返回某数据源应使用的 autofix 设定。
    功能：保留各数据源原有 autofix 习惯——仅 CCXT 为 True，其余 False
    输入：data_src - DATA_SRC 枚举（或字符串）
    输出：bool
    """
    try:
        return data_src == DATA_SRC.CCXT
    except Exception:
        return False


def kbar_to_klu_dict(kbar: KBar, autofix: bool = False) -> dict:
    """KBar -> CKLine_Unit 构造所需的 DATA_FIELD 字典。
    功能：把纯 OHLCV 载体转为缠论 K 线单元所需字典，time 必须转为 CTime
    输入：kbar - DataBasis.KBar；autofix - 是否启用 OHLC 自动修正
    输出：符合 DATA_FIELD 命名的 dict（time 为 CTime）
    关键：CTime 用 auto=True，日线自动对齐 23:59；时间截断到分钟
    """
    t = kbar.time
    return {
        DATA_FIELD.FIELD_TIME: CTime(t.year, t.month, t.day, t.hour, t.minute, auto=True),
        DATA_FIELD.FIELD_OPEN: kbar.open,
        DATA_FIELD.FIELD_HIGH: kbar.high,
        DATA_FIELD.FIELD_LOW: kbar.low,
        DATA_FIELD.FIELD_CLOSE: kbar.close,
        DATA_FIELD.FIELD_VOLUME: kbar.volume,
        DATA_FIELD.FIELD_TURNOVER: kbar.turnover,
        DATA_FIELD.FIELD_TURNRATE: kbar.turnrate,
    }


def kbar_to_klu(kbar: KBar, autofix: bool = False) -> CKLine_Unit:
    """KBar -> CKLine_Unit（一步转换）。
    功能：组合 kbar_to_klu_dict + CKLine_Unit 构造
    输入：kbar - DataBasis.KBar；autofix - 是否启用 OHLC 自动修正
    输出：CKLine_Unit
    """
    return CKLine_Unit(kbar_to_klu_dict(kbar, autofix=autofix), autofix=autofix)
