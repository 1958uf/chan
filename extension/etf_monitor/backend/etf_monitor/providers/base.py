"""数据源共用契约：严格单位、时间和可诊断错误，不将缺失伪装成零。"""
from datetime import date, datetime
from math import isfinite
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ProviderError(RuntimeError):
    """采集错误，source定位来源，status区分失败和有效空，retryable说明重试性。"""

    def __init__(self, source: str, message: str, *, retryable: bool = False, status: str = "error"):
        """功能：构造来源错误；输入：来源、原因与状态；输出：可捕获异常。"""
        self.source = source
        self.message = message
        self.retryable = retryable
        self.status = status
        super().__init__(f"{source}: {message}")


def number(value, *, positive=False, optional=False):
    """功能：解析有限数字；输入：带千分位原值和约束；输出：float或明确缺失None。"""
    if value is None or str(value).strip() in {"", "-", "--", "None", "nan", "NaN", "null"}:
        if optional:
            return None
        raise ValueError("必需数值缺失")
    result = float(str(value).replace(",", "").replace("%", "").strip())
    if not isfinite(result):
        if optional:
            return None
        raise ValueError("非有限数字")
    if (positive and result <= 0) or (not positive and result < 0):
        raise ValueError("数值不符合范围")
    return result


def parse_date(value) -> date:
    """功能：解析统计日期；输入：ISO/八位日期或日期对象；输出：date，拒绝未知值。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def parse_time(value) -> datetime:
    """功能：解析交易源时间；输入：ISO或本地交易时间；输出：上海时区datetime。"""
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=SHANGHAI)
    return result.astimezone(SHANGHAI)


def require_rows(records, source):
    """功能：显式报告有效空；输入：列表、来源；输出：非空列表或empty错误。"""
    if not records:
        raise ProviderError(source, "查询成功但指定标的/日期没有有效记录", status="empty")
    return records
