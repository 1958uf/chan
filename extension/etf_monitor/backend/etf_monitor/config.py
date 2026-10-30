"""独立系统配置。

功能：校验运行目录、观察池和有界调度参数；不读取主工程配置。
"""
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ETF

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    """运行参数：默认本机、真实模式，调度显式开启。"""
    model_config = ConfigDict(extra="forbid")
    data_dir: Path = ROOT / "runtime"
    mode: Literal["live", "demo"] = "live"
    scheduler_enabled: bool = False
    quote_interval: int = Field(default=30, ge=15, le=3600)
    intraday_enabled: bool = False
    daily_update_hour: int = Field(default=18, ge=16, le=23)
    daily_update_minute: int = Field(default=17, ge=0, le=59)
    request_timeout: int = Field(default=15, ge=1, le=60)
    max_retries: int = Field(default=2, ge=0, le=4)
    max_backfill_days: int = Field(default=366, ge=1, le=3650)
    alert_cooldown_seconds: int = Field(default=1800, ge=1)
    shares_alert_pct: float = Field(default=2.0, gt=0, le=100)
    token: str | None = None
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:8765", "http://localhost:8765", "http://127.0.0.1:5173"])

    @classmethod
    def from_env(cls):
        """功能：读取ETF专属环境变量；输入：环境；输出：已校验配置。"""
        values = {}
        if os.getenv("ETF_MONITOR_HOME"):
            values["data_dir"] = Path(os.environ["ETF_MONITOR_HOME"]).expanduser().resolve()
        if os.getenv("ETF_MONITOR_MODE"):
            values["mode"] = os.environ["ETF_MONITOR_MODE"]
        values["scheduler_enabled"] = os.getenv("ETF_MONITOR_SCHEDULER", "0") == "1"
        values["token"] = os.getenv("ETF_MONITOR_TOKEN")
        return cls(**values)


def default_etfs() -> list[ETF]:
    """功能：载入默认观察池；输入：系统JSON；输出：校验后的ETF列表。"""
    path = ROOT / "config" / "etfs.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    result = [ETF.model_validate(item) for item in records]
    if len({item.code for item in result}) != len(result):
        raise ValueError("观察池存在重复代码")
    return result
