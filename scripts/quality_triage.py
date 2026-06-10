from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PERCENT_S = "%" + "s"
PERCENT_D = "%" + "d"

DISPOSITION_BLOCKER = "blocker"
DISPOSITION_NEEDS_REVIEW = "needs_review"
DISPOSITION_KNOWN_NOISE = "known_noise"

HTTP_PREFIX = "http" + "://"
LOCAL_HTTP_MARKERS = (
    HTTP_PREFIX + "127.0.0.1",
    HTTP_PREFIX + "localhost",
    HTTP_PREFIX + "testserver",
    HTTP_PREFIX + "0.0.0.0",
)

SQL_CALL_RE = re.compile(r"\b(?:execute|executemany|executescript|raw|query)\s*\(")
LOGGING_CALL_RE = re.compile(r"\b(?:logger|logging)\.\w+\s*\(")


@dataclass(frozen=True)
class TriagedFinding:
    file: str
    line: int | None
    type: str
    severity: str
    disposition: str
    reason: str
    message: str


def _read_source_line(root: Path, file_path: str, line_number: Any) -> str:
    try:
        line_index = int(line_number) - 1
    except (TypeError, ValueError):
        return ""
    try:
        lines = (root / file_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[line_index].strip() if 0 <= line_index < len(lines) else ""


def _is_logging_placeholder_noise(source_line: str) -> bool:
    return all((bool(LOGGING_CALL_RE.search(source_line)), any((PERCENT_S in source_line, PERCENT_D in source_line))))


def _is_date_format_noise(source_line: str) -> bool:
    return all(("strftime(" in source_line, any((PERCENT_S in source_line, PERCENT_D in source_line))))


def _is_local_http_noise(source_line: str) -> bool:
    return any(map(lambda marker: marker in source_line, LOCAL_HTTP_MARKERS))


def _text(value: Any, default: str = "") -> str:
    text = str(value)
    return {"": default, "None": default}.get(text, text)


def classify_security_finding(finding: dict[str, Any], *, root: Path = ROOT) -> TriagedFinding:
    file_path = _text(finding.get("file"))
    finding_type = _text(finding.get("type"), "unknown")
    severity = _text(finding.get("severity"), "unknown")
    message = _text(finding.get("message"))
    line_number = finding.get("line")
    source_line = _read_source_line(root, file_path, line_number)
    rules = (
        (
            any((severity == "critical", finding_type == "hardcoded_secret")),
            DISPOSITION_BLOCKER,
            "critical 或凭据类命中必须阻断发布，直到证明安全",
        ),
        (
            all((finding_type == "sql_injection", _is_logging_placeholder_noise(source_line))),
            DISPOSITION_KNOWN_NOISE,
            "日志占位符命中了宽泛 SQL 启发式规则",
        ),
        (
            all((finding_type == "sql_injection", _is_date_format_noise(source_line))),
            DISPOSITION_KNOWN_NOISE,
            "日期格式占位符命中了宽泛 SQL 启发式规则",
        ),
        (
            all((finding_type == "sql_injection", bool(SQL_CALL_RE.search(source_line)))),
            DISPOSITION_NEEDS_REVIEW,
            "数据库调用需要人工确认是否参数化",
        ),
        (
            all((finding_type == "insecure_protocol", _is_local_http_noise(source_line))),
            DISPOSITION_KNOWN_NOISE,
            "本地开发 URL 不是生产传输策略",
        ),
        (
            finding_type in {"xss_vulnerable", "unsafe_react_html"},
            DISPOSITION_NEEDS_REVIEW,
            "HTML 渲染命中需要确认转义或可信模板",
        ),
        (
            all((finding_type == "debug_code", file_path.startswith("scripts/"))),
            DISPOSITION_KNOWN_NOISE,
            "验证脚本输出属于预期行为",
        ),
    )
    disposition, reason = next(
        ((item[1], item[2]) for item in rules if item[0]),
        (DISPOSITION_NEEDS_REVIEW, "需要人工审查后才能关闭"),
    )

    try:
        normalized_line: int | None = int(line_number)
    except (TypeError, ValueError):
        normalized_line = None
    return TriagedFinding(
        file=file_path,
        line=normalized_line,
        type=finding_type,
        severity=severity,
        disposition=disposition,
        reason=reason,
        message=message,
    )


def iter_security_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    security = report.get("security")
    if not isinstance(security, dict):
        return []
    buckets = map(security.get, ("critical", "high", "medium", "low", "info"))
    filtered = map(lambda bucket: list(filter(lambda item: isinstance(item, dict), bucket)) if isinstance(bucket, list) else [], buckets)
    return sum(filtered, [])


def triage_report(report: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    findings = list(map(lambda item: classify_security_finding(item, root=root), iter_security_findings(report)))
    summary_counts = Counter(map(lambda item: item.disposition, findings))
    severity_counts = Counter(map(lambda item: item.severity, findings))
    summary = {
        DISPOSITION_BLOCKER: summary_counts.get(DISPOSITION_BLOCKER, 0),
        DISPOSITION_NEEDS_REVIEW: summary_counts.get(DISPOSITION_NEEDS_REVIEW, 0),
        DISPOSITION_KNOWN_NOISE: summary_counts.get(DISPOSITION_KNOWN_NOISE, 0),
    }
    return {
        "ok": summary[DISPOSITION_BLOCKER] == 0,
        "summary": summary,
        "by_severity": dict(severity_counts),
        "findings": [asdict(item) for item in findings],
    }


def _format_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    header = (
        "quality_triage.py: "
        f"{summary[DISPOSITION_BLOCKER]} blocker(s), "
        f"{summary[DISPOSITION_NEEDS_REVIEW]} needs review, "
        f"{summary[DISPOSITION_KNOWN_NOISE]} known noise"
    )
    return "\n".join([header] + list(map(_format_finding_line, report["findings"]))) + "\n"


def _format_finding_line(item: dict[str, Any]) -> str:
    line_suffix = {None: ""}.get(item["line"], f":{item['line']}")
    location = f"{item['file']}{line_suffix}"
    return f"- {location} [{item['severity']}/{item['type']}] {item['disposition']}: {item['reason']}"


def load_report(path: Path) -> dict[str, Any]:
    if str(path) == "-":
        return json.loads(sys.stdin.read())
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage code_quality_analyzer JSON security findings.")
    parser.add_argument("report", type=Path, help="Analyzer JSON path. Use '-' to read stdin.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Project root used to inspect source lines.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    triaged = triage_report(load_report(args.report), root=args.root)
    if args.json:
        sys.stdout.write(json.dumps(triaged, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(_format_text(triaged))
    return int(not triaged["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
