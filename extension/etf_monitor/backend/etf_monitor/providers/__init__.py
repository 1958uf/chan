"""真实数据提供器公共入口。"""
from .base import ProviderError
from .live import LiveProvider

__all__ = ["LiveProvider", "ProviderError"]
