"""API 服务的路径和运行参数。

API 默认使用独立的数据目录 data/api/，不读写桌面端的
data/history.db 与 data/api_configs.db。
"""
from __future__ import annotations

import os
from pathlib import Path

from app.paths import ROOT

APP_NAME = "特征微生物分析工具 API"
VERSION = "0.1.0"


def _resolve_data_dir() -> Path:
    raw = os.environ.get("MICROBE_API_DATA_DIR", "").strip()
    path = Path(raw) if raw else ROOT / "data" / "api"
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = _resolve_data_dir()
HISTORY_DB = DATA_DIR / "history.db"
API_CONFIG_DB = DATA_DIR / "api_configs.db"

HOST = os.environ.get("MICROBE_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
try:
    PORT = int(os.environ.get("MICROBE_API_PORT", "8000"))
except ValueError as exc:
    raise SystemExit("MICROBE_API_PORT 必须是整数") from exc

# 留空表示本机开发阶段不校验；局域网联调前应设置。
API_KEY = os.environ.get("MICROBE_API_KEY", "").strip()
