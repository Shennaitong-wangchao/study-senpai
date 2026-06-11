from __future__ import annotations

from scripts.release_gate import is_forbidden_tracked_path, scan_text_for_findings, scan_tracked_files


def test_forbidden_tracked_path_rules_block_local_state() -> None:
    assert is_forbidden_tracked_path(".env") == "private local-only file is tracked"
    assert is_forbidden_tracked_path(".env.local") == "private local-only file is tracked"
    assert is_forbidden_tracked_path("data/app.sqlite3") == "local runtime directory is tracked"
    assert is_forbidden_tracked_path("logs/app.log") == "local runtime directory is tracked"
    assert is_forbidden_tracked_path("scripts/deploy_host.sh") == "deployment script may contain host-specific state"


def test_forbidden_tracked_path_rules_allow_public_examples() -> None:
    assert is_forbidden_tracked_path(".env.example") is None
    assert is_forbidden_tracked_path("docs/TESTING.md") is None
    assert is_forbidden_tracked_path("deploy/systemd/README.md") is None


def test_scan_text_for_findings_detects_high_confidence_tokens() -> None:
    github_like = "ghp_" + "A" * 36
    openai_like = "sk-" + "B" * 40

    findings = scan_text_for_findings("example.txt", f"{github_like}\n{openai_like}")

    assert [item.check for item in findings] == ["github_token", "openai_key"]
    assert [item.line_number for item in findings] == [1, 2]


def test_scan_text_for_findings_ignores_redacted_or_placeholder_values() -> None:
    findings = scan_text_for_findings(
        "docs.md",
        "Authorization: Bearer <MOBILE_API_TOKEN>\n"
        "token=[REDACTED]\n",
    )

    assert findings == []


def test_scan_tracked_files_combines_path_and_text_findings(tmp_path) -> None:
    (tmp_path / "safe.py").write_text("value = 'sk-" + "C" * 40 + "'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SHOULD_NOT_BE_TRACKED=1\n", encoding="utf-8")

    findings = scan_tracked_files(["safe.py", ".env"], root=tmp_path)

    assert [(item.file_path, item.check) for item in findings] == [
        ("safe.py", "openai_key"),
        (".env", "tracked_private_path"),
    ]
