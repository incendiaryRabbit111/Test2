"""时间字符串解析的小工具（无 Qt 依赖，方便复用）。"""
from __future__ import annotations

from datetime import datetime

DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
    "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d%H%M%S", "%m-%d %H:%M", "%m/%d %H:%M",
    "%Y年%m月%d日 %H:%M", "%Y年%m月%d日", "%Y.%m.%d %H:%M", "%Y.%m.%d",
)
STD_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_dt(text) -> datetime | None:
    """尽量把时间字符串解析出来，失败返回 None。"""
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def fmt(dt: datetime) -> str:
    return dt.strftime(STD_FORMAT)
