from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"
WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    return utc_now().isoformat()


def parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def current_local_time(timezone_name: str = DEFAULT_TIMEZONE_NAME) -> datetime:
    normalized = (timezone_name or DEFAULT_TIMEZONE_NAME).strip() or DEFAULT_TIMEZONE_NAME
    try:
        tz = ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        if normalized == DEFAULT_TIMEZONE_NAME:
            tz = timezone(timedelta(hours=8), name="UTC+08:00")
        else:
            tz = timezone.utc
    return datetime.now(tz)


def build_current_time_context(timezone_name: str = DEFAULT_TIMEZONE_NAME) -> str:
    current = current_local_time(timezone_name)
    weekday = WEEKDAY_NAMES[current.weekday()]
    tz_label = getattr(current.tzinfo, "key", None) or current.tzname() or timezone_name or DEFAULT_TIMEZONE_NAME
    return (
        f"当前本地时间：{current.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"今天是 {current.strftime('%Y-%m-%d')}，星期{weekday}，时区 {tz_label}。\n"
        "如果用户提到现在、今天、明天、昨晚、周末这类相对时间，请以这个时间为准理解。"
    )
