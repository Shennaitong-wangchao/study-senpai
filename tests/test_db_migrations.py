from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from src.db.database import Database
from src.db.migrations import MIGRATIONS, _migration_20260425_message_idempotency


@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "app.sqlite3"))
    try:
        yield db
    finally:
        db.close()


def test_database_initialize_records_migrations_and_creates_context_tables(database: Database) -> None:
    database.initialize()
    database.initialize()

    migration_rows = database.fetchall("SELECT name FROM schema_migrations ORDER BY name")
    table_rows = database.fetchall(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN (
            'app_settings',
            'dashboard_security_events',
            'companion_day_routes',
            'shared_diary_entries',
            'reality_context_snapshots',
            'calendar_context_events'
          )
        ORDER BY name
        """
    )

    assert [row["name"] for row in migration_rows] == sorted(migration.name for migration in MIGRATIONS)
    assert [row["name"] for row in table_rows] == [
        "app_settings",
        "calendar_context_events",
        "companion_day_routes",
        "dashboard_security_events",
        "reality_context_snapshots",
        "shared_diary_entries",
    ]


def test_message_idempotency_migration_marks_existing_duplicates_unclaimed() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                platform_message_id TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO messages (platform, platform_message_id) VALUES (?, ?)",
            [
                ("discord", "message-1"),
                ("discord", "message-1"),
                ("discord", "message-2"),
                ("discord", None),
            ],
        )

        _migration_20260425_message_idempotency(connection)
        _migration_20260425_message_idempotency(connection)

        rows = connection.execute(
            """
            SELECT platform_message_id, idempotency_claimed
            FROM messages
            ORDER BY id
            """
        ).fetchall()

        columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)").fetchall()}

        assert "idempotency_claimed" in columns
        assert [(row["platform_message_id"], row["idempotency_claimed"]) for row in rows] == [
            ("message-1", 1),
            ("message-1", 0),
            ("message-2", 1),
            (None, 1),
        ]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO messages (platform, platform_message_id, idempotency_claimed)
                VALUES (?, ?, ?)
                """,
                ("discord", "message-1", 1),
            )
    finally:
        connection.close()
