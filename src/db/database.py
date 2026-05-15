from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from src.db.migrations import MIGRATIONS
from src.db.schema import SCHEMA_STATEMENTS


class Database:
    def __init__(self, database_path: str) -> None:
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._configure_connection()

    def _configure_connection(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")

    def initialize(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            cursor = self._connection.cursor()
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            for migration in MIGRATIONS:
                applied = cursor.execute(
                    "SELECT name FROM schema_migrations WHERE name = ? LIMIT 1",
                    (migration.name,),
                ).fetchone()
                if applied is not None:
                    continue
                migration.apply(self._connection)
                cursor.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, datetime('now'))",
                    (migration.name,),
                )
            self._connection.commit()

    def execute(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(query, tuple(params))
            self._connection.commit()
            return cursor

    def executemany(self, query: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.executemany(query, rows)
            self._connection.commit()

    def fetchone(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(query, tuple(params))
            return cursor.fetchone()

    def fetchall(self, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(query, tuple(params))
            return cursor.fetchall()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
