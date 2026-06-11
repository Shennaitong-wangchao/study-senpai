from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

HIGH_CONFIDENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("slack_bot_token", re.compile(r"\bxoxb-[A-Za-z0-9-]{20,}\b")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
)

PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+\]|<[A-Z0-9_]+>")

TEXT_SUFFIX_ALLOWLIST = {
    "",
    ".cfg",
    ".css",
    ".env",
    ".example",
    ".html",
    ".json",
    ".md",
    ".pbxproj",
    ".plist",
    ".py",
    ".swift",
    ".txt",
    ".xcworkspacedata",
    ".yml",
    ".yaml",
}

FORBIDDEN_PATH_PREFIXES = (
    "data/",
    "logs/",
    "secrets/",
    "tmp/",
    "temp/",
    ".claude/",
)

FORBIDDEN_PATH_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
)

FORBIDDEN_EXACT_PATHS = {
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    "dashboard_bootstrap_password.txt",
    "docs/PERSONA_SYSTEM.md",
    "src/seed_tavo_memory.py",
    "src/memory/bootstrap.py",
}


@dataclass(frozen=True)
class GateFinding:
    file_path: str
    check: str
    detail: str
    line_number: int | None = None


def git_tracked_files(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return list(filter(None, result.stdout.decode("utf-8").split("\0")))


def is_text_candidate(path: str) -> bool:
    suffix = Path(path).suffix
    return suffix in TEXT_SUFFIX_ALLOWLIST


def is_forbidden_tracked_path(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    rules = (
        (normalized in FORBIDDEN_EXACT_PATHS, "private local-only file is tracked"),
        (all((normalized.startswith(".env."), normalized != ".env.example")), "environment override file is tracked"),
        (all((normalized.startswith("DEPLOY_"), normalized.endswith("_PROMPT.md"))), "deployment prompt file may contain machine-specific state"),
        (all((normalized.startswith("scripts/deploy_"), normalized.endswith(".sh"))), "deployment script may contain host-specific state"),
        (any(map(normalized.startswith, FORBIDDEN_PATH_PREFIXES)), "local runtime directory is tracked"),
        (any(map(normalized.endswith, FORBIDDEN_PATH_SUFFIXES)), "local runtime artifact is tracked"),
    )
    matches = list(filter(lambda item: item[0], rules))
    return (matches[:1] or [(False, None)])[0][1]


def scan_text_for_findings(path: str, text: str) -> list[GateFinding]:
    return [
        GateFinding(
            file_path=path,
            line_number=line_number,
            check=pattern_id,
            detail="high-confidence credential pattern matched",
        )
        for line_number, line in enumerate(text.splitlines(), start=1)
        for pattern_id, pattern in HIGH_CONFIDENCE_PATTERNS
        if PLACEHOLDER_RE.search(line) is None and pattern.search(line)
    ]


def scan_tracked_file(path: str, root: Path = ROOT) -> list[GateFinding]:
    path_reason = is_forbidden_tracked_path(path)
    if path_reason:
        return [GateFinding(file_path=path, check="tracked_private_path", detail=path_reason)]
    if not is_text_candidate(path):
        return []
    try:
        text = (root / path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return scan_text_for_findings(path, text)


def scan_tracked_files(paths: Iterable[str], root: Path = ROOT) -> list[GateFinding]:
    findings: list[GateFinding] = []
    list(map(findings.extend, map(lambda path: scan_tracked_file(path, root), paths)))
    return findings


def run_release_gate(root: Path = ROOT) -> list[GateFinding]:
    return scan_tracked_files(git_tracked_files(root), root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Release gate: tracked private files, high-confidence credentials.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    findings = run_release_gate()
    if args.json:
        sys.stdout.write(
            json.dumps({"ok": not findings, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2)
            + "\n"
        )
    elif findings:
        sys.stdout.write("release_gate.py: failed\n")
        for item in findings:
            location = item.file_path if item.line_number is None else f"{item.file_path}:{item.line_number}"
            sys.stdout.write(f"- {location} [{item.check}] {item.detail}\n")
    else:
        sys.stdout.write("release_gate.py: release gate passed.\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
