from __future__ import annotations

from scripts.quality_triage import (
    DISPOSITION_BLOCKER,
    DISPOSITION_KNOWN_NOISE,
    DISPOSITION_NEEDS_REVIEW,
    classify_security_finding,
    triage_report,
)


def write_source(tmp_path, relative_path: str, lines: list[str]) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finding(file_path: str, line: int, finding_type: str, severity: str = "high") -> dict[str, object]:
    return {
        "file": file_path,
        "line": line,
        "type": finding_type,
        "severity": severity,
        "message": "from analyzer",
    }


def test_classifies_critical_findings_as_blockers(tmp_path) -> None:
    write_source(tmp_path, "src/app.py", ["value = 'placeholder'"])

    triaged = classify_security_finding(
        finding("src/app.py", 1, "hardcoded_secret", "critical"),
        root=tmp_path,
    )

    assert triaged.disposition == DISPOSITION_BLOCKER
    assert "阻断发布" in triaged.reason


def test_classifies_logging_and_date_format_sql_noise(tmp_path) -> None:
    percent_s = "%" + "s"
    percent_d = "%" + "d"
    write_source(
        tmp_path,
        "src/app.py",
        [
            f'logger.warning("failed for {percent_s}", path)',
            f'return current.strftime("{percent_d}")',
        ],
    )

    logging_triage = classify_security_finding(finding("src/app.py", 1, "sql_injection"), root=tmp_path)
    date_triage = classify_security_finding(finding("src/app.py", 2, "sql_injection"), root=tmp_path)

    assert logging_triage.disposition == DISPOSITION_KNOWN_NOISE
    assert "日志占位符" in logging_triage.reason
    assert date_triage.disposition == DISPOSITION_KNOWN_NOISE
    assert "日期格式" in date_triage.reason


def test_classifies_real_query_style_calls_for_review(tmp_path) -> None:
    write_source(tmp_path, "src/db.py", ['cursor.execute("SELECT * FROM users WHERE id = " + user_id)'])

    triaged = classify_security_finding(finding("src/db.py", 1, "sql_injection"), root=tmp_path)

    assert triaged.disposition == DISPOSITION_NEEDS_REVIEW
    assert "参数化" in triaged.reason


def test_classifies_local_http_as_noise_and_html_rendering_for_review(tmp_path) -> None:
    write_source(
        tmp_path,
        "src/dashboard.js",
        [
            'const url = "' + "http" + '://127.0.0.1:8099";',
            "target." + "inner" + "HTML = userContent;",
        ],
    )

    http_triage = classify_security_finding(
        finding("src/dashboard.js", 1, "insecure_protocol", "medium"),
        root=tmp_path,
    )
    html_triage = classify_security_finding(
        finding("src/dashboard.js", 2, "xss_vulnerable", "medium"),
        root=tmp_path,
    )

    assert http_triage.disposition == DISPOSITION_KNOWN_NOISE
    assert html_triage.disposition == DISPOSITION_NEEDS_REVIEW


def test_triage_report_summarizes_dispositions(tmp_path) -> None:
    percent_s = "%" + "s"
    write_source(
        tmp_path,
        "src/app.py",
        [
            f'logger.info("ok {percent_s}", value)',
            'cursor.execute("SELECT " + value)',
            "secret_value = 'placeholder'",
        ],
    )
    report = {
        "security": {
            "critical": [finding("src/app.py", 3, "hardcoded_secret", "critical")],
            "high": [
                finding("src/app.py", 1, "sql_injection"),
                finding("src/app.py", 2, "sql_injection"),
            ],
        }
    }

    triaged = triage_report(report, root=tmp_path)

    assert triaged["ok"] is False
    assert triaged["summary"] == {
        DISPOSITION_BLOCKER: 1,
        DISPOSITION_NEEDS_REVIEW: 1,
        DISPOSITION_KNOWN_NOISE: 1,
    }
