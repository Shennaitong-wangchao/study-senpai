from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Migration:
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _execute_statements(connection: sqlite3.Connection, statements: list[str]) -> None:
    cursor = connection.cursor()
    for statement in statements:
        cursor.execute(statement)


def _migration_20260416_dashboard_p1(connection: sqlite3.Connection) -> None:
    _execute_statements(
        connection,
        [
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS dashboard_security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uid TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                username TEXT,
                source_ip TEXT,
                success INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_dashboard_security_events_created ON dashboard_security_events(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dashboard_security_events_source ON dashboard_security_events(source_ip, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS dashboard_action_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_uid TEXT NOT NULL UNIQUE,
                actor_username TEXT NOT NULL,
                source_ip TEXT,
                action_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                scope_user_id TEXT,
                scope_conversation_id TEXT,
                status TEXT NOT NULL DEFAULT 'applied',
                undo_available INTEGER NOT NULL DEFAULT 0,
                details_json TEXT NOT NULL DEFAULT '{}',
                undo_payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                undone_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_dashboard_action_audits_created ON dashboard_action_audits(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dashboard_action_audits_scope ON dashboard_action_audits(scope_user_id, scope_conversation_id, created_at DESC)",
        ],
    )


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _migration_20260425_message_idempotency(connection: sqlite3.Connection) -> None:
    if not _column_exists(connection, "messages", "idempotency_claimed"):
        connection.execute("ALTER TABLE messages ADD COLUMN idempotency_claimed INTEGER NOT NULL DEFAULT 1")

    duplicate_groups = connection.execute(
        """
        SELECT platform, platform_message_id, MIN(id) AS keep_id
        FROM messages
        WHERE platform_message_id IS NOT NULL
        GROUP BY platform, platform_message_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in duplicate_groups:
        connection.execute(
            """
            UPDATE messages
            SET idempotency_claimed = 0
            WHERE platform = ?
              AND platform_message_id = ?
              AND id != ?
            """,
            (row["platform"], row["platform_message_id"], row["keep_id"]),
        )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_platform_message_unique
        ON messages(platform, platform_message_id)
        WHERE platform_message_id IS NOT NULL AND idempotency_claimed = 1
        """
    )


def _migration_20260426_companion_day_engine(connection: sqlite3.Connection) -> None:
    _execute_statements(
        connection,
        [
            """
            CREATE TABLE IF NOT EXISTS companion_day_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                local_date TEXT NOT NULL,
                timezone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                current_scene TEXT NOT NULL DEFAULT '',
                mood_label TEXT NOT NULL DEFAULT '',
                longing_level REAL NOT NULL DEFAULT 0.7,
                quiet_mode INTEGER NOT NULL DEFAULT 0,
                route_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                generated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, conversation_id, local_date)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_companion_day_routes_scope ON companion_day_routes(user_id, conversation_id, local_date DESC)",
            """
            CREATE TABLE IF NOT EXISTS companion_day_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uid TEXT NOT NULL UNIQUE,
                route_uid TEXT NOT NULL,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                channel_id TEXT,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                content TEXT NOT NULL DEFAULT '',
                card_json TEXT NOT NULL DEFAULT '{}',
                response_expected INTEGER NOT NULL DEFAULT 1,
                expectation_level TEXT NOT NULL DEFAULT 'clear',
                scheduled_for TEXT,
                sent_at TEXT,
                response_deadline_at TEXT,
                responded_at TEXT,
                response_message_id INTEGER,
                follow_up_of_event_uid TEXT,
                follow_up_sent_at TEXT,
                feedback TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_companion_day_events_scope ON companion_day_events(user_id, conversation_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_companion_day_events_route ON companion_day_events(route_uid, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS shared_diary_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                diary_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                route_uid TEXT,
                event_uid TEXT,
                local_date TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                role_scope TEXT NOT NULL DEFAULT 'companion',
                source TEXT NOT NULL DEFAULT 'day_engine',
                importance REAL NOT NULL DEFAULT 0.5,
                tags_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_shared_diary_entries_scope ON shared_diary_entries(user_id, conversation_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_shared_diary_entries_date ON shared_diary_entries(user_id, local_date DESC)",
        ],
    )


def _migration_20260426_reality_context(connection: sqlite3.Connection) -> None:
    _execute_statements(
        connection,
        [
            """
            CREATE TABLE IF NOT EXISTS reality_context_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                payload_json TEXT NOT NULL DEFAULT '{}',
                summary_text TEXT NOT NULL DEFAULT '',
                valid_from TEXT,
                valid_until TEXT,
                fetched_at TEXT NOT NULL,
                error_text TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_reality_context_snapshots_scope ON reality_context_snapshots(user_id, conversation_id, source_type, fetched_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS calendar_context_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_uid TEXT NOT NULL,
                source_label TEXT NOT NULL DEFAULT '',
                external_uid TEXT,
                event_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT,
                timezone TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                is_all_day INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, conversation_id, source_uid, event_hash)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_calendar_context_events_scope ON calendar_context_events(user_id, conversation_id, start_at ASC)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_context_events_source ON calendar_context_events(source_uid, status, start_at ASC)",
            """
            CREATE TABLE IF NOT EXISTS reality_source_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                details_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_reality_source_audits_scope ON reality_source_audits(user_id, conversation_id, created_at DESC)",
        ],
    )


def _migration_20260611_study_system(connection: sqlite3.Connection) -> None:
    """学习目标追踪和间隔复习系统迁移（幂等）。"""
    _execute_statements(
        connection,
        [
            """
            CREATE TABLE IF NOT EXISTS study_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                subject TEXT,
                target_date TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                progress_pct INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_study_goals_user ON study_goals(user_id, status, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS review_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                goal_uid TEXT,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                subject TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                ease_factor REAL NOT NULL DEFAULT 2.5,
                interval_days INTEGER NOT NULL DEFAULT 1,
                repetitions INTEGER NOT NULL DEFAULT 0,
                next_review_at TEXT,
                last_reviewed_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_review_items_user ON review_items(user_id, status, next_review_at ASC)",
            "CREATE INDEX IF NOT EXISTS idx_review_items_goal ON review_items(goal_uid, status)",
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uid TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                goal_uid TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                focus_minutes INTEGER NOT NULL DEFAULT 0,
                items_reviewed INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_study_sessions_user ON study_sessions(user_id, started_at DESC)",
        ],
    )


MIGRATIONS: list[Migration] = [
    Migration(name="20260416_dashboard_p1", apply=_migration_20260416_dashboard_p1),
    Migration(name="20260425_message_idempotency", apply=_migration_20260425_message_idempotency),
    Migration(name="20260426_companion_day_engine", apply=_migration_20260426_companion_day_engine),
    Migration(name="20260426_reality_context", apply=_migration_20260426_reality_context),
    Migration(name="20260611_study_system", apply=_migration_20260611_study_system),
]
