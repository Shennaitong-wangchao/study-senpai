from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.persona.immersion_lint import repair_immersive_voice
from src.product.store import ProductStore
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import iso_utc_now, parse_iso8601

try:  # Optional until requirements are installed on a target host.
    import icalendar
except Exception:  # noqa: BLE001
    icalendar = None

try:
    import recurring_ical_events
except Exception:  # noqa: BLE001
    recurring_ical_events = None


logger = logging.getLogger(__name__)

WEATHER_CODE_TEXT = {
    0: "天挺晴",
    1: "云不多",
    2: "有点多云",
    3: "阴一点",
    45: "有雾",
    48: "有雾",
    51: "有小雨丝",
    53: "有细雨",
    55: "雨会更明显一点",
    61: "有小雨",
    63: "雨不算小",
    65: "雨会偏大",
    71: "有小雪",
    73: "雪会明显一点",
    75: "雪会偏大",
    80: "可能有阵雨",
    81: "阵雨会明显一点",
    82: "阵雨会偏大",
    95: "可能有雷雨",
}

SENSITIVE_SOURCE_RE = re.compile(r"(?i)(token|secret|key|auth|password|sig|signature)=([^&\\s]+)")


class RealityContextService:
    def __init__(
        self,
        *,
        settings: Settings,
        product_store: ProductStore,
    ) -> None:
        self.settings = settings
        self.product_store = product_store

    async def refresh_if_stale(self, scope: ConversationScope) -> dict[str, Any]:
        if not self.settings.reality_context_enabled:
            return self.build_dashboard_payload(scope)
        latest = self.product_store.get_latest_reality_snapshot(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
        )
        fetched_at = parse_iso8601(str((latest or {}).get("fetched_at") or ""))
        if fetched_at is not None:
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            threshold = datetime.now(timezone.utc) - timedelta(minutes=max(self.settings.reality_refresh_minutes, 1))
            if fetched_at >= threshold:
                return self.build_dashboard_payload(scope)
        return await self.refresh_now(scope)

    async def refresh_now(self, scope: ConversationScope) -> dict[str, Any]:
        if not self.settings.reality_context_enabled:
            self._record_audit(scope, "system", "refresh", "disabled", {"reason": "reality_context_disabled"})
            return self.build_dashboard_payload(scope)
        await self._refresh_weather(scope)
        await self._refresh_calendar(scope)
        return self.build_dashboard_payload(scope)

    def build_context_block(self, scope: ConversationScope) -> str:
        if not self.settings.reality_context_enabled:
            return ""
        anchors = self.get_cached_anchors(scope)
        lines = [
            "Reality Anchors（外部现实锚点，只能轻轻带过；不要说来源、接口、订阅地址、后台、工具或系统）：",
        ]
        if anchors["weather"].get("status") == "ok" and anchors["weather"].get("summary_text"):
            lines.append(f"- 现在外面：{anchors['weather']['summary_text']}")
        elif anchors["weather"].get("status") == "error":
            lines.append("- 天气锚点暂时不可用；不要提失败原因，按本地时间和她的一天继续聊。")
        events = anchors["calendar_events"][:3]
        if events:
            lines.append(
                "- 接下来 48 小时可轻轻惦记的安排："
                + "；".join(self._format_event_for_context(event) for event in events)
            )
        manual = [event for event in events if event.get("source_uid") == "manual"]
        if manual:
            lines.append("- 手动日程是用户或 Dashboard 补充的现实锚点，不要说成长期用户事实。")
        if len(lines) == 1:
            return ""
        lines.extend(
            [
                "- 用法：像真实聊天里顺手想起来一样用，不要播报天气/日历，不要把角色日常冒充真实事实。",
                "- 输出要求：禁止括号心理活动、第三人称自我叙述、工具腔和系统解释；若需要动作描写，用中文全角括号包住短动作。",
            ]
        )
        return "\n".join(lines)

    def get_cached_anchors(self, scope: ConversationScope) -> dict[str, Any]:
        weather = self.product_store.get_latest_reality_snapshot(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            source_type="weather",
        )
        now, horizon = self._window()
        events = self.product_store.list_calendar_events(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            start_at=now.isoformat(),
            end_at=horizon.isoformat(),
            limit=12,
        )
        return {
            "weather": weather or {},
            "calendar_events": events,
            "location": self.get_location(scope),
            "sources": self.public_calendar_sources(scope),
        }

    def build_dashboard_payload(self, scope: ConversationScope) -> dict[str, Any]:
        now, horizon = self._window()
        snapshots = self.product_store.list_reality_snapshots(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=20,
        )
        events = self.product_store.list_calendar_events(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            start_at=now.isoformat(),
            end_at=horizon.isoformat(),
            limit=80,
        )
        audits = self.product_store.list_reality_source_audits(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=30,
        )
        latest_weather = next((item for item in snapshots if item.get("source_type") == "weather"), None)
        return {
            "summary": {
                "enabled": self.settings.reality_context_enabled,
                "location": self.get_location(scope),
                "weather": latest_weather or {},
                "sources": self.public_calendar_sources(scope),
                "lookahead_hours": self.settings.calendar_lookahead_hours,
                "refresh_minutes": self.settings.reality_refresh_minutes,
                "window": {"start_at": now.isoformat(), "end_at": horizon.isoformat()},
            },
            "items": events,
            "highlights": {
                "snapshots": snapshots,
                "audits": audits,
                "context_block_preview": self.build_context_block(scope),
            },
        }

    def get_location(self, scope: ConversationScope) -> dict[str, Any]:
        value = self.product_store.get_app_setting(self._location_key(scope), None)
        if isinstance(value, dict):
            label = compact_text(str(value.get("label") or ""))
            latitude = value.get("latitude")
            longitude = value.get("longitude")
            if label and isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
                return {
                    "label": label,
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                    "source": "dashboard",
                    "updated_at": value.get("updated_at"),
                }
        return {
            "label": self.settings.weather_location_label,
            "latitude": self.settings.weather_latitude,
            "longitude": self.settings.weather_longitude,
            "source": "settings",
            "updated_at": None,
        }

    def update_location(
        self,
        scope: ConversationScope,
        *,
        label: str,
        latitude: float,
        longitude: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "label": compact_text(label)[:80],
            "latitude": float(latitude),
            "longitude": float(longitude),
            "note": truncate_text(compact_text(note or ""), 160),
            "updated_at": iso_utc_now(),
        }
        self.product_store.set_app_setting(self._location_key(scope), payload)
        self._record_audit(
            scope,
            "location",
            "update",
            "ok",
            {"label": payload["label"], "latitude": payload["latitude"], "longitude": payload["longitude"]},
        )
        return self.get_location(scope)

    def add_calendar_source(
        self,
        scope: ConversationScope,
        *,
        url: str,
        label: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        normalized_url = self._normalize_source_url(url)
        source = {
            "source_uid": self._source_uid(normalized_url),
            "label": compact_text(label)[:80] or "ICS 日程",
            "url": normalized_url,
            "enabled": bool(enabled),
            "created_at": iso_utc_now(),
            "updated_at": iso_utc_now(),
        }
        existing = self._dashboard_calendar_sources(scope)
        kept = [item for item in existing if item.get("source_uid") != source["source_uid"]]
        self.product_store.set_app_setting(self._calendar_sources_key(scope), kept + [source])
        self._record_audit(
            scope,
            "calendar",
            "upsert_source",
            "ok",
            {"source_uid": source["source_uid"], "label": source["label"], "enabled": source["enabled"]},
        )
        return self._public_source(source, readonly=False)

    def set_calendar_source_enabled(self, scope: ConversationScope, *, source_uid: str, enabled: bool) -> bool:
        sources = self._dashboard_calendar_sources(scope)
        changed = False
        for source in sources:
            if source.get("source_uid") == source_uid:
                source["enabled"] = bool(enabled)
                source["updated_at"] = iso_utc_now()
                changed = True
        if changed:
            self.product_store.set_app_setting(self._calendar_sources_key(scope), sources)
            self._record_audit(
                scope,
                "calendar",
                "set_source_enabled",
                "ok",
                {"source_uid": source_uid, "enabled": bool(enabled)},
            )
        return changed

    def add_manual_event(
        self,
        scope: ConversationScope,
        *,
        title: str,
        start_at: str,
        end_at: str | None = None,
        location: str = "",
        is_all_day: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        clean_title = truncate_text(compact_text(title), 120)
        if not clean_title:
            raise ValueError("title is required")
        start_dt = self._parse_datetime_or_date(start_at)
        end_dt = self._parse_datetime_or_date(end_at) if end_at else None
        event_hash = self._hash("|".join(["manual", clean_title, start_dt.isoformat(), (end_dt.isoformat() if end_dt else "")]))
        event = self.product_store.upsert_calendar_event(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            source_uid="manual",
            source_label="手动日程",
            external_uid=event_hash,
            event_hash=event_hash,
            title=clean_title,
            start_at=self._to_utc_iso(start_dt),
            end_at=None if end_dt is None else self._to_utc_iso(end_dt),
            timezone=self.settings.bot_timezone,
            location=truncate_text(compact_text(location), 120),
            is_all_day=is_all_day,
            status="manual",
            metadata={"note": truncate_text(compact_text(note or ""), 180), "source": "dashboard_manual"},
        )
        self._record_audit(scope, "calendar", "add_manual_event", "ok", {"event_uid": event["event_uid"]})
        return event

    async def _refresh_weather(self, scope: ConversationScope) -> None:
        if self.settings.weather_provider != "open_meteo":
            self.product_store.create_reality_snapshot(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                source_type="weather",
                source_label="weather",
                status="disabled",
                summary_text="",
                metadata={"provider": "disabled"},
            )
            return
        location = self.get_location(scope)
        fetched_at = iso_utc_now()
        try:
            payload = await self._fetch_weather_payload(location)
            summary = self._summarize_weather(location, payload)
            self.product_store.create_reality_snapshot(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                source_type="weather",
                source_label=str(location["label"]),
                status="ok",
                payload=self._compact_weather_payload(payload),
                summary_text=summary,
                fetched_at=fetched_at,
                valid_from=fetched_at,
                valid_until=(datetime.now(timezone.utc) + timedelta(minutes=max(self.settings.reality_refresh_minutes, 1))).isoformat(),
                metadata={"location": location, "provider": "open_meteo"},
            )
            self._record_audit(scope, "weather", "refresh", "ok", {"location": location["label"]})
        except Exception as exc:  # noqa: BLE001
            safe_error = truncate_text(str(exc), 180)
            self.product_store.create_reality_snapshot(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                source_type="weather",
                source_label=str(location["label"]),
                status="error",
                summary_text="",
                fetched_at=fetched_at,
                error_text=safe_error,
                metadata={"location": location, "provider": "open_meteo"},
            )
            self._record_audit(scope, "weather", "refresh", "error", {"location": location["label"]}, safe_error)

    async def _refresh_calendar(self, scope: ConversationScope) -> None:
        sources = [source for source in self._calendar_sources(scope) if source.get("enabled", True)]
        if not sources:
            self.product_store.create_reality_snapshot(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                source_type="calendar",
                source_label="calendar",
                status="disabled",
                summary_text="未配置日历订阅，只使用手动日程。",
                metadata={"source_count": 0},
            )
            self._record_audit(scope, "calendar", "refresh", "disabled", {"source_count": 0})
            return
        now, horizon = self._window()
        total_events = 0
        failures = 0
        for source in sources:
            source_uid = str(source.get("source_uid") or "")
            label = str(source.get("label") or "ICS 日程")
            try:
                ics_text = await self._fetch_ics_text(str(source.get("url") or ""))
                parsed_events = self._parse_ics_events(ics_text, source=source, start=now, end=horizon)
                hashes: set[str] = set()
                for item in parsed_events:
                    hashes.add(str(item["event_hash"]))
                    self.product_store.upsert_calendar_event(
                        user_id=scope.user_id,
                        conversation_id=scope.conversation_id,
                        source_uid=source_uid,
                        source_label=label,
                        external_uid=item.get("external_uid"),
                        event_hash=str(item["event_hash"]),
                        title=str(item["title"]),
                        start_at=str(item["start_at"]),
                        end_at=item.get("end_at"),
                        timezone=str(item.get("timezone") or self.settings.bot_timezone),
                        location=str(item.get("location") or ""),
                        is_all_day=bool(item.get("is_all_day")),
                        status="active",
                        metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    )
                self.product_store.mark_calendar_source_events_stale(
                    user_id=scope.user_id,
                    conversation_id=scope.conversation_id,
                    source_uid=source_uid,
                    keep_event_hashes=hashes,
                )
                total_events += len(parsed_events)
                self._record_audit(scope, "calendar", "refresh_source", "ok", {"source_uid": source_uid, "label": label, "events": len(parsed_events)})
            except Exception as exc:  # noqa: BLE001
                failures += 1
                safe_error = truncate_text(self._redact_url(str(exc)), 180)
                self._record_audit(scope, "calendar", "refresh_source", "error", {"source_uid": source_uid, "label": label}, safe_error)
        status = "ok" if failures == 0 else "partial_error"
        summary = f"未来 {self.settings.calendar_lookahead_hours} 小时有 {total_events} 个可参考安排。"
        self.product_store.create_reality_snapshot(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            source_type="calendar",
            source_label="calendar",
            status=status,
            summary_text=summary,
            payload={"event_count": total_events, "failure_count": failures},
            valid_from=now.isoformat(),
            valid_until=horizon.isoformat(),
            metadata={"source_count": len(sources), "failure_count": failures},
        )

    async def _fetch_weather_payload(self, location: dict[str, Any]) -> dict[str, Any]:
        params = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "temperature_2m,apparent_temperature,precipitation,rain,snowfall,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": self.settings.bot_timezone,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            return response.json()

    async def _fetch_ics_text(self, url: str) -> str:
        normalized = self._normalize_source_url(url)
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(normalized)
            response.raise_for_status()
            return response.text

    def _parse_ics_events(
        self,
        ics_text: str,
        *,
        source: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        if icalendar is None:
            raise RuntimeError("icalendar dependency is not installed")
        calendar = icalendar.Calendar.from_ical(ics_text)
        if recurring_ical_events is not None:
            raw_events = recurring_ical_events.of(calendar).between(start, end)
        else:
            raw_events = [component for component in calendar.walk("VEVENT")]
        events: list[dict[str, Any]] = []
        for component in raw_events:
            item = self._calendar_component_to_event(component, source=source)
            if item is None:
                continue
            start_at = parse_iso8601(item["start_at"])
            if start_at is None:
                continue
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            if start_at > end:
                continue
            item_end = parse_iso8601(item["end_at"]) if item.get("end_at") else None
            if item_end is not None and item_end.tzinfo is None:
                item_end = item_end.replace(tzinfo=timezone.utc)
            if item_end is not None and item_end < start:
                continue
            if item_end is None and start_at < start:
                continue
            events.append(item)
        events.sort(key=lambda item: item["start_at"])
        return events[:80]

    def _calendar_component_to_event(self, component: Any, *, source: dict[str, Any]) -> dict[str, Any] | None:
        summary = self._ical_value(component.get("summary"))
        if not summary:
            return None
        dtstart = component.get("dtstart")
        if dtstart is None:
            return None
        dtend = component.get("dtend")
        start_value = dtstart.dt
        end_value = dtend.dt if dtend is not None else None
        start_dt, is_all_day = self._coerce_ical_datetime(start_value)
        end_dt = self._coerce_ical_datetime(end_value)[0] if end_value is not None else None
        uid = self._ical_value(component.get("uid")) or ""
        recurrence_id = self._ical_value(component.get("recurrence-id")) or ""
        location = self._ical_value(component.get("location"))
        event_hash = self._hash(
            "|".join(
                [
                    str(source.get("source_uid") or ""),
                    uid,
                    recurrence_id,
                    summary,
                    start_dt.isoformat(),
                    "" if end_dt is None else end_dt.isoformat(),
                ]
            )
        )
        return {
            "external_uid": uid or event_hash,
            "event_hash": event_hash,
            "title": truncate_text(compact_text(summary), 140),
            "start_at": self._to_utc_iso(start_dt),
            "end_at": None if end_dt is None else self._to_utc_iso(end_dt),
            "timezone": self.settings.bot_timezone,
            "location": truncate_text(compact_text(location), 120),
            "is_all_day": is_all_day,
            "metadata": {
                "recurrence_id": recurrence_id,
                "source_kind": "ics",
                "masked_source": self._mask_source(str(source.get("url") or "")),
            },
        }

    def _summarize_weather(self, location: dict[str, Any], payload: dict[str, Any]) -> str:
        current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
        daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
        temp = current.get("temperature_2m")
        apparent = current.get("apparent_temperature")
        wind = current.get("wind_speed_10m")
        precipitation = current.get("precipitation") or current.get("rain") or current.get("snowfall") or 0
        code = int(current.get("weather_code") or 0)
        weather_text = WEATHER_CODE_TEXT.get(code, "天气还算平稳")
        high = self._first(daily.get("temperature_2m_max"))
        low = self._first(daily.get("temperature_2m_min"))
        rain_chance = self._first(daily.get("precipitation_probability_max"))
        pieces = [str(location.get("label") or "这边"), weather_text]
        if temp is not None:
            pieces.append(f"约 {round(float(temp))} 度")
        if apparent is not None and temp is not None and abs(float(apparent) - float(temp)) >= 2:
            pieces.append(f"体感 {round(float(apparent))} 度")
        if high is not None and low is not None:
            pieces.append(f"今天大概 {round(float(low))}-{round(float(high))} 度")
        if rain_chance is not None and float(rain_chance) >= 45:
            pieces.append(f"有点下雨概率")
        if float(precipitation or 0) > 0:
            pieces.append("路面可能湿")
        if wind is not None and float(wind) >= 20:
            pieces.append("风会明显一点")
        return repair_immersive_voice("，".join(pieces) + "。")

    def _compact_weather_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
        daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
        return {
            "current": {
                key: current.get(key)
                for key in (
                    "time",
                    "temperature_2m",
                    "apparent_temperature",
                    "precipitation",
                    "rain",
                    "snowfall",
                    "weather_code",
                    "wind_speed_10m",
                )
            },
            "daily": {
                key: daily.get(key)
                for key in ("time", "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max")
            },
        }

    def _calendar_sources(self, scope: ConversationScope) -> list[dict[str, Any]]:
        config_sources = [
            {
                "source_uid": self._source_uid(url),
                "label": f"配置日历 {index + 1}",
                "url": self._normalize_source_url(url),
                "enabled": True,
                "readonly": True,
            }
            for index, url in enumerate(self.settings.calendar_ics_urls)
            if url
        ]
        dashboard_sources = self._dashboard_calendar_sources(scope)
        by_uid: dict[str, dict[str, Any]] = {}
        for source in config_sources + dashboard_sources:
            uid = str(source.get("source_uid") or "")
            if uid:
                by_uid[uid] = source
        return list(by_uid.values())

    def public_calendar_sources(self, scope: ConversationScope) -> list[dict[str, Any]]:
        public = []
        config_uids = {self._source_uid(url) for url in self.settings.calendar_ics_urls if url}
        for source in self._calendar_sources(scope):
            public.append(self._public_source(source, readonly=str(source.get("source_uid")) in config_uids or bool(source.get("readonly"))))
        return public

    def _dashboard_calendar_sources(self, scope: ConversationScope) -> list[dict[str, Any]]:
        value = self.product_store.get_app_setting(self._calendar_sources_key(scope), [])
        if not isinstance(value, list):
            return []
        sources = []
        for item in value:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            try:
                normalized_url = self._normalize_source_url(url)
            except ValueError:
                continue
            source_uid = str(item.get("source_uid") or self._source_uid(normalized_url))
            sources.append(
                {
                    "source_uid": source_uid,
                    "label": truncate_text(compact_text(str(item.get("label") or "ICS 日程")), 80),
                    "url": normalized_url,
                    "enabled": bool(item.get("enabled", True)),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "readonly": False,
                }
            )
        return sources

    def _public_source(self, source: dict[str, Any], *, readonly: bool) -> dict[str, Any]:
        return {
            "source_uid": source.get("source_uid"),
            "label": source.get("label") or "ICS 日程",
            "enabled": bool(source.get("enabled", True)),
            "readonly": bool(readonly),
            "masked_url": self._mask_source(str(source.get("url") or "")),
            "created_at": source.get("created_at"),
            "updated_at": source.get("updated_at"),
        }

    def _window(self) -> tuple[datetime, datetime]:
        try:
            tz = ZoneInfo(self.settings.bot_timezone)
        except Exception:  # noqa: BLE001
            tz = timezone.utc
        now = datetime.now(tz)
        horizon = now + timedelta(hours=max(self.settings.calendar_lookahead_hours, 1))
        return now.astimezone(timezone.utc), horizon.astimezone(timezone.utc)

    def _coerce_ical_datetime(self, value: Any) -> tuple[datetime, bool]:
        try:
            tz = ZoneInfo(self.settings.bot_timezone)
        except Exception:  # noqa: BLE001
            tz = timezone.utc
        if isinstance(value, datetime):
            return (value if value.tzinfo is not None else value.replace(tzinfo=tz)), False
        if isinstance(value, date):
            return datetime.combine(value, time.min, tzinfo=tz), True
        if isinstance(value, str):
            return self._parse_datetime_or_date(value), False
        return datetime.now(tz), False

    def _parse_datetime_or_date(self, value: str | None) -> datetime:
        text = compact_text(value or "")
        if not text:
            raise ValueError("datetime is required")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed_date = date.fromisoformat(text)
            try:
                tz = ZoneInfo(self.settings.bot_timezone)
            except Exception:  # noqa: BLE001
                tz = timezone.utc
            return datetime.combine(parsed_date, time.min, tzinfo=tz)
        if parsed.tzinfo is None:
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo(self.settings.bot_timezone))
            except Exception:  # noqa: BLE001
                parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _format_event_for_context(self, event: dict[str, Any]) -> str:
        title = truncate_text(compact_text(str(event.get("title") or "")), 48)
        start = parse_iso8601(str(event.get("start_at") or ""))
        if start is None:
            return title
        try:
            start = start.astimezone(ZoneInfo(self.settings.bot_timezone))
        except Exception:  # noqa: BLE001
            pass
        if event.get("is_all_day"):
            time_text = f"{start.strftime('%m-%d')} 全天"
        else:
            time_text = start.strftime("%m-%d %H:%M")
        location = compact_text(str(event.get("location") or ""))
        suffix = f" @ {truncate_text(location, 28)}" if location else ""
        return f"{time_text} {title}{suffix}"

    def _normalize_source_url(self, url: str) -> str:
        normalized = compact_text(url)
        if normalized.startswith("webcal://"):
            normalized = "https://" + normalized[len("webcal://") :]
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("ICS URL must start with http(s) or webcal")
        return normalized

    def _mask_source(self, url: str) -> str:
        if not url:
            return ""
        redacted = SENSITIVE_SOURCE_RE.sub(r"\1=[redacted]", url)
        digest = self._hash(redacted)[:8]
        host = redacted.split("//", 1)[-1].split("/", 1)[0]
        return f"{host}/...#{digest}"

    def _redact_url(self, text: str) -> str:
        return SENSITIVE_SOURCE_RE.sub(r"\1=[redacted]", text)

    def _source_uid(self, url: str) -> str:
        return f"ics_{self._hash(self._normalize_source_url(url))[:16]}"

    def _location_key(self, scope: ConversationScope) -> str:
        return f"reality_location:{scope.user_id}:{scope.conversation_id}"

    def _calendar_sources_key(self, scope: ConversationScope) -> str:
        return f"reality_calendar_sources:{scope.user_id}:{scope.conversation_id}"

    def _record_audit(
        self,
        scope: ConversationScope,
        source_type: str,
        action: str,
        status: str,
        details: dict[str, Any] | None = None,
        error_text: str | None = None,
    ) -> None:
        try:
            self.product_store.record_reality_source_audit(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                source_type=source_type,
                action=action,
                status=status,
                details=details or {},
                error_text=error_text,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to record reality source audit")

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_utc_iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _first(value: Any) -> Any:
        if isinstance(value, list) and value:
            return value[0]
        return value

    @staticmethod
    def _ical_value(value: Any) -> str:
        if value is None:
            return ""
        raw = getattr(value, "to_ical", None)
        if callable(raw):
            try:
                return raw().decode("utf-8")
            except Exception:  # noqa: BLE001
                pass
        return compact_text(str(value))
