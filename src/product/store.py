from __future__ import annotations

import math
import re
import uuid
from collections import Counter, deque
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.core.types import ConversationScope
from src.db.database import Database
from src.memory.models import LongTermMemoryCandidate
from src.product.models import (
    BackgroundTaskRecord,
    CandidateMemoryRecord,
    ExperienceMetricsRecord,
    HealthCheckRecord,
    ModeState,
    ProactiveMessageRecord,
    TurnTraceRecord,
)
from src.utils.json_utils import json_dumps, json_loads
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import iso_utc_now, parse_iso8601, utc_now


def _normalize_signature(*parts: str) -> str:
    return " | ".join(compact_text(part).lower() for part in parts if compact_text(part))


SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b(authorization|api[_-]?key|token|password|secret)(\s*[:=]\s*)([^,\s]+)")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+")


def _redact_log_line(line: str) -> str:
    if "Prompt context for" in line:
        prefix = line.split("Prompt context for", 1)[0]
        return prefix + "Prompt context for [redacted]\n"
    redacted = BEARER_TOKEN_RE.sub("Bearer [redacted]", line)
    return SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)


class ProductStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        row = self.db.fetchone(
            """
            SELECT value_json FROM app_settings
            WHERE key = ?
            LIMIT 1
            """,
            (key,),
        )
        if row is None:
            return default
        return json_loads(row["value_json"], default)

    def set_app_setting(self, key: str, value: Any) -> None:
        self.db.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (key, json_dumps(value), iso_utc_now()),
        )

    def delete_app_setting(self, key: str) -> None:
        self.db.execute("DELETE FROM app_settings WHERE key = ?", (key,))

    def get_dashboard_active_scope(self) -> dict[str, Any] | None:
        value = self.get_app_setting("dashboard_active_scope", None)
        if not isinstance(value, dict):
            return None
        user_id = str(value.get("user_id", "") or "").strip()
        conversation_id = str(value.get("conversation_id", "") or "").strip()
        if not user_id or not conversation_id:
            return None
        return {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "channel_id": value.get("channel_id"),
            "guild_id": value.get("guild_id"),
            "updated_at": value.get("updated_at"),
        }

    def set_dashboard_active_scope(
        self,
        *,
        user_id: str,
        conversation_id: str,
        channel_id: str | None,
        guild_id: str | None,
    ) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "channel_id": channel_id,
            "guild_id": guild_id,
            "updated_at": iso_utc_now(),
        }
        self.set_app_setting("dashboard_active_scope", payload)
        return payload

    def get_dashboard_password_hash(self) -> str | None:
        value = self.get_app_setting("dashboard_password_hash", None)
        if not isinstance(value, dict):
            return None
        password_hash = value.get("password_hash")
        return str(password_hash) if password_hash else None

    def set_dashboard_password_hash(self, password_hash: str) -> None:
        self.set_app_setting(
            "dashboard_password_hash",
            {"password_hash": password_hash, "updated_at": iso_utc_now()},
        )

    def dashboard_password_change_required(self, *, generated_password_in_use: bool) -> bool:
        value = self.get_app_setting("dashboard_force_password_change", None)
        if isinstance(value, dict) and "required" in value:
            return bool(value.get("required"))
        return generated_password_in_use and self.get_dashboard_password_hash() is None

    def set_dashboard_password_change_required(self, required: bool) -> None:
        self.set_app_setting(
            "dashboard_force_password_change",
            {"required": bool(required), "updated_at": iso_utc_now()},
        )

    def list_recent_conversations(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT conversation_id, user_id, channel_id, guild_id, MAX(created_at) AS last_created_at
            FROM messages
            GROUP BY conversation_id, user_id, channel_id, guild_id
            ORDER BY last_created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def list_dashboard_scopes(self, *, limit: int = 12) -> list[dict[str, Any]]:
        recent = self.list_recent_conversations(limit=limit)
        scopes: list[dict[str, Any]] = []
        for item in recent:
            snapshot = self.get_scope_snapshot(
                user_id=str(item["user_id"]),
                conversation_id=str(item["conversation_id"]),
            )
            if snapshot is not None:
                scopes.append(snapshot)
        return scopes

    def get_scope_snapshot(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT conversation_id, user_id, channel_id, guild_id, created_at, content, sender_type, metadata_json
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        if row is None:
            return None
        pending_candidates = self._count(
            "candidate_memories",
            " WHERE user_id = ? AND conversation_id = ? AND status = 'pending'",
            (user_id, conversation_id),
        )
        active_memories = self._count(
            "long_term_memories",
            " WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        turn_count = self._count(
            "turn_traces",
            " WHERE conversation_id = ?",
            (conversation_id,),
        )
        metadata = json_loads(row["metadata_json"], {})
        display_name = metadata.get("display_name") if isinstance(metadata, dict) else None
        preview = truncate_text(compact_text(row["content"]), 80)
        return {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "channel_id": row["channel_id"],
            "guild_id": row["guild_id"],
            "display_name": display_name or user_id,
            "last_message_at": row["created_at"],
            "latest_sender_type": row["sender_type"],
            "latest_preview": preview,
            "pending_candidates": pending_candidates,
            "active_memories": active_memories,
            "turn_count": turn_count,
        }

    def get_mode_state(self, user_id: str, conversation_id: str) -> ModeState:
        row = self.db.fetchone(
            """
            SELECT * FROM mode_states
            WHERE user_id = ? AND conversation_id = ?
            LIMIT 1
            """,
            (user_id, conversation_id),
        )
        if row is None:
            return ModeState()
        return ModeState(
            mode=row["mode"],
            learning_mode=bool(row["learning_mode"]),
            custom_model=row["custom_model"],
            backup_model=row["backup_model"],
            metadata=json_loads(row["metadata_json"], {}),
        )

    def upsert_mode_state(
        self,
        user_id: str,
        conversation_id: str,
        *,
        mode: str,
        learning_mode: bool,
        custom_model: str | None,
        backup_model: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> ModeState:
        now = iso_utc_now()
        existing = self.db.fetchone(
            """
            SELECT * FROM mode_states
            WHERE user_id = ? AND conversation_id = ?
            LIMIT 1
            """,
            (user_id, conversation_id),
        )
        payload = json_dumps(metadata or {})
        if existing is None:
            self.db.execute(
                """
                INSERT INTO mode_states (
                    user_id, conversation_id, mode, learning_mode, custom_model, backup_model,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    conversation_id,
                    mode,
                    int(learning_mode),
                    custom_model,
                    backup_model,
                    payload,
                    now,
                ),
            )
        else:
            merged_metadata = {**json_loads(existing["metadata_json"], {}), **(metadata or {})}
            self.db.execute(
                """
                UPDATE mode_states
                SET mode = ?, learning_mode = ?, custom_model = ?, backup_model = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    mode,
                    int(learning_mode),
                    custom_model,
                    backup_model,
                    json_dumps(merged_metadata),
                    now,
                    existing["id"],
                ),
            )
        return self.get_mode_state(user_id, conversation_id)

    def create_candidate_memory(
        self,
        scope: ConversationScope,
        candidate: LongTermMemoryCandidate,
    ) -> str | None:
        signature = _normalize_signature(candidate.memory_type, candidate.category, candidate.content)
        if not signature:
            return None
        if self.db.fetchone(
            """
            SELECT id FROM candidate_memories
            WHERE user_id = ? AND dedupe_signature = ? AND status = 'pending'
            LIMIT 1
            """,
            (scope.user_id, signature),
        ):
            return None

        now = iso_utc_now()
        candidate_uid = f"cand_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO candidate_memories (
                candidate_uid, user_id, conversation_id, session_id, channel_id, guild_id,
                memory_type, category, content, tags_json, confidence, importance, reason,
                source_message_ids_json, dedupe_signature, status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                candidate_uid,
                scope.user_id,
                scope.conversation_id,
                scope.session_id,
                scope.channel_id,
                scope.guild_id,
                candidate.memory_type,
                candidate.category,
                candidate.content,
                json_dumps(candidate.tags),
                candidate.confidence,
                candidate.importance,
                candidate.reason,
                json_dumps(candidate.source_message_ids),
                signature,
                json_dumps(candidate.metadata),
                now,
                now,
            ),
        )
        return candidate_uid

    def list_candidate_memories(
        self,
        *,
        user_id: str | None = None,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[CandidateMemoryRecord]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(limit)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM candidate_memories
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        )
        return [self._candidate_from_row(row) for row in rows]

    def get_candidate_memory(self, candidate_uid: str) -> CandidateMemoryRecord | None:
        row = self.db.fetchone(
            "SELECT * FROM candidate_memories WHERE candidate_uid = ? LIMIT 1",
            (candidate_uid,),
        )
        return self._candidate_from_row(row) if row else None

    def mark_candidate_reviewed(
        self,
        candidate_uid: str,
        *,
        status: str,
        review_note: str | None = None,
        approved_memory_uid: str | None = None,
        expected_status: str | None = None,
    ) -> bool:
        now = iso_utc_now()
        query = """
            UPDATE candidate_memories
            SET status = ?, review_note = ?, approved_memory_uid = ?, reviewed_at = ?, updated_at = ?
            WHERE candidate_uid = ?
            """
        params: list[Any] = [status, review_note, approved_memory_uid, now, now, candidate_uid]
        if expected_status:
            query = query.rstrip() + " AND status = ?"
            params.append(expected_status)
        cursor = self.db.execute(query, params)
        return (cursor.rowcount or 0) > 0

    def reopen_candidate_memory(self, candidate_uid: str) -> bool:
        cursor = self.db.execute(
            """
            UPDATE candidate_memories
            SET status = 'pending', review_note = NULL, reviewed_at = NULL, updated_at = ?
            WHERE candidate_uid = ? AND status = 'rejected'
            """,
            (iso_utc_now(), candidate_uid),
        )
        return (cursor.rowcount or 0) > 0

    def list_top_memory_hits(self, user_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT ltm.memory_uid, ltm.memory_type, ltm.category, ltm.content, ltm.importance, ltm.confidence,
                   mus.hit_count, mus.last_hit_at
            FROM memory_usage_stats mus
            JOIN long_term_memories ltm ON ltm.memory_uid = mus.memory_uid
            WHERE mus.user_id = ? AND ltm.status = 'active'
            ORDER BY mus.hit_count DESC, ltm.importance DESC, mus.updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    def record_memory_hits(
        self,
        user_id: str,
        memory_uids: list[str],
        *,
        context_type: str = "reply",
    ) -> None:
        now = iso_utc_now()
        for memory_uid in memory_uids:
            existing = self.db.fetchone(
                "SELECT * FROM memory_usage_stats WHERE memory_uid = ? LIMIT 1",
                (memory_uid,),
            )
            if existing is None:
                self.db.execute(
                    """
                    INSERT INTO memory_usage_stats (
                        memory_uid, user_id, hit_count, last_hit_at, last_context_type, metadata_json, updated_at
                    ) VALUES (?, ?, 1, ?, ?, '{}', ?)
                    """,
                    (memory_uid, user_id, now, context_type, now),
                )
                continue
            self.db.execute(
                """
                UPDATE memory_usage_stats
                SET hit_count = hit_count + 1, last_hit_at = ?, last_context_type = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, context_type, now, existing["id"]),
            )

    def enqueue_task(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        dedupe_key: str | None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        session_id: str | None = None,
        priority: float = 0.5,
        timeout_seconds: int = 180,
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> str | None:
        if dedupe_key:
            existing_rows = self.db.fetchall(
                """
                SELECT *
                FROM background_tasks
                WHERE task_type = ? AND dedupe_key = ? AND status IN ('pending', 'running', 'retrying')
                ORDER BY created_at DESC
                """,
                (task_type, dedupe_key),
            )
            for row in existing_rows:
                if row["status"] in {"pending", "retrying"}:
                    return row["task_uid"]
                if row["status"] == "running" and not self._task_is_stale(row):
                    return row["task_uid"]

        now = iso_utc_now()
        task_uid = f"task_{uuid.uuid4().hex}"
        available_at = now
        if delay_seconds > 0:
            available_at = self._shift_seconds(now, delay_seconds)
        self.db.execute(
            """
            INSERT INTO background_tasks (
                task_uid, task_type, user_id, conversation_id, session_id, dedupe_key, payload_json, status,
                attempts, max_attempts, priority, timeout_seconds, available_at, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                task_uid,
                task_type,
                user_id,
                conversation_id,
                session_id,
                dedupe_key,
                json_dumps(payload),
                max_attempts,
                priority,
                timeout_seconds,
                available_at,
                now,
                now,
            ),
        )
        return task_uid

    def claim_next_task(self) -> BackgroundTaskRecord | None:
        for _ in range(3):
            with self.db.transaction() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM background_tasks
                    WHERE status IN ('pending', 'retrying') AND available_at <= ?
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                    """,
                    (iso_utc_now(),),
                ).fetchone()
                if row is None:
                    return None
                now = iso_utc_now()
                updated = connection.execute(
                    """
                    UPDATE background_tasks
                    SET status = 'running', attempts = attempts + 1, started_at = ?, updated_at = ?
                    WHERE id = ? AND status IN ('pending', 'retrying')
                    """,
                    (now, now, row["id"]),
                )
                if (updated.rowcount or 0) != 1:
                    continue
                refreshed = connection.execute(
                    "SELECT * FROM background_tasks WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                return self._task_from_row(refreshed) if refreshed else None
        return None

    def complete_task(self, task_uid: str, result: dict[str, Any] | None = None) -> None:
        now = iso_utc_now()
        self.db.execute(
            """
            UPDATE background_tasks
            SET status = 'completed', finished_at = ?, updated_at = ?, result_json = ?
            WHERE task_uid = ?
            """,
            (now, now, json_dumps(result or {}), task_uid),
        )

    def fail_task(
        self,
        task_uid: str,
        *,
        error_text: str,
        retry_delay_seconds: int = 20,
    ) -> None:
        row = self.db.fetchone("SELECT * FROM background_tasks WHERE task_uid = ? LIMIT 1", (task_uid,))
        if row is None:
            return
        attempts = int(row["attempts"])
        max_attempts = int(row["max_attempts"])
        now = iso_utc_now()
        if attempts >= max_attempts:
            self.db.execute(
                """
                UPDATE background_tasks
                SET status = 'failed', finished_at = ?, updated_at = ?, last_error = ?
                WHERE task_uid = ?
                """,
                (now, now, error_text, task_uid),
            )
            return
        self.db.execute(
            """
            UPDATE background_tasks
            SET status = 'retrying', available_at = ?, updated_at = ?, last_error = ?
            WHERE task_uid = ?
            """,
            (self._shift_seconds(now, retry_delay_seconds), now, error_text, task_uid),
        )

    def mark_task_timed_out(
        self,
        task_uid: str,
        *,
        error_text: str,
        retry_delay_seconds: int = 20,
    ) -> None:
        row = self.db.fetchone("SELECT * FROM background_tasks WHERE task_uid = ? LIMIT 1", (task_uid,))
        if row is None:
            return
        attempts = int(row["attempts"])
        max_attempts = int(row["max_attempts"])
        now = iso_utc_now()
        if attempts >= max_attempts:
            self.db.execute(
                """
                UPDATE background_tasks
                SET status = 'timed_out', finished_at = ?, updated_at = ?, last_error = ?
                WHERE task_uid = ?
                """,
                (now, now, error_text, task_uid),
            )
            return
        self.db.execute(
            """
            UPDATE background_tasks
            SET status = 'retrying', available_at = ?, updated_at = ?, last_error = ?
            WHERE task_uid = ?
            """,
            (self._shift_seconds(now, retry_delay_seconds), now, error_text, task_uid),
        )

    def list_tasks(
        self,
        *,
        status: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        limit: int = 100,
    ) -> list[BackgroundTaskRecord]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        params.append(limit)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM background_tasks
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_uid: str) -> BackgroundTaskRecord | None:
        row = self.db.fetchone(
            """
            SELECT * FROM background_tasks
            WHERE task_uid = ?
            LIMIT 1
            """,
            (task_uid,),
        )
        return self._task_from_row(row) if row else None

    def recover_stale_tasks(self, *, grace_seconds: int = 60) -> int:
        rows = self.db.fetchall(
            """
            SELECT * FROM background_tasks
            WHERE status = 'running'
            ORDER BY started_at ASC
            """
        )
        recovered = 0
        now = iso_utc_now()
        for row in rows:
            if not self._task_is_stale(row, grace_seconds=grace_seconds):
                continue
            self.db.execute(
                """
                UPDATE background_tasks
                SET status = 'retrying', available_at = ?, updated_at = ?, started_at = NULL,
                    last_error = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    now,
                    now,
                    "Recovered stale running task after worker restart",
                    row["id"],
                ),
            )
            recovered += 1
        return recovered

    def retry_task(self, task_uid: str) -> bool:
        now = iso_utc_now()
        cursor = self.db.execute(
            """
            UPDATE background_tasks
            SET status = 'pending', attempts = 0, available_at = ?, started_at = NULL, finished_at = NULL,
                last_error = NULL, updated_at = ?
            WHERE task_uid = ? AND status IN ('failed', 'timed_out', 'cancelled')
            """,
            (now, now, task_uid),
        )
        return (cursor.rowcount or 0) > 0

    def cancel_task(self, task_uid: str) -> bool:
        now = iso_utc_now()
        cursor = self.db.execute(
            """
            UPDATE background_tasks
            SET status = 'cancelled', finished_at = ?, updated_at = ?
            WHERE task_uid = ? AND status IN ('pending', 'retrying', 'failed', 'timed_out')
            """,
            (now, now, task_uid),
        )
        return (cursor.rowcount or 0) > 0

    def reprioritize_task(self, task_uid: str, *, priority: float) -> bool:
        cursor = self.db.execute(
            """
            UPDATE background_tasks
            SET priority = ?, updated_at = ?
            WHERE task_uid = ? AND status IN ('pending', 'retrying')
            """,
            (priority, iso_utc_now(), task_uid),
        )
        return (cursor.rowcount or 0) > 0

    def record_dashboard_security_event(
        self,
        *,
        event_type: str,
        username: str | None,
        source_ip: str | None,
        success: bool,
        details: dict[str, Any] | None = None,
        locked_until: str | None = None,
    ) -> str:
        event_uid = f"dse_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO dashboard_security_events (
                event_uid, event_type, username, source_ip, success, locked_until, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_uid,
                event_type,
                username,
                source_ip,
                int(success),
                locked_until,
                json_dumps(details or {}),
                iso_utc_now(),
            ),
        )
        return event_uid

    def get_dashboard_lock_status(
        self,
        *,
        source_ip: str,
        window_seconds: int,
        max_attempts: int,
        lockout_seconds: int,
    ) -> dict[str, Any]:
        rows = self.db.fetchall(
            """
            SELECT * FROM dashboard_security_events
            WHERE source_ip = ? AND event_type = 'login_failure'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (source_ip, max_attempts),
        )
        now = utc_now()
        recent_failures = [
            row
            for row in rows
            if (
                (created_at := parse_iso8601(row["created_at"])) is not None
                and self._seconds_since(created_at, now) <= window_seconds
            )
        ]
        if len(recent_failures) < max_attempts:
            return {"locked": False, "failed_attempts": len(recent_failures), "locked_until": None}
        latest_failure = parse_iso8601(recent_failures[0]["created_at"])
        if latest_failure is None:
            return {"locked": False, "failed_attempts": len(recent_failures), "locked_until": None}
        locked_until_dt = latest_failure + timedelta(seconds=lockout_seconds)
        locked = locked_until_dt > now
        return {
            "locked": locked,
            "failed_attempts": len(recent_failures),
            "locked_until": locked_until_dt.isoformat() if locked else None,
        }

    def list_dashboard_security_events(self, *, limit: int = 40) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT * FROM dashboard_security_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "event_uid": row["event_uid"],
                "event_type": row["event_type"],
                "username": row["username"],
                "source_ip": row["source_ip"],
                "success": bool(row["success"]),
                "locked_until": row["locked_until"],
                "details": json_loads(row["details_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_dashboard_security_metrics(
        self,
        *,
        window_seconds: int,
        max_attempts: int,
        lockout_seconds: int,
    ) -> dict[str, Any]:
        rows = self.db.fetchall(
            """
            SELECT * FROM dashboard_security_events
            ORDER BY created_at DESC
            LIMIT 200
            """
        )
        now = utc_now()
        window_events = []
        for row in rows:
            created_at = parse_iso8601(row["created_at"])
            if created_at is None or self._seconds_since(created_at, now) > window_seconds:
                continue
            window_events.append(row)
        last_success = next((row["created_at"] for row in rows if row["event_type"] == "login_success"), None)
        last_failure = next((row["created_at"] for row in rows if row["event_type"] == "login_failure"), None)
        recent_sources: dict[str, int] = {}
        for row in window_events:
            source = row["source_ip"] or "unknown"
            recent_sources[source] = recent_sources.get(source, 0) + (1 if row["event_type"] == "login_failure" else 0)
        locked_sources = []
        for source, failures in recent_sources.items():
            lock_state = self.get_dashboard_lock_status(
                source_ip=source,
                window_seconds=window_seconds,
                max_attempts=max_attempts,
                lockout_seconds=lockout_seconds,
            )
            if lock_state["locked"]:
                locked_sources.append({"source_ip": source, "locked_until": lock_state["locked_until"]})
        return {
            "failed_last_window": sum(1 for row in window_events if row["event_type"] == "login_failure"),
            "success_last_window": sum(1 for row in window_events if row["event_type"] == "login_success"),
            "lockouts_last_window": sum(1 for row in window_events if row["event_type"] == "login_locked"),
            "last_success_at": last_success,
            "last_failure_at": last_failure,
            "window_seconds": window_seconds,
            "max_attempts": max_attempts,
            "lockout_seconds": lockout_seconds,
            "locked_sources": locked_sources,
        }

    def record_dashboard_action_audit(
        self,
        *,
        actor_username: str,
        source_ip: str | None,
        action_type: str,
        target_type: str,
        target_id: str,
        scope_user_id: str | None = None,
        scope_conversation_id: str | None = None,
        details: dict[str, Any] | None = None,
        undo_available: bool = False,
        undo_payload: dict[str, Any] | None = None,
    ) -> str:
        audit_uid = f"audit_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO dashboard_action_audits (
                audit_uid, actor_username, source_ip, action_type, target_type, target_id,
                scope_user_id, scope_conversation_id, status, undo_available, details_json, undo_payload_json,
                created_at, undone_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, NULL)
            """,
            (
                audit_uid,
                actor_username,
                source_ip,
                action_type,
                target_type,
                target_id,
                scope_user_id,
                scope_conversation_id,
                int(undo_available),
                json_dumps(details or {}),
                json_dumps(undo_payload or {}),
                iso_utc_now(),
            ),
        )
        return audit_uid

    def get_dashboard_action_audit(self, audit_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM dashboard_action_audits
            WHERE audit_uid = ?
            LIMIT 1
            """,
            (audit_uid,),
        )
        if row is None:
            return None
        return {
            "audit_uid": row["audit_uid"],
            "actor_username": row["actor_username"],
            "source_ip": row["source_ip"],
            "action_type": row["action_type"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "scope_user_id": row["scope_user_id"],
            "scope_conversation_id": row["scope_conversation_id"],
            "status": row["status"],
            "undo_available": bool(row["undo_available"]),
            "details": json_loads(row["details_json"], {}),
            "undo_payload": json_loads(row["undo_payload_json"], {}),
            "created_at": row["created_at"],
            "undone_at": row["undone_at"],
        }

    def list_dashboard_action_audits(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT * FROM dashboard_action_audits
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "audit_uid": row["audit_uid"],
                "actor_username": row["actor_username"],
                "source_ip": row["source_ip"],
                "action_type": row["action_type"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "scope_user_id": row["scope_user_id"],
                "scope_conversation_id": row["scope_conversation_id"],
                "status": row["status"],
                "undo_available": bool(row["undo_available"]),
                "details": json_loads(row["details_json"], {}),
                "created_at": row["created_at"],
                "undone_at": row["undone_at"],
            }
            for row in rows
        ]

    def mark_dashboard_action_undone(self, audit_uid: str) -> bool:
        cursor = self.db.execute(
            """
            UPDATE dashboard_action_audits
            SET status = 'undone', undone_at = ?
            WHERE audit_uid = ? AND status = 'applied' AND undo_available = 1
            """,
            (iso_utc_now(), audit_uid),
        )
        return (cursor.rowcount or 0) > 0

    def record_health_check(
        self,
        *,
        component: str,
        status: str,
        message: str,
        latency_ms: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO health_checks (component, status, message, latency_ms, details_json, checked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (component, status, message, latency_ms, json_dumps(details or {}), iso_utc_now()),
        )

    def get_latest_health(self) -> list[HealthCheckRecord]:
        rows = self.db.fetchall(
            """
            SELECT hc.*
            FROM health_checks hc
            JOIN (
                SELECT component, MAX(id) AS latest_id
                FROM health_checks
                GROUP BY component
            ) latest ON latest.latest_id = hc.id
            ORDER BY hc.component ASC
            """
        )
        return [self._health_from_row(row) for row in rows]

    def create_memory_snapshot(
        self,
        *,
        user_id: str,
        conversation_id: str,
        session_id: str,
        turn_uid: str | None,
        snapshot: dict[str, Any],
    ) -> str:
        snapshot_uid = f"snap_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO memory_snapshots (
                snapshot_uid, user_id, conversation_id, session_id, turn_uid, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (snapshot_uid, user_id, conversation_id, session_id, turn_uid, json_dumps(snapshot), iso_utc_now()),
        )
        return snapshot_uid

    def list_memory_snapshots(self, *, conversation_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        if conversation_id:
            rows = self.db.fetchall(
                """
                SELECT * FROM memory_snapshots
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
        else:
            rows = self.db.fetchall(
                """
                SELECT * FROM memory_snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [
            {
                "snapshot_uid": row["snapshot_uid"],
                "user_id": row["user_id"],
                "conversation_id": row["conversation_id"],
                "session_id": row["session_id"],
                "turn_uid": row["turn_uid"],
                "snapshot": json_loads(row["snapshot_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_turn_trace(
        self,
        *,
        turn_uid: str,
        user_id: str,
        conversation_id: str,
        session_id: str,
        user_message_id: int | None,
        assistant_message_id: int | None,
        request_type: str,
        reply_goal: str,
        scene: str,
        mode_text: str,
        model_name: str | None,
        backup_model_name: str | None,
        fallback_used: bool,
        latency_ms: float,
        user_input: str,
        assistant_reply: str,
        attachments: list[dict[str, Any]],
        search_context: list[dict[str, Any]],
        planning: dict[str, Any],
        retrieval: dict[str, Any],
        metrics: dict[str, Any],
        error_text: str | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO turn_traces (
                turn_uid, user_id, conversation_id, session_id, user_message_id, assistant_message_id,
                request_type, reply_goal, scene, mode_text, model_name, backup_model_name,
                fallback_used, latency_ms, user_input, assistant_reply, attachments_json,
                search_context_json, planning_json, retrieval_json, metrics_json, error_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_uid,
                user_id,
                conversation_id,
                session_id,
                user_message_id,
                assistant_message_id,
                request_type,
                reply_goal,
                scene,
                mode_text,
                model_name,
                backup_model_name,
                int(fallback_used),
                latency_ms,
                user_input,
                assistant_reply,
                json_dumps(attachments),
                json_dumps(search_context),
                json_dumps(planning),
                json_dumps(retrieval),
                json_dumps(metrics),
                error_text,
                iso_utc_now(),
            ),
        )

    def list_recent_turns(self, *, conversation_id: str | None = None, limit: int = 40) -> list[TurnTraceRecord]:
        if conversation_id:
            rows = self.db.fetchall(
                """
                SELECT * FROM turn_traces
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
        else:
            rows = self.db.fetchall(
                """
                SELECT * FROM turn_traces
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [self._turn_trace_from_row(row) for row in rows]

    def record_experience_metrics(
        self,
        turn_uid: str,
        *,
        persona_consistency: float,
        memory_hit_quality: float,
        memory_usage_rate: float,
        proactive_acceptance: float,
        repeated_comfort_rate: float,
        over_explaining_rate: float,
        tool_trace_leakage_rate: float,
        proactive_cold_response_rate: float,
        structure_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO experience_metric_events (
                turn_uid, persona_consistency, memory_hit_quality, memory_usage_rate, proactive_acceptance,
                repeated_comfort_rate, over_explaining_rate, tool_trace_leakage_rate,
                proactive_cold_response_rate, structure_type, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_uid,
                persona_consistency,
                memory_hit_quality,
                memory_usage_rate,
                proactive_acceptance,
                repeated_comfort_rate,
                over_explaining_rate,
                tool_trace_leakage_rate,
                proactive_cold_response_rate,
                structure_type,
                json_dumps(metadata or {}),
                iso_utc_now(),
            ),
        )

    def list_experience_metrics(self, *, limit: int = 200) -> list[ExperienceMetricsRecord]:
        rows = self.db.fetchall(
            """
            SELECT * FROM experience_metric_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._experience_from_row(row) for row in rows]

    def create_proactive_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        channel_id: str,
        trigger_type: str,
        opening_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        now = iso_utc_now()
        proactive_uid = f"pro_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO proactive_messages (
                proactive_uid, user_id, conversation_id, channel_id, trigger_type, opening_text,
                status, metadata_json, sent_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'sent', ?, ?, ?)
            """,
            (proactive_uid, user_id, conversation_id, channel_id, trigger_type, opening_text, json_dumps(metadata or {}), now, now),
        )
        return proactive_uid

    def mark_proactive_response(
        self,
        *,
        user_id: str,
        conversation_id: str,
        response_message_id: int,
        response_latency_minutes: float,
    ) -> None:
        row = self.db.fetchone(
            """
            SELECT * FROM proactive_messages
            WHERE user_id = ? AND conversation_id = ? AND status = 'sent'
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (user_id, conversation_id),
        )
        if row is None:
            return
        now = iso_utc_now()
        self.db.execute(
            """
            UPDATE proactive_messages
            SET accepted = 1, cold_response = 0, response_message_id = ?, response_latency_minutes = ?,
                status = 'responded', updated_at = ?
            WHERE id = ?
            """,
            (response_message_id, response_latency_minutes, now, row["id"]),
        )

    def mark_stale_proactive_messages(self, *, idle_hours: int) -> int:
        rows = self.db.fetchall(
            """
            SELECT * FROM proactive_messages
            WHERE status = 'sent'
            ORDER BY sent_at ASC
            """
        )
        updated = 0
        for row in rows:
            if self._older_than_hours(row["sent_at"], idle_hours):
                self.db.execute(
                    """
                    UPDATE proactive_messages
                    SET accepted = 0, cold_response = 1, status = 'expired', updated_at = ?
                    WHERE id = ?
                    """,
                    (iso_utc_now(), row["id"]),
                )
                updated += 1
        return updated

    def list_proactive_messages(self, *, limit: int = 100) -> list[ProactiveMessageRecord]:
        rows = self.db.fetchall(
            """
            SELECT * FROM proactive_messages
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._proactive_from_row(row) for row in rows]

    def get_proactive_message(self, proactive_uid: str) -> ProactiveMessageRecord | None:
        row = self.db.fetchone(
            """
            SELECT * FROM proactive_messages
            WHERE proactive_uid = ?
            LIMIT 1
            """,
            (proactive_uid,),
        )
        if row is None:
            return None
        return self._proactive_from_row(row)

    def update_proactive_metadata(self, proactive_uid: str, metadata_patch: dict[str, Any]) -> bool:
        row = self.db.fetchone(
            """
            SELECT metadata_json FROM proactive_messages
            WHERE proactive_uid = ?
            LIMIT 1
            """,
            (proactive_uid,),
        )
        if row is None:
            return False
        metadata = json_loads(row["metadata_json"], {})
        metadata.update(metadata_patch)
        cursor = self.db.execute(
            """
            UPDATE proactive_messages
            SET metadata_json = ?, updated_at = ?
            WHERE proactive_uid = ?
            """,
            (json_dumps(metadata), iso_utc_now(), proactive_uid),
        )
        return (cursor.rowcount or 0) > 0

    def get_companion_day_route(self, *, user_id: str, conversation_id: str, local_date: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM companion_day_routes
            WHERE user_id = ? AND conversation_id = ? AND local_date = ?
            LIMIT 1
            """,
            (user_id, conversation_id, local_date),
        )
        return None if row is None else self._companion_day_route_from_row(row)

    def get_companion_day_route_by_uid(self, route_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM companion_day_routes
            WHERE route_uid = ?
            LIMIT 1
            """,
            (route_uid,),
        )
        return None if row is None else self._companion_day_route_from_row(row)

    def create_companion_day_route(
        self,
        *,
        user_id: str,
        conversation_id: str,
        local_date: str,
        timezone: str,
        current_scene: str,
        mood_label: str,
        longing_level: float,
        quiet_mode: bool,
        route: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = iso_utc_now()
        route_uid = f"day_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO companion_day_routes (
                route_uid, user_id, conversation_id, local_date, timezone, status,
                current_scene, mood_label, longing_level, quiet_mode, route_json, metadata_json,
                generated_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                route_uid,
                user_id,
                conversation_id,
                local_date,
                timezone,
                current_scene,
                mood_label,
                longing_level,
                int(quiet_mode),
                json_dumps(route),
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        created = self.get_companion_day_route_by_uid(route_uid)
        if created is None:
            raise RuntimeError("companion day route insert failed")
        return created

    def update_companion_day_route(self, route_uid: str, fields: dict[str, Any]) -> bool:
        allowed = {"status", "current_scene", "mood_label", "longing_level", "quiet_mode", "route_json", "metadata_json"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key in {"route_json", "metadata_json"}:
                params.append(json_dumps(value))
            elif key == "quiet_mode":
                params.append(int(bool(value)))
            else:
                params.append(value)
        if not assignments:
            return False
        assignments.append("updated_at = ?")
        params.append(iso_utc_now())
        params.append(route_uid)
        cursor = self.db.execute(
            f"UPDATE companion_day_routes SET {', '.join(assignments)} WHERE route_uid = ?",
            params,
        )
        return (cursor.rowcount or 0) > 0

    def create_companion_day_event(
        self,
        *,
        route_uid: str,
        user_id: str,
        conversation_id: str,
        channel_id: str | None,
        event_type: str,
        status: str = "planned",
        content: str = "",
        card: dict[str, Any] | None = None,
        response_expected: bool = True,
        expectation_level: str = "clear",
        scheduled_for: str | None = None,
        sent_at: str | None = None,
        response_deadline_at: str | None = None,
        follow_up_of_event_uid: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = iso_utc_now()
        event_uid = f"dayevt_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO companion_day_events (
                event_uid, route_uid, user_id, conversation_id, channel_id, event_type, status,
                content, card_json, response_expected, expectation_level, scheduled_for, sent_at,
                response_deadline_at, follow_up_of_event_uid, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_uid,
                route_uid,
                user_id,
                conversation_id,
                channel_id,
                event_type,
                status,
                content,
                json_dumps(card or {}),
                int(response_expected),
                expectation_level,
                scheduled_for,
                sent_at,
                response_deadline_at,
                follow_up_of_event_uid,
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        created = self.get_companion_day_event(event_uid)
        if created is None:
            raise RuntimeError("companion day event insert failed")
        return created

    def get_companion_day_event(self, event_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM companion_day_events
            WHERE event_uid = ?
            LIMIT 1
            """,
            (event_uid,),
        )
        return None if row is None else self._companion_day_event_from_row(row)

    def list_companion_day_events(
        self,
        *,
        user_id: str,
        conversation_id: str,
        route_uid: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?", "conversation_id = ?"]
        params: list[Any] = [user_id, conversation_id]
        if route_uid:
            clauses.append("route_uid = ?")
            params.append(route_uid)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM companion_day_events
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        return [self._companion_day_event_from_row(row) for row in rows]

    def get_latest_unresponded_companion_day_event(self, *, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM companion_day_events
            WHERE user_id = ?
              AND conversation_id = ?
              AND response_expected = 1
              AND sent_at IS NOT NULL
              AND responded_at IS NULL
              AND status IN ('sent', 'waiting')
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (user_id, conversation_id),
        )
        return None if row is None else self._companion_day_event_from_row(row)

    def update_companion_day_event(self, event_uid: str, fields: dict[str, Any]) -> bool:
        allowed = {
            "status",
            "content",
            "card_json",
            "response_deadline_at",
            "responded_at",
            "response_message_id",
            "follow_up_sent_at",
            "feedback",
            "metadata_json",
        }
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key in {"card_json", "metadata_json"}:
                params.append(json_dumps(value))
            else:
                params.append(value)
        if not assignments:
            return False
        assignments.append("updated_at = ?")
        params.append(iso_utc_now())
        params.append(event_uid)
        cursor = self.db.execute(
            f"UPDATE companion_day_events SET {', '.join(assignments)} WHERE event_uid = ?",
            params,
        )
        return (cursor.rowcount or 0) > 0

    def create_shared_diary_entry(
        self,
        *,
        user_id: str,
        conversation_id: str,
        local_date: str,
        content: str,
        route_uid: str | None = None,
        event_uid: str | None = None,
        entry_type: str = "day_event",
        title: str = "",
        role_scope: str = "companion",
        source: str = "day_engine",
        importance: float = 0.5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        diary_uid = f"diary_{uuid.uuid4().hex}"
        now = iso_utc_now()
        self.db.execute(
            """
            INSERT INTO shared_diary_entries (
                diary_uid, user_id, conversation_id, route_uid, event_uid, local_date, entry_type,
                title, content, role_scope, source, importance, tags_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                diary_uid,
                user_id,
                conversation_id,
                route_uid,
                event_uid,
                local_date,
                entry_type,
                title,
                content,
                role_scope,
                source,
                importance,
                json_dumps(tags or []),
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        return diary_uid

    def list_shared_diary_entries(
        self,
        *,
        user_id: str,
        conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM shared_diary_entries
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        return [self._shared_diary_from_row(row) for row in rows]

    def create_reality_snapshot(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_type: str,
        source_label: str,
        status: str,
        payload: dict[str, Any] | None = None,
        summary_text: str = "",
        valid_from: str | None = None,
        valid_until: str | None = None,
        fetched_at: str | None = None,
        error_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot_uid = f"real_{uuid.uuid4().hex}"
        now = iso_utc_now()
        self.db.execute(
            """
            INSERT INTO reality_context_snapshots (
                snapshot_uid, user_id, conversation_id, source_type, source_label, status,
                payload_json, summary_text, valid_from, valid_until, fetched_at, error_text,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_uid,
                user_id,
                conversation_id,
                source_type,
                source_label,
                status,
                json_dumps(payload or {}),
                summary_text,
                valid_from,
                valid_until,
                fetched_at or now,
                error_text,
                json_dumps(metadata or {}),
                now,
            ),
        )
        snapshot = self.get_reality_snapshot(snapshot_uid)
        if snapshot is None:
            raise RuntimeError("reality snapshot insert failed")
        return snapshot

    def get_reality_snapshot(self, snapshot_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM reality_context_snapshots
            WHERE snapshot_uid = ?
            LIMIT 1
            """,
            (snapshot_uid,),
        )
        return None if row is None else self._reality_snapshot_from_row(row)

    def get_latest_reality_snapshot(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_type: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["user_id = ?", "conversation_id = ?"]
        params: list[Any] = [user_id, conversation_id]
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        row = self.db.fetchone(
            f"""
            SELECT * FROM reality_context_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        return None if row is None else self._reality_snapshot_from_row(row)

    def list_reality_snapshots(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?", "conversation_id = ?"]
        params: list[Any] = [user_id, conversation_id]
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM reality_context_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY fetched_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        return [self._reality_snapshot_from_row(row) for row in rows]

    def upsert_calendar_event(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_uid: str,
        source_label: str,
        event_hash: str,
        title: str,
        start_at: str,
        end_at: str | None = None,
        external_uid: str | None = None,
        timezone: str = "",
        location: str = "",
        is_all_day: bool = False,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = iso_utc_now()
        event_uid = f"calevt_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO calendar_context_events (
                event_uid, user_id, conversation_id, source_uid, source_label, external_uid,
                event_hash, title, start_at, end_at, timezone, location, is_all_day,
                status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, conversation_id, source_uid, event_hash) DO UPDATE SET
                source_label = excluded.source_label,
                external_uid = excluded.external_uid,
                title = excluded.title,
                start_at = excluded.start_at,
                end_at = excluded.end_at,
                timezone = excluded.timezone,
                location = excluded.location,
                is_all_day = excluded.is_all_day,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                event_uid,
                user_id,
                conversation_id,
                source_uid,
                source_label,
                external_uid,
                event_hash,
                title,
                start_at,
                end_at,
                timezone,
                location,
                int(is_all_day),
                status,
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        row = self.db.fetchone(
            """
            SELECT * FROM calendar_context_events
            WHERE user_id = ? AND conversation_id = ? AND source_uid = ? AND event_hash = ?
            LIMIT 1
            """,
            (user_id, conversation_id, source_uid, event_hash),
        )
        if row is None:
            raise RuntimeError("calendar event upsert failed")
        return self._calendar_event_from_row(row)

    def mark_calendar_source_events_stale(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_uid: str,
        keep_event_hashes: set[str],
    ) -> int:
        rows = self.db.fetchall(
            """
            SELECT event_hash FROM calendar_context_events
            WHERE user_id = ? AND conversation_id = ? AND source_uid = ? AND status = 'active'
            """,
            (user_id, conversation_id, source_uid),
        )
        stale_hashes = [row["event_hash"] for row in rows if row["event_hash"] not in keep_event_hashes]
        updated = 0
        for event_hash in stale_hashes:
            cursor = self.db.execute(
                """
                UPDATE calendar_context_events
                SET status = 'stale', updated_at = ?
                WHERE user_id = ? AND conversation_id = ? AND source_uid = ? AND event_hash = ?
                """,
                (iso_utc_now(), user_id, conversation_id, source_uid, event_hash),
            )
            updated += cursor.rowcount or 0
        return updated

    def list_calendar_events(
        self,
        *,
        user_id: str,
        conversation_id: str,
        start_at: str | None = None,
        end_at: str | None = None,
        include_stale: bool = False,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?", "conversation_id = ?"]
        params: list[Any] = [user_id, conversation_id]
        if not include_stale:
            clauses.append("status IN ('active', 'manual')")
        if start_at:
            clauses.append("(end_at IS NULL OR end_at >= ?)")
            params.append(start_at)
        if end_at:
            clauses.append("start_at <= ?")
            params.append(end_at)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM calendar_context_events
            WHERE {' AND '.join(clauses)}
            ORDER BY start_at ASC, id ASC
            LIMIT ?
            """,
            (*params, limit),
        )
        return [self._calendar_event_from_row(row) for row in rows]

    def get_calendar_event(self, event_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM calendar_context_events
            WHERE event_uid = ?
            LIMIT 1
            """,
            (event_uid,),
        )
        return None if row is None else self._calendar_event_from_row(row)

    def record_reality_source_audit(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_type: str,
        action: str,
        status: str,
        details: dict[str, Any] | None = None,
        error_text: str | None = None,
    ) -> str:
        audit_uid = f"reaudit_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO reality_source_audits (
                audit_uid, user_id, conversation_id, source_type, action, status,
                details_json, error_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_uid,
                user_id,
                conversation_id,
                source_type,
                action,
                status,
                json_dumps(details or {}),
                error_text,
                iso_utc_now(),
            ),
        )
        return audit_uid

    def list_reality_source_audits(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT * FROM reality_source_audits
            WHERE user_id = ? AND conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, conversation_id, limit),
        )
        return [self._reality_audit_from_row(row) for row in rows]

    def record_error(
        self,
        *,
        component: str,
        message: str,
        severity: str = "error",
        details: dict[str, Any] | None = None,
        related_task_uid: str | None = None,
        related_turn_uid: str | None = None,
    ) -> str:
        error_uid = f"err_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO error_events (
                error_uid, component, severity, message, details_json, related_task_uid, related_turn_uid,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                error_uid,
                component,
                severity,
                message,
                json_dumps(details or {}),
                related_task_uid,
                related_turn_uid,
                iso_utc_now(),
            ),
        )
        return error_uid

    def list_errors(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self.db.fetchall(
                """
                SELECT * FROM error_events
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            )
        else:
            rows = self.db.fetchall(
                """
                SELECT * FROM error_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) | {"details": json_loads(row["details_json"], {})} for row in rows]

    def record_attachment_artifact(
        self,
        *,
        platform_message_id: str | None,
        user_id: str,
        conversation_id: str,
        filename: str,
        content_type: str | None,
        artifact_type: str,
        extracted_text: str,
        summary_text: str,
        truncated: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO attachment_artifacts (
                artifact_uid, platform_message_id, user_id, conversation_id, filename, content_type,
                artifact_type, extracted_text, summary_text, truncated, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"att_{uuid.uuid4().hex}",
                platform_message_id,
                user_id,
                conversation_id,
                filename,
                content_type,
                artifact_type,
                extracted_text,
                summary_text,
                int(truncated),
                json_dumps(metadata or {}),
                iso_utc_now(),
            ),
        )

    def get_memories_for_review(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取需要复盘的记忆（超过 30 天未被引用的重要记忆）。

        筛选条件：
        - status = 'active'
        - last_used_at IS NULL 或 last_used_at 超过 30 天前
        - 按 importance 倒序排列（高重要性优先）
        - 排除已有 review_action = 'archive' 或 'update'（通过 metadata 标记）的记忆

        Returns:
            list of dict，每条格式同 list_long_term_memories，但附加 review_status 字段。
        """
        from datetime import datetime, timezone, timedelta

        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_iso = cutoff_dt.isoformat()

        rows = self.db.fetchall(
            """
            SELECT ltm.*, mus.hit_count, mus.last_hit_at
            FROM long_term_memories ltm
            LEFT JOIN memory_usage_stats mus ON mus.memory_uid = ltm.memory_uid
            WHERE ltm.user_id = ? AND ltm.status = 'active'
              AND (ltm.last_used_at IS NULL OR ltm.last_used_at < ?)
              AND (mus.last_hit_at IS NULL OR mus.last_hit_at < ?)
            ORDER BY ltm.importance DESC, ltm.updated_at ASC
            LIMIT ?
            """,
            (user_id, cutoff_iso, cutoff_iso, limit),
        )

        result: list[dict[str, Any]] = []
        for row in rows:
            metadata = json_loads(row["metadata_json"], {})
            # 跳过已被标记 review_action 为 archive 的记忆
            review_action = metadata.get("review_action")
            if review_action == "archive":
                continue
            result.append({
                "memory_uid": row["memory_uid"],
                "user_id": row["user_id"],
                "memory_type": row["memory_type"],
                "category": row["category"],
                "content": row["content"],
                "tags": json_loads(row["tags_json"], []),
                "confidence": float(row["confidence"]),
                "importance": float(row["importance"]),
                "last_used_at": row["last_used_at"],
                "hit_count": int(row["hit_count"] or 0),
                "last_hit_at": row["last_hit_at"],
                "review_action": review_action,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return result[:limit]

    def record_memory_review(self, memory_uid: str, action: str) -> bool:
        """记录记忆复盘结果。

        action 含义：
        - confirm：确认仍然有效，更新 last_used_at 为当前时间
        - archive：归档该记忆（设置 status = 'archived'）
        - update：标记需要更新，在 metadata 中记录 review_action = 'update'

        Returns:
            True 表示操作成功，False 表示记忆不存在或状态不符合条件。
        """
        allowed_actions = {"confirm", "archive", "update"}
        if action not in allowed_actions:
            raise ValueError(f"不合法的 action：{action!r}，允许值：{allowed_actions}")

        row = self.db.fetchone(
            "SELECT * FROM long_term_memories WHERE memory_uid = ? LIMIT 1",
            (memory_uid,),
        )
        if row is None:
            return False

        now = iso_utc_now()

        if action == "confirm":
            # 确认有效：更新 last_used_at，清除 review_action 标记
            metadata = json_loads(row["metadata_json"], {})
            metadata.pop("review_action", None)
            cursor = self.db.execute(
                """
                UPDATE long_term_memories
                SET last_used_at = ?, metadata_json = ?, updated_at = ?
                WHERE memory_uid = ? AND status = 'active'
                """,
                (now, json_dumps(metadata), now, memory_uid),
            )
            return (cursor.rowcount or 0) > 0

        if action == "archive":
            # 归档记忆
            cursor = self.db.execute(
                """
                UPDATE long_term_memories
                SET status = 'archived', updated_at = ?
                WHERE memory_uid = ? AND status = 'active'
                """,
                (now, memory_uid),
            )
            return (cursor.rowcount or 0) > 0

        if action == "update":
            # 标记需要更新（在 metadata 写入 review_action = 'update'）
            metadata = json_loads(row["metadata_json"], {})
            metadata["review_action"] = "update"
            metadata["review_flagged_at"] = now
            cursor = self.db.execute(
                """
                UPDATE long_term_memories
                SET metadata_json = ?, updated_at = ?
                WHERE memory_uid = ? AND status = 'active'
                """,
                (json_dumps(metadata), now, memory_uid),
            )
            return (cursor.rowcount or 0) > 0

        return False  # 不会到这里，但让静态分析满意

    def archive_long_term_memory(self, memory_uid: str) -> bool:
        cursor = self.db.execute(
            """
            UPDATE long_term_memories
            SET status = 'archived', updated_at = ?
            WHERE memory_uid = ? AND status = 'active'
            """,
            (iso_utc_now(), memory_uid),
        )
        return (cursor.rowcount or 0) > 0

    def restore_long_term_memory(self, memory_uid: str) -> bool:
        cursor = self.db.execute(
            """
            UPDATE long_term_memories
            SET status = 'active', updated_at = ?
            WHERE memory_uid = ? AND status = 'archived'
            """,
            (iso_utc_now(), memory_uid),
        )
        return (cursor.rowcount or 0) > 0

    def get_long_term_memory(self, memory_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT * FROM long_term_memories
            WHERE memory_uid = ?
            LIMIT 1
            """,
            (memory_uid,),
        )
        if row is None:
            return None
        return {
            "memory_uid": row["memory_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "channel_id": row["channel_id"],
            "guild_id": row["guild_id"],
            "memory_type": row["memory_type"],
            "category": row["category"],
            "content": row["content"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_memory_graph(self, user_id: str, limit: int = 50) -> dict:
        """返回记忆关系图数据（用于可视化），不依赖 LLM，纯本地计算。

        返回格式：
        {
            "nodes": [{"id": "mem-uid", "label": "content[:40]", "type": "preference", "importance": 0.8}],
            "edges": [{"source": "mem-uid-a", "target": "mem-uid-b", "weight": 0.6}]
        }

        边的计算逻辑：
        - 两条记忆共享相同 category → weight 0.5
        - 两条记忆 tags 有交集 → weight 0.6 * (交集数/并集数)（Jaccard 相似度）
        - 两条记忆 content 有词汇重叠（>2个词）→ weight 0.4
        只保留 weight >= 0.3 的边，取多条规则中最高权重。
        """
        rows = self.db.fetchall(
            """
            SELECT memory_uid, memory_type, category, content, tags_json, importance
            FROM long_term_memories
            WHERE user_id = ? AND status = 'active'
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

        nodes: list[dict] = []
        mems: list[dict] = []
        for row in rows:
            tags = json_loads(row["tags_json"], [])
            content = str(row["content"] or "")
            nodes.append(
                {
                    "id": row["memory_uid"],
                    "label": content[:40],
                    "type": row["memory_type"],
                    "importance": float(row["importance"]),
                }
            )
            mems.append(
                {
                    "uid": row["memory_uid"],
                    "category": str(row["category"] or ""),
                    "tags": set(str(t) for t in tags if t),
                    # 分词：小写、去除短词（长度<=2）
                    "words": set(
                        w for w in content.lower().split()
                        if len(w) > 2
                    ),
                }
            )

        edges: list[dict] = []
        n = len(mems)
        for i in range(n):
            for j in range(i + 1, n):
                a = mems[i]
                b = mems[j]
                best_weight = 0.0

                # 规则一：相同 category
                if a["category"] and b["category"] and a["category"] == b["category"]:
                    best_weight = max(best_weight, 0.5)

                # 规则二：tags Jaccard 相似度
                if a["tags"] and b["tags"]:
                    intersection = len(a["tags"] & b["tags"])
                    if intersection > 0:
                        union = len(a["tags"] | b["tags"])
                        jaccard = intersection / union if union > 0 else 0.0
                        tag_weight = round(0.6 * jaccard, 4)
                        best_weight = max(best_weight, tag_weight)

                # 规则三：content 词汇重叠（>2 个公共词）
                if a["words"] and b["words"]:
                    common_words = len(a["words"] & b["words"])
                    if common_words > 2:
                        best_weight = max(best_weight, 0.4)

                if best_weight >= 0.3:
                    edges.append(
                        {
                            "source": a["uid"],
                            "target": b["uid"],
                            "weight": round(best_weight, 4),
                        }
                    )

        return {"nodes": nodes, "edges": edges}

    def get_memory_health_score(self, user_id: str) -> dict[str, Any]:
        """计算记忆库的健康度评分（0-100），包含详细分析。

        评分维度：
        - coverage: 记忆类型覆盖率（10 种 type 各 10 分）
        - freshness: 近 30 天有更新的记忆占比
        - confidence: 平均可信度 × 100
        - diversity: 不同 category 的多样性（Shannon entropy），normalize 到 0-100

        返回：
        {
            "overall": 75,
            "coverage": 80,
            "freshness": 70,
            "confidence": 82,
            "diversity": 68,
            "total_memories": 45,
            "active_memories": 40,
            "stale_memories": 5,
            "top_categories": [{"category": "study", "count": 15}, ...],
            "type_distribution": {"preference": 8, "personal_fact": 12, ...},
            "recommendations": ["建议增加情感支持类记忆", ...],
        }
        """
        from datetime import datetime, timezone

        # 拉取所有 active 记忆（不限数量，用于统计）
        rows = self.db.fetchall(
            """
            SELECT memory_type, category, confidence, updated_at
            FROM long_term_memories
            WHERE user_id = ? AND status = 'active'
            """,
            (user_id,),
        )

        total_memories = len(rows)

        # 零记忆边界处理
        if total_memories == 0:
            return {
                "overall": 0,
                "coverage": 0,
                "freshness": 0,
                "confidence": 0,
                "diversity": 0,
                "total_memories": 0,
                "active_memories": 0,
                "stale_memories": 0,
                "top_categories": [],
                "type_distribution": {},
                "recommendations": [
                    "记忆库为空，建议开始与 AI 对话以积累记忆",
                    "尝试分享个人偏好和习惯以丰富记忆库",
                ],
            }

        # 所有已知记忆类型（10 种）
        KNOWN_TYPES = {
            "preference",
            "personal_fact",
            "relationship",
            "experience",
            "goal",
            "habit",
            "emotional",
            "knowledge",
            "schedule",
            "imported",
        }

        now_utc = datetime.now(timezone.utc)
        cutoff_30d = (now_utc - timedelta(days=30)).isoformat()
        cutoff_90d = (now_utc - timedelta(days=90)).isoformat()

        # 统计各维度
        type_counter: Counter = Counter()
        category_counter: Counter = Counter()
        confidence_sum = 0.0
        fresh_count = 0  # 近 30 天有更新
        stale_count = 0  # 超 90 天未更新

        for row in rows:
            mem_type = str(row["memory_type"] or "")
            category = str(row["category"] or "")
            conf = float(row["confidence"] or 0.0)
            updated_at = str(row["updated_at"] or "")

            type_counter[mem_type] += 1
            if category:
                category_counter[category] += 1
            confidence_sum += conf

            if updated_at >= cutoff_30d:
                fresh_count += 1
            if updated_at < cutoff_90d:
                stale_count += 1

        # --- coverage（覆盖率）---
        # 统计出现在 KNOWN_TYPES 中的类型数量，每种 10 分，上限 100
        covered_types = sum(1 for t in KNOWN_TYPES if type_counter.get(t, 0) > 0)
        coverage = min(100, covered_types * 10)

        # --- freshness（新鲜度）---
        freshness = round(fresh_count / total_memories * 100)

        # --- confidence（可信度）---
        avg_confidence = confidence_sum / total_memories
        confidence_score = round(avg_confidence * 100)

        # --- diversity（Shannon entropy normalize 到 0-100）---
        if len(category_counter) <= 1:
            diversity = 0
        else:
            total_cat = sum(category_counter.values())
            entropy = -sum(
                (p / total_cat) * math.log2(p / total_cat)
                for p in category_counter.values()
                if p > 0
            )
            # 最大熵 = log2(N 个 category)
            max_entropy = math.log2(len(category_counter))
            diversity = round((entropy / max_entropy) * 100) if max_entropy > 0 else 100

        # --- overall（综合得分）---
        overall = round((coverage + freshness + confidence_score + diversity) / 4)

        # --- top_categories（前 5 个 category）---
        top_categories = [
            {"category": cat, "count": cnt}
            for cat, cnt in category_counter.most_common(5)
        ]

        # --- type_distribution（各类型分布）---
        type_distribution = dict(type_counter)

        # --- recommendations（最多 3 条，基于规则）---
        recommendations: list[str] = []
        if freshness < 50:
            recommendations.append("记忆库较陈旧，建议近期多聊天以刷新记忆")
        if coverage < 50:
            recommendations.append("记忆类型覆盖不足，建议丰富对话内容（如分享情感、目标、习惯等）")
        if confidence_score < 60:
            recommendations.append("整体记忆置信度较低，建议确认并更新不准确的记忆条目")
        if diversity < 40 and not recommendations:
            recommendations.append("记忆 category 多样性不足，建议拓展话题范围")
        if not type_counter.get("emotional"):
            if len(recommendations) < 3:
                recommendations.append("建议增加情感支持类记忆（emotional 类型）")
        recommendations = recommendations[:3]

        return {
            "overall": overall,
            "coverage": coverage,
            "freshness": freshness,
            "confidence": confidence_score,
            "diversity": diversity,
            "total_memories": total_memories,
            "active_memories": total_memories,
            "stale_memories": stale_count,
            "top_categories": top_categories,
            "type_distribution": type_distribution,
            "recommendations": recommendations,
        }

    def list_long_term_memories(self, *, user_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = []
        query = "SELECT * FROM long_term_memories WHERE status = 'active'"
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.fetchall(query, params)
        usage_rows = self.db.fetchall("SELECT * FROM memory_usage_stats")
        usage_map = {row["memory_uid"]: dict(row) for row in usage_rows}
        result: list[dict[str, Any]] = []
        for row in rows:
            usage = usage_map.get(row["memory_uid"], {})
            result.append(
                {
                    "memory_uid": row["memory_uid"],
                    "user_id": row["user_id"],
                    "memory_type": row["memory_type"],
                    "category": row["category"],
                    "content": row["content"],
                    "tags": json_loads(row["tags_json"], []),
                    "confidence": float(row["confidence"]),
                    "importance": float(row["importance"]),
                    "last_used_at": row["last_used_at"],
                    "hit_count": int(usage.get("hit_count", 0)),
                    "last_hit_at": usage.get("last_hit_at"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result

    def export_memories(
        self,
        user_id: str | None = None,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        """导出记忆为字典列表，格式与 list_long_term_memories 兼容。"""
        params: list[Any] = []
        query = "SELECT * FROM long_term_memories WHERE status = ?"
        params.append(status)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY importance DESC, updated_at DESC"
        rows = self.db.fetchall(query, params)
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "memory_uid": row["memory_uid"],
                    "user_id": row["user_id"],
                    "conversation_id": row["conversation_id"],
                    "channel_id": row["channel_id"],
                    "guild_id": row["guild_id"],
                    "memory_type": row["memory_type"],
                    "category": row["category"],
                    "content": row["content"],
                    "tags": json_loads(row["tags_json"], []),
                    "source_message_ids": json_loads(row["source_message_ids_json"], []),
                    "confidence": float(row["confidence"]),
                    "importance": float(row["importance"]),
                    "status": row["status"],
                    "last_used_at": row["last_used_at"],
                    "supersedes_memory_uid": row["supersedes_memory_uid"],
                    "metadata": json_loads(row["metadata_json"], {}),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result

    def import_memories(
        self,
        records: list[dict[str, Any]],
        user_id: str,
    ) -> dict[str, Any]:
        """从记录列表导入记忆，通过 content+user_id 去重，跳过已存在的条目。

        返回 {imported: N, skipped: M, errors: [...]}
        """
        imported = 0
        skipped = 0
        errors: list[str] = []

        for idx, record in enumerate(records):
            try:
                content = str(record.get("content", "")).strip()
                if not content:
                    errors.append(f"记录 #{idx}: content 字段为空")
                    continue

                memory_type = str(record.get("memory_type", "imported")).strip() or "imported"
                category = str(record.get("category", "general")).strip() or "general"

                existing = self.db.fetchone(
                    """
                    SELECT id FROM long_term_memories
                    WHERE user_id = ? AND content = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (user_id, content),
                )
                if existing:
                    skipped += 1
                    continue

                now = iso_utc_now()
                memory_uid = f"mem_{uuid.uuid4().hex}"
                tags = record.get("tags", [])
                if not isinstance(tags, list):
                    tags = []
                source_message_ids = record.get("source_message_ids", [])
                if not isinstance(source_message_ids, list):
                    source_message_ids = []
                confidence = float(record.get("confidence", 0.8))
                importance = float(record.get("importance", 0.5))
                metadata = record.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["imported"] = True

                self.db.execute(
                    """
                    INSERT INTO long_term_memories (
                        memory_uid, user_id, conversation_id, channel_id, guild_id, memory_type, category,
                        content, tags_json, source_message_ids_json, confidence, importance, status,
                        last_used_at, supersedes_memory_uid, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, ?, ?, ?)
                    """,
                    (
                        memory_uid,
                        user_id,
                        record.get("conversation_id") or "",
                        record.get("channel_id"),
                        record.get("guild_id"),
                        memory_type,
                        category,
                        content,
                        json_dumps(tags),
                        json_dumps(source_message_ids),
                        confidence,
                        importance,
                        json_dumps(metadata),
                        now,
                        now,
                    ),
                )
                imported += 1
            except Exception as exc:
                errors.append(f"记录 #{idx}: {exc}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    def get_overview(self, *, user_id: str | None = None) -> dict[str, Any]:
        where_user = " WHERE user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        counts = {
            "messages": self._count("messages", where_user, params),
            "long_term_memories": self._count("long_term_memories", f"{where_user} {'AND' if where_user else 'WHERE'} status = 'active'" if user_id else " WHERE status = 'active'", params),
            "candidate_memories": self._count("candidate_memories", f"{where_user} {'AND' if where_user else 'WHERE'} status = 'pending'" if user_id else " WHERE status = 'pending'", params),
            "tasks_pending": self._count("background_tasks", " WHERE status IN ('pending', 'running', 'retrying')", ()),
            "errors_open": self._count("error_events", " WHERE status = 'open'", ()),
        }
        latest_turn = self.list_recent_turns(limit=1)
        latest_health = self.get_latest_health()
        proactive = self.list_proactive_messages(limit=50)
        accepted = [item for item in proactive if item.accepted is True]
        cold = [item for item in proactive if item.cold_response is True]
        counts["proactive_acceptance_rate"] = round(len(accepted) / max(len(proactive), 1), 3)
        counts["proactive_cold_rate"] = round(len(cold) / max(len(proactive), 1), 3)
        counts["latest_turn"] = latest_turn[0].turn_uid if latest_turn else None
        counts["health"] = [
            {
                "component": item.component,
                "status": item.status,
                "message": item.message,
                "latency_ms": item.latency_ms,
                "checked_at": item.checked_at,
            }
            for item in latest_health
        ]
        return counts

    def get_performance_summary(self, *, limit: int = 120, conversation_id: str | None = None) -> dict[str, Any]:
        turns = self.list_recent_turns(limit=limit, conversation_id=conversation_id)
        if not turns:
            return {
                "turn_count": 0,
                "avg_latency_ms": 0,
                "fallback_rate": 0,
                "request_types": {},
                "scenes": {},
                "modes": {},
            }
        latencies = [turn.latency_ms for turn in turns]
        request_counter = Counter(turn.request_type for turn in turns)
        scene_counter = Counter(turn.scene for turn in turns)
        mode_counter = Counter(turn.mode_text for turn in turns)
        fallback_count = sum(1 for turn in turns if turn.fallback_used)
        return {
            "turn_count": len(turns),
            "avg_latency_ms": round(sum(latencies) / max(len(latencies), 1), 2),
            "fallback_rate": round(fallback_count / max(len(turns), 1), 3),
            "request_types": dict(request_counter),
            "scenes": dict(scene_counter),
            "modes": dict(mode_counter),
        }

    def get_experience_summary(self, *, limit: int = 120, conversation_id: str | None = None) -> dict[str, Any]:
        if conversation_id:
            rows = self.db.fetchall(
                """
                SELECT * FROM experience_metric_events
                WHERE turn_uid IN (
                    SELECT turn_uid FROM turn_traces WHERE conversation_id = ?
                )
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
            metrics = [self._experience_from_row(row) for row in rows]
        else:
            metrics = self.list_experience_metrics(limit=limit)
        if not metrics:
            return {
                "sample_size": 0,
                "averages": {},
                "structure_distribution": {},
            }
        structure_counter = Counter(item.structure_type for item in metrics)
        return {
            "sample_size": len(metrics),
            "averages": {
                "persona_consistency": round(sum(item.persona_consistency for item in metrics) / len(metrics), 3),
                "memory_hit_quality": round(sum(item.memory_hit_quality for item in metrics) / len(metrics), 3),
                "memory_usage_rate": round(sum(item.memory_usage_rate for item in metrics) / len(metrics), 3),
                "proactive_acceptance": round(sum(item.proactive_acceptance for item in metrics) / len(metrics), 3),
                "repeated_comfort_rate": round(sum(item.repeated_comfort_rate for item in metrics) / len(metrics), 3),
                "over_explaining_rate": round(sum(item.over_explaining_rate for item in metrics) / len(metrics), 3),
                "tool_trace_leakage_rate": round(sum(item.tool_trace_leakage_rate for item in metrics) / len(metrics), 3),
                "proactive_cold_response_rate": round(sum(item.proactive_cold_response_rate for item in metrics) / len(metrics), 3),
            },
            "structure_distribution": dict(structure_counter),
        }

    def tail_log_file(
        self,
        log_file_path: str,
        *,
        lines: int = 180,
        redact: bool = True,
    ) -> list[str]:
        path = Path(log_file_path)
        if not path.exists() or lines <= 0:
            return []
        with path.open("r", encoding="utf-8", errors="ignore") as file:
            items = list(deque(file, maxlen=lines))
        if not redact:
            return items
        return [_redact_log_line(line) for line in items]

    def purge_old_observability(self, *, retention_days: int) -> dict[str, int]:
        if retention_days <= 0:
            return {}
        cutoff = (utc_now() - timedelta(days=retention_days)).isoformat()
        targets = (
            ("health_checks", "checked_at"),
            ("memory_snapshots", "created_at"),
            ("turn_traces", "created_at"),
            ("experience_metric_events", "created_at"),
            ("attachment_artifacts", "created_at"),
            ("error_events", "created_at"),
        )
        purged: dict[str, int] = {}
        for table, column in targets:
            cursor = self.db.execute(
                f"DELETE FROM {table} WHERE {column} < ?",
                (cutoff,),
            )
            purged[table] = int(cursor.rowcount or 0)
        return purged

    def _count(self, table: str, clause: str, params: tuple[Any, ...]) -> int:
        row = self.db.fetchone(f"SELECT COUNT(*) AS count FROM {table}{clause}", params)
        return int(row["count"]) if row else 0

    def _candidate_from_row(self, row: Any) -> CandidateMemoryRecord:
        return CandidateMemoryRecord(
            id=int(row["id"]),
            candidate_uid=row["candidate_uid"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            session_id=row["session_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            memory_type=row["memory_type"],
            category=row["category"],
            content=row["content"],
            tags=json_loads(row["tags_json"], []),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            reason=row["reason"],
            source_message_ids=json_loads(row["source_message_ids_json"], []),
            dedupe_signature=row["dedupe_signature"],
            status=row["status"],
            metadata=json_loads(row["metadata_json"], {}),
            approved_memory_uid=row["approved_memory_uid"],
            review_note=row["review_note"],
            reviewed_at=row["reviewed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _task_from_row(self, row: Any) -> BackgroundTaskRecord:
        return BackgroundTaskRecord(
            id=int(row["id"]),
            task_uid=row["task_uid"],
            task_type=row["task_type"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            session_id=row["session_id"],
            dedupe_key=row["dedupe_key"],
            payload=json_loads(row["payload_json"], {}),
            status=row["status"],
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            priority=float(row["priority"]),
            timeout_seconds=int(row["timeout_seconds"]),
            available_at=row["available_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            last_error=row["last_error"],
            result=json_loads(row["result_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _health_from_row(self, row: Any) -> HealthCheckRecord:
        return HealthCheckRecord(
            id=int(row["id"]),
            component=row["component"],
            status=row["status"],
            message=row["message"],
            latency_ms=float(row["latency_ms"]),
            details=json_loads(row["details_json"], {}),
            checked_at=row["checked_at"],
        )

    def _turn_trace_from_row(self, row: Any) -> TurnTraceRecord:
        return TurnTraceRecord(
            id=int(row["id"]),
            turn_uid=row["turn_uid"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            session_id=row["session_id"],
            user_message_id=row["user_message_id"],
            assistant_message_id=row["assistant_message_id"],
            request_type=row["request_type"],
            reply_goal=row["reply_goal"],
            scene=row["scene"],
            mode_text=row["mode_text"],
            model_name=row["model_name"],
            backup_model_name=row["backup_model_name"],
            fallback_used=bool(row["fallback_used"]),
            latency_ms=float(row["latency_ms"]),
            user_input=row["user_input"],
            assistant_reply=row["assistant_reply"],
            attachments=json_loads(row["attachments_json"], []),
            search_context=json_loads(row["search_context_json"], []),
            planning=json_loads(row["planning_json"], {}),
            retrieval=json_loads(row["retrieval_json"], {}),
            metrics=json_loads(row["metrics_json"], {}),
            error_text=row["error_text"],
            created_at=row["created_at"],
        )

    def _experience_from_row(self, row: Any) -> ExperienceMetricsRecord:
        return ExperienceMetricsRecord(
            id=int(row["id"]),
            turn_uid=row["turn_uid"],
            persona_consistency=float(row["persona_consistency"]),
            memory_hit_quality=float(row["memory_hit_quality"]),
            memory_usage_rate=float(row["memory_usage_rate"]),
            proactive_acceptance=float(row["proactive_acceptance"]),
            repeated_comfort_rate=float(row["repeated_comfort_rate"]),
            over_explaining_rate=float(row["over_explaining_rate"]),
            tool_trace_leakage_rate=float(row["tool_trace_leakage_rate"]),
            proactive_cold_response_rate=float(row["proactive_cold_response_rate"]),
            structure_type=row["structure_type"],
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _proactive_from_row(self, row: Any) -> ProactiveMessageRecord:
        accepted = row["accepted"]
        cold_response = row["cold_response"]
        return ProactiveMessageRecord(
            id=int(row["id"]),
            proactive_uid=row["proactive_uid"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            channel_id=row["channel_id"],
            trigger_type=row["trigger_type"],
            opening_text=row["opening_text"],
            status=row["status"],
            accepted=None if accepted is None else bool(accepted),
            cold_response=None if cold_response is None else bool(cold_response),
            response_message_id=row["response_message_id"],
            response_latency_minutes=row["response_latency_minutes"],
            metadata=json_loads(row["metadata_json"], {}),
            sent_at=row["sent_at"],
            updated_at=row["updated_at"],
        )

    def _companion_day_route_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "route_uid": row["route_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "local_date": row["local_date"],
            "timezone": row["timezone"],
            "status": row["status"],
            "current_scene": row["current_scene"],
            "mood_label": row["mood_label"],
            "longing_level": float(row["longing_level"]),
            "quiet_mode": bool(row["quiet_mode"]),
            "route": json_loads(row["route_json"], {}),
            "metadata": json_loads(row["metadata_json"], {}),
            "generated_at": row["generated_at"],
            "updated_at": row["updated_at"],
        }

    def _companion_day_event_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "event_uid": row["event_uid"],
            "route_uid": row["route_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "channel_id": row["channel_id"],
            "event_type": row["event_type"],
            "status": row["status"],
            "content": row["content"],
            "card": json_loads(row["card_json"], {}),
            "response_expected": bool(row["response_expected"]),
            "expectation_level": row["expectation_level"],
            "scheduled_for": row["scheduled_for"],
            "sent_at": row["sent_at"],
            "response_deadline_at": row["response_deadline_at"],
            "responded_at": row["responded_at"],
            "response_message_id": row["response_message_id"],
            "follow_up_of_event_uid": row["follow_up_of_event_uid"],
            "follow_up_sent_at": row["follow_up_sent_at"],
            "feedback": row["feedback"],
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _shared_diary_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "diary_uid": row["diary_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "route_uid": row["route_uid"],
            "event_uid": row["event_uid"],
            "local_date": row["local_date"],
            "entry_type": row["entry_type"],
            "title": row["title"],
            "content": row["content"],
            "role_scope": row["role_scope"],
            "source": row["source"],
            "importance": float(row["importance"]),
            "tags": json_loads(row["tags_json"], []),
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _reality_snapshot_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "snapshot_uid": row["snapshot_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "source_type": row["source_type"],
            "source_label": row["source_label"],
            "status": row["status"],
            "payload": json_loads(row["payload_json"], {}),
            "summary_text": row["summary_text"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "fetched_at": row["fetched_at"],
            "error_text": row["error_text"],
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }

    def _calendar_event_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "event_uid": row["event_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "source_uid": row["source_uid"],
            "source_label": row["source_label"],
            "external_uid": row["external_uid"],
            "event_hash": row["event_hash"],
            "title": row["title"],
            "start_at": row["start_at"],
            "end_at": row["end_at"],
            "timezone": row["timezone"],
            "location": row["location"],
            "is_all_day": bool(row["is_all_day"]),
            "status": row["status"],
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _reality_audit_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "audit_uid": row["audit_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "source_type": row["source_type"],
            "action": row["action"],
            "status": row["status"],
            "details": json_loads(row["details_json"], {}),
            "error_text": row["error_text"],
            "created_at": row["created_at"],
        }

    def _shift_seconds(self, iso_timestamp: str, seconds: int) -> str:
        from datetime import datetime, timedelta

        return (datetime.fromisoformat(iso_timestamp) + timedelta(seconds=seconds)).isoformat()

    def _seconds_since(self, created_at, now) -> float:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=now.tzinfo)
        return max((now - created_at).total_seconds(), 0.0)

    def _task_is_stale(self, row: Any, *, grace_seconds: int = 60) -> bool:
        started_at = parse_iso8601(row["started_at"]) if row["started_at"] else None
        if started_at is None:
            return False
        now = utc_now()
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=now.tzinfo)
        timeout_seconds = int(row["timeout_seconds"] or 0)
        return started_at + timedelta(seconds=timeout_seconds + grace_seconds) <= now

    def _older_than_hours(self, iso_timestamp: str, hours: int) -> bool:
        from datetime import datetime, timedelta, timezone

        try:
            created_at = datetime.fromisoformat(iso_timestamp)
        except ValueError:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at + timedelta(hours=hours) <= datetime.now(timezone.utc)
