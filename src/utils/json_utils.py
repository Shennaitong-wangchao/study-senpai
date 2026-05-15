from __future__ import annotations

import json
from collections import Counter, deque
from typing import Any
from threading import Lock


_JSON_EXTRACT_LOCK = Lock()
_JSON_EXTRACT_COUNTERS: Counter[str] = Counter()
_JSON_EXTRACT_RECENT: deque[dict[str, Any]] = deque(maxlen=32)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _record_json_extraction(event_type: str, *, preview: str, success: bool, detail: str | None = None) -> None:
    with _JSON_EXTRACT_LOCK:
        _JSON_EXTRACT_COUNTERS[event_type] += 1
        _JSON_EXTRACT_COUNTERS["success" if success else "failure"] += 1
        _JSON_EXTRACT_RECENT.appendleft(
            {
                "event_type": event_type,
                "success": success,
                "detail": detail,
                "preview": preview[:160],
            }
        )


def get_json_extraction_stats() -> dict[str, Any]:
    with _JSON_EXTRACT_LOCK:
        return {
            "counters": dict(_JSON_EXTRACT_COUNTERS),
            "recent": list(_JSON_EXTRACT_RECENT),
        }


def extract_json_object(value: str) -> dict[str, Any]:
    value = value.strip()
    preview = value.replace("\n", " ")[:160]
    try:
        result = json.loads(value)
        _record_json_extraction("exact_json", preview=preview, success=True)
        return result
    except json.JSONDecodeError as exc:
        last_error = exc

    start = value.find("{")
    end = value.rfind("}")
    if "```" in value:
        fenced_start = value.find("{", value.find("```"))
        fenced_end = value.rfind("}")
        if fenced_start != -1 and fenced_end != -1 and fenced_start < fenced_end:
            try:
                result = json.loads(value[fenced_start : fenced_end + 1])
                _record_json_extraction("fenced_json", preview=preview, success=True)
                return result
            except json.JSONDecodeError as exc:
                last_error = exc

    if start == -1 or end == -1 or start >= end:
        _record_json_extraction("missing_object_bounds", preview=preview, success=False, detail=str(last_error))
        raise json.JSONDecodeError("No JSON object found", value, 0)
    try:
        result = json.loads(value[start : end + 1])
        prefix = value[:start].strip()
        suffix = value[end + 1 :].strip()
        if prefix and suffix:
            _record_json_extraction("wrapped_noise_both", preview=preview, success=True)
        elif prefix:
            _record_json_extraction("wrapped_noise_prefix", preview=preview, success=True)
        elif suffix:
            _record_json_extraction("wrapped_noise_suffix", preview=preview, success=True)
        else:
            _record_json_extraction("object_slice", preview=preview, success=True)
        return result
    except json.JSONDecodeError as exc:
        _record_json_extraction("invalid_inner_json", preview=preview, success=False, detail=str(exc))
        raise
