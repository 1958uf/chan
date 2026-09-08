"""
终端告警渲染

功能说明：
    - 把 MaCheckResult 列表渲染成对齐的彩色表格输出到终端
    - 触发接近的行用绿/红高亮 + 蜂鸣，吸引注意
    - 同时返回是否有触发，供调用方决定是否额外提示

设计要点：
    - 仅用 ANSI 转义实现彩色，无第三方 TUI 依赖
    - Windows 终端在 Win10+ 默认支持 ANSI；不支持时自动降级为纯文本
"""
from __future__ import annotations

import sys
from typing import List

from .indicators import MaCheckResult


# ANSI 颜色码
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
# 终端蜂鸣
_BEEP = "\a"

# 表格列定义：(表头, 宽度, 对齐方式 '<'左 '>'右)
_COLUMNS = [
    ("代码", 12, "<"),
    ("名称", 12, "<"),
    ("现价", 12, ">"),
    ("MA", 12, ">"),
    ("偏离%", 9, ">"),
    ("方向", 6, ">"),
    ("状态", 10, ">"),
]


def _fmt(v, width: int, align: str, color: str = "") -> str:
    """格式化单个单元格内容。
    功能：按宽度与对齐方式填充，可选加颜色
    输入：v - 原始值；width - 列宽；align - '<'或'>'；color - ANSI 颜色码
    输出：格式化后的字符串
    """
    if v is None:
        s = "-"
    elif isinstance(v, float):
        s = f"{v:.2f}"
    else:
        s = str(v)
    # 中文按两个宽度计算，做简单对齐补偿
    disp = sum(2 if ord(ch) > 127 else 1 for ch in s)
    pad = max(0, width - disp)
    if align == ">":
        out = " " * pad + s
    else:
        out = s + " " * pad
    return f"{color}{out}{_RESET}" if color else out


def render_table(results: List[MaCheckResult], beep: bool = True) -> bool:
    """渲染判定结果表格并打印。
    功能：输出对齐表格，触发行高亮，整体有触发则蜂鸣
    输入：results - 判定结果列表；beep - 是否允许蜂鸣
    输出：是否有任何触发（near=True）的标的
    """
    # 表头
    header = "  ".join(_fmt(h, w, a, _BOLD + _CYAN)
                       for h, w, a in _COLUMNS)
    sep = "-" * len(header)
    lines = [header, sep]

    any_near = False
    for r in results:
        # 方向：均线上方=↑ 下方=↓ 未知=-
        if r.above is True:
            direction, dir_color = "↑", _GREEN
        elif r.above is False:
            direction, dir_color = "↓", _RED
        else:
            direction, dir_color = "-", _DIM

        if r.deviation is not None:
            dev_str = f"{r.deviation*100:+.2f}"
        else:
            dev_str = "-"

        # 状态与整行颜色：触发=黄底高亮，未触发=暗淡
        if r.near:
            status, row_color = "★接近", _YELLOW + _BOLD
            any_near = True
        else:
            status, row_color = ("数据缺" if r.ma_value is None else "远离"), _DIM

        cells = [
            _fmt(r.code, _COLUMNS[0][1], "<", row_color),
            _fmt(r.name, _COLUMNS[1][1], "<", row_color),
            _fmt(r.price, _COLUMNS[2][1], ">", row_color),
            _fmt(r.ma_value, _COLUMNS[3][1], ">", row_color),
            _fmt(dev_str, _COLUMNS[4][1], ">", dir_color),
            _fmt(direction, _COLUMNS[5][1], ">", dir_color),
            _fmt(status, _COLUMNS[6][1], ">", row_color),
        ]
        lines.append("  ".join(cells))

        # 触发行追加原因/位置说明
        if r.near and r.deviation is not None:
            pos = "均线上方" if r.above else "均线下方"
            lines.append(f"     {_DIM}↳ {r.name}({r.code}) 现价 {r.price:.2f} "
                         f"距 MA{''} {pos} {abs(r.deviation)*100:.2f}%{_RESET}")

    # 触发时蜂鸣
    if any_near and beep:
        lines.append(_BEEP)

    print("\n".join(lines))
    return any_near


def info(msg: str) -> None:
    """打印普通信息行（暗青色）。
    功能：统一的日志输出样式
    输入：msg - 文本
    输出：无
    """
    print(f"{_DIM}{msg}{_RESET}")


def warn(msg: str) -> None:
    """打印警告行（黄色）。
    功能：统一的告警日志样式
    输入：msg - 文本
    输出：无
    """
    print(f"{_YELLOW}{msg}{_RESET}", file=sys.stderr)
