from __future__ import annotations

import uuid
import sqlite3
from typing import Any

from src.core.types import ConversationScope, MessageContext
from src.db.database import Database
from src.memory.models import (
    ConversationSummaryRecord,
    LongTermMemoryRecord,
    MessageRecord,
    RelationshipStateRecord,
    SessionMemoryRecord,
    StructuredFactRecord,
)
from src.utils.json_utils import json_dumps, json_loads
from src.utils.time_utils import iso_utc_now, parse_iso8601, utc_now


class MemoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def insert_message(
        self,
        scope: ConversationScope,
        *,
        sender_type: str,
        content: str,
        context: MessageContext,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        platform_message_id = (context.platform_message_id or "").strip() or None
        if platform_message_id is not None:
            existing = self.get_message_by_platform_id(scope.platform, platform_message_id)
            if existing is not None:
                return existing

        timestamp = iso_utc_now()
        try:
            cursor = self.db.execute(
                """
                INSERT INTO messages (
                    platform, conversation_id, session_id, platform_message_id, sender_type,
                    author_id, user_id, channel_id, guild_id, reply_to_platform_message_id,
                    thread_id, content, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope.platform,
                    scope.conversation_id,
                    scope.session_id,
                    platform_message_id,
                    sender_type,
                    context.author_id,
                    scope.user_id,
                    scope.channel_id,
                    scope.guild_id,
                    context.reply_to_platform_message_id,
                    context.thread_id,
                    content,
                    json_dumps(metadata or {}),
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError:
            if platform_message_id is not None:
                existing = self.get_message_by_platform_id(scope.platform, platform_message_id)
                if existing is not None:
                    return existing
            raise
        row = self.db.fetchone("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,))
        return self._message_from_row(row)

    def get_message_by_platform_id(self, platform: str, platform_message_id: str) -> MessageRecord | None:
        normalized = (platform_message_id or "").strip()
        if not normalized:
            return None
        row = self.db.fetchone(
            """
            SELECT * FROM messages
            WHERE platform = ?
              AND platform_message_id = ?
              AND idempotency_claimed = 1
            ORDER BY id ASC
            LIMIT 1
            """,
            (platform, normalized),
        )
        return self._message_from_row(row) if row else None

    def get_latest_message(self, conversation_id: str) -> MessageRecord | None:
        row = self.db.fetchone(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        return self._message_from_row(row) if row else None

    def get_message_by_id(self, message_id: int) -> MessageRecord | None:
        row = self.db.fetchone("SELECT * FROM messages WHERE id = ? LIMIT 1", (message_id,))
        return self._message_from_row(row) if row else None

    def list_recent_messages(
        self,
        conversation_id: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[MessageRecord]:
        params: list[Any] = [conversation_id]
        query = "SELECT * FROM messages WHERE conversation_id = ?"
        if before_message_id is not None:
            query += " AND id < ?"
            params.append(before_message_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.db.fetchall(query, params)
        return [self._message_from_row(row) for row in reversed(rows)]

    def list_messages_after(self, conversation_id: str, after_message_id: int) -> list[MessageRecord]:
        rows = self.db.fetchall(
            """
            SELECT * FROM messages
            WHERE conversation_id = ? AND id > ?
            ORDER BY id ASC
            """,
            (conversation_id, after_message_id),
        )
        return [self._message_from_row(row) for row in rows]

    def get_latest_user_message(self, conversation_id: str) -> MessageRecord | None:
        row = self.db.fetchone(
            """
            SELECT * FROM messages
            WHERE conversation_id = ? AND sender_type = 'user'
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        return self._message_from_row(row) if row else None

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

    def add_or_refresh_session_memory(
        self,
        scope: ConversationScope,
        *,
        memory_type: str,
        content: str,
        priority: float,
        confidence: float,
        source_message_ids: list[int],
        expires_at: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = iso_utc_now()
        existing = self.db.fetchone(
            """
            SELECT * FROM session_memories
            WHERE session_id = ? AND memory_type = ? AND content = ? AND status = 'active'
            LIMIT 1
            """,
            (scope.session_id, memory_type, content),
        )
        merged_sources = source_message_ids
        if existing:
            merged_sources = sorted(
                set(json_loads(existing["source_message_ids_json"], []) + source_message_ids)
            )
            merged_metadata = {**json_loads(existing["metadata_json"], {}), **(metadata or {})}
            self.db.execute(
                """
                UPDATE session_memories
                SET priority = ?, confidence = ?, source_message_ids_json = ?, metadata_json = ?,
                    updated_at = ?, last_active_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    max(float(existing["priority"]), priority),
                    max(float(existing["confidence"]), confidence),
                    json_dumps(merged_sources),
                    json_dumps(merged_metadata),
                    now,
                    now,
                    expires_at,
                    existing["id"],
                ),
            )
            return

        self.db.execute(
            """
            INSERT INTO session_memories (
                session_id, conversation_id, user_id, channel_id, guild_id, memory_type, content,
                priority, confidence, status, source_message_ids_json, metadata_json,
                created_at, updated_at, last_active_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                scope.session_id,
                scope.conversation_id,
                scope.user_id,
                scope.channel_id,
                scope.guild_id,
                memory_type,
                content,
                priority,
                confidence,
                json_dumps(merged_sources),
                json_dumps(metadata or {}),
                now,
                now,
                now,
                expires_at,
            ),
        )

    def list_active_session_memories(
        self,
        scope: ConversationScope,
        *,
        limit: int,
    ) -> list[SessionMemoryRecord]:
        now = utc_now()
        rows = self.db.fetchall(
            """
            SELECT * FROM session_memories
            WHERE conversation_id = ? AND session_id = ? AND status = 'active'
            ORDER BY priority DESC, updated_at DESC
            LIMIT ?
            """,
            (scope.conversation_id, scope.session_id, limit),
        )
        records = [self._session_memory_from_row(row) for row in rows]
        return [
            record
            for record in records
            if record.expires_at is None or (parse_iso8601(record.expires_at) and parse_iso8601(record.expires_at) > now)
        ]

    def list_recent_active_session_memories_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> list[SessionMemoryRecord]:
        now = utc_now()
        rows = self.db.fetchall(
            """
            SELECT * FROM session_memories
            WHERE conversation_id = ? AND status = 'active'
            ORDER BY priority DESC, updated_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        records = [self._session_memory_from_row(row) for row in rows]
        return [
            record
            for record in records
            if record.expires_at is None or (parse_iso8601(record.expires_at) and parse_iso8601(record.expires_at) > now)
        ]

    def insert_or_merge_long_term_memory(
        self,
        scope: ConversationScope,
        *,
        memory_type: str,
        category: str,
        content: str,
        tags: list[str],
        confidence: float,
        importance: float,
        source_message_ids: list[int],
        metadata: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        now = iso_utc_now()
        query = """
            SELECT * FROM long_term_memories
            WHERE user_id = ? AND memory_type = ? AND content = ? AND status = 'active'
            LIMIT 1
            """
        params = (scope.user_id, memory_type, content)
        if connection is None:
            existing = self.db.fetchone(query, params)
        else:
            existing_cursor = connection.execute(query, params)
            existing = existing_cursor.fetchone()
        if existing:
            merged_tags = sorted(set(json_loads(existing["tags_json"], []) + tags))
            merged_sources = sorted(
                set(json_loads(existing["source_message_ids_json"], []) + source_message_ids)
            )
            merged_metadata = {**json_loads(existing["metadata_json"], {}), **(metadata or {})}
            update_query = """
                UPDATE long_term_memories
                SET confidence = ?, importance = ?, tags_json = ?, source_message_ids_json = ?,
                    metadata_json = ?, updated_at = ?
                WHERE id = ?
                """
            update_params = (
                max(float(existing["confidence"]), confidence),
                max(float(existing["importance"]), importance),
                json_dumps(merged_tags),
                json_dumps(merged_sources),
                json_dumps(merged_metadata),
                now,
                existing["id"],
            )
            if connection is None:
                self.db.execute(update_query, update_params)
            else:
                connection.execute(update_query, update_params)
            return str(existing["memory_uid"])

        memory_uid = f"mem_{uuid.uuid4().hex}"
        insert_query = """
            INSERT INTO long_term_memories (
                memory_uid, user_id, conversation_id, channel_id, guild_id, memory_type, category,
                content, tags_json, source_message_ids_json, confidence, importance, status,
                last_used_at, supersedes_memory_uid, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, ?, ?, ?)
            """
        insert_params = (
            memory_uid,
            scope.user_id,
            scope.conversation_id,
            scope.channel_id,
            scope.guild_id,
            memory_type,
            category,
            content,
            json_dumps(tags),
            json_dumps(source_message_ids),
            confidence,
            importance,
            json_dumps(metadata or {}),
            now,
            now,
        )
        if connection is None:
            self.db.execute(insert_query, insert_params)
        else:
            connection.execute(insert_query, insert_params)
        return memory_uid

    def list_active_long_term_memories(self, user_id: str) -> list[LongTermMemoryRecord]:
        rows = self.db.fetchall(
            """
            SELECT * FROM long_term_memories
            WHERE user_id = ? AND status = 'active'
            ORDER BY importance DESC, updated_at DESC
            """,
            (user_id,),
        )
        return [self._long_term_memory_from_row(row) for row in rows]

    def touch_long_term_memories(self, memory_uids: list[str]) -> None:
        if not memory_uids:
            return
        now = iso_utc_now()
        placeholders = ", ".join("?" for _ in memory_uids)
        self.db.execute(
            f"UPDATE long_term_memories SET last_used_at = ? WHERE memory_uid IN ({placeholders})",
            (now, *memory_uids),
        )

    def upsert_structured_fact(
        self,
        user_id: str,
        *,
        namespace: str,
        key: str,
        value: str,
        confidence: float,
        source_message_ids: list[int],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = iso_utc_now()
        existing = self.db.fetchone(
            """
            SELECT * FROM structured_facts
            WHERE user_id = ? AND namespace = ? AND key = ?
            LIMIT 1
            """,
            (user_id, namespace, key),
        )
        if existing:
            merged_sources = sorted(
                set(json_loads(existing["source_message_ids_json"], []) + source_message_ids)
            )
            merged_metadata = {**json_loads(existing["metadata_json"], {}), **(metadata or {})}
            self.db.execute(
                """
                UPDATE structured_facts
                SET value = ?, confidence = ?, source_message_ids_json = ?, metadata_json = ?,
                    status = 'active', updated_at = ?
                WHERE id = ?
                """,
                (
                    value,
                    max(float(existing["confidence"]), confidence),
                    json_dumps(merged_sources),
                    json_dumps(merged_metadata),
                    now,
                    existing["id"],
                ),
            )
            return

        self.db.execute(
            """
            INSERT INTO structured_facts (
                user_id, namespace, key, value, confidence, source_message_ids_json, status,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                user_id,
                namespace,
                key,
                value,
                confidence,
                json_dumps(source_message_ids),
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )

    def list_structured_facts(self, user_id: str, *, limit: int) -> list[StructuredFactRecord]:
        rows = self.db.fetchall(
            """
            SELECT * FROM structured_facts
            WHERE user_id = ? AND status = 'active'
            ORDER BY confidence DESC, updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [self._structured_fact_from_row(row) for row in rows]

    def get_structured_fact(
        self,
        user_id: str,
        *,
        namespace: str,
        key: str,
    ) -> StructuredFactRecord | None:
        row = self.db.fetchone(
            """
            SELECT * FROM structured_facts
            WHERE user_id = ? AND namespace = ? AND key = ? AND status = 'active'
            LIMIT 1
            """,
            (user_id, namespace, key),
        )
        return self._structured_fact_from_row(row) if row else None

    def upsert_relationship_state(
        self,
        user_id: str,
        *,
        dimension: str,
        value: str,
        weight: float,
        confidence: float,
        note: str | None,
        source_message_ids: list[int],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = iso_utc_now()
        existing = self.db.fetchone(
            """
            SELECT * FROM relationship_states
            WHERE user_id = ? AND dimension = ?
            LIMIT 1
            """,
            (user_id, dimension),
        )
        if existing:
            merged_sources = sorted(
                set(json_loads(existing["source_message_ids_json"], []) + source_message_ids)
            )
            merged_metadata = {**json_loads(existing["metadata_json"], {}), **(metadata or {})}
            self.db.execute(
                """
                UPDATE relationship_states
                SET value = ?, weight = ?, confidence = ?, note = ?, source_message_ids_json = ?,
                    metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    value,
                    max(float(existing["weight"]), weight),
                    max(float(existing["confidence"]), confidence),
                    note,
                    json_dumps(merged_sources),
                    json_dumps(merged_metadata),
                    now,
                    existing["id"],
                ),
            )
            return

        self.db.execute(
            """
            INSERT INTO relationship_states (
                user_id, dimension, value, weight, confidence, note, source_message_ids_json,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                dimension,
                value,
                weight,
                confidence,
                note,
                json_dumps(source_message_ids),
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )

    def list_relationship_states(self, user_id: str) -> list[RelationshipStateRecord]:
        rows = self.db.fetchall(
            """
            SELECT * FROM relationship_states
            WHERE user_id = ?
            ORDER BY weight DESC, updated_at DESC
            """,
            (user_id,),
        )
        return [self._relationship_state_from_row(row) for row in rows]

    def get_latest_summary(self, conversation_id: str) -> ConversationSummaryRecord | None:
        row = self.db.fetchone(
            """
            SELECT * FROM conversation_summaries
            WHERE conversation_id = ?
            ORDER BY message_end_id DESC, version DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        return self._summary_from_row(row) if row else None

    def insert_summary(
        self,
        scope: ConversationScope,
        *,
        content: str,
        message_start_id: int,
        message_end_id: int,
        message_count: int,
        version: int,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationSummaryRecord:
        now = iso_utc_now()
        cursor = self.db.execute(
            """
            INSERT INTO conversation_summaries (
                conversation_id, user_id, channel_id, guild_id, session_id, summary_kind, content,
                message_start_id, message_end_id, message_count, version, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'rolling', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope.conversation_id,
                scope.user_id,
                scope.channel_id,
                scope.guild_id,
                scope.session_id,
                content,
                message_start_id,
                message_end_id,
                message_count,
                version,
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        row = self.db.fetchone("SELECT * FROM conversation_summaries WHERE id = ?", (cursor.lastrowid,))
        return self._summary_from_row(row)

    def _message_from_row(self, row: Any) -> MessageRecord:
        return MessageRecord(
            id=int(row["id"]),
            platform=row["platform"],
            conversation_id=row["conversation_id"],
            session_id=row["session_id"],
            platform_message_id=row["platform_message_id"],
            sender_type=row["sender_type"],
            author_id=row["author_id"],
            user_id=row["user_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            reply_to_platform_message_id=row["reply_to_platform_message_id"],
            thread_id=row["thread_id"],
            content=row["content"],
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _session_memory_from_row(self, row: Any) -> SessionMemoryRecord:
        return SessionMemoryRecord(
            id=int(row["id"]),
            session_id=row["session_id"],
            conversation_id=row["conversation_id"],
            user_id=row["user_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            memory_type=row["memory_type"],
            content=row["content"],
            priority=float(row["priority"]),
            confidence=float(row["confidence"]),
            status=row["status"],
            source_message_ids=json_loads(row["source_message_ids_json"], []),
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_active_at=row["last_active_at"],
            expires_at=row["expires_at"],
        )

    def _long_term_memory_from_row(self, row: Any) -> LongTermMemoryRecord:
        return LongTermMemoryRecord(
            id=int(row["id"]),
            memory_uid=row["memory_uid"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            memory_type=row["memory_type"],
            category=row["category"],
            content=row["content"],
            tags=json_loads(row["tags_json"], []),
            source_message_ids=json_loads(row["source_message_ids_json"], []),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            status=row["status"],
            last_used_at=row["last_used_at"],
            supersedes_memory_uid=row["supersedes_memory_uid"],
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _structured_fact_from_row(self, row: Any) -> StructuredFactRecord:
        return StructuredFactRecord(
            id=int(row["id"]),
            user_id=row["user_id"],
            namespace=row["namespace"],
            key=row["key"],
            value=row["value"],
            confidence=float(row["confidence"]),
            source_message_ids=json_loads(row["source_message_ids_json"], []),
            status=row["status"],
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _relationship_state_from_row(self, row: Any) -> RelationshipStateRecord:
        return RelationshipStateRecord(
            id=int(row["id"]),
            user_id=row["user_id"],
            dimension=row["dimension"],
            value=row["value"],
            weight=float(row["weight"]),
            confidence=float(row["confidence"]),
            note=row["note"],
            source_message_ids=json_loads(row["source_message_ids_json"], []),
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _summary_from_row(self, row: Any) -> ConversationSummaryRecord:
        return ConversationSummaryRecord(
            id=int(row["id"]),
            conversation_id=row["conversation_id"],
            user_id=row["user_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            session_id=row["session_id"],
            summary_kind=row["summary_kind"],
            content=row["content"],
            message_start_id=int(row["message_start_id"]),
            message_end_id=int(row["message_end_id"]),
            message_count=int(row["message_count"]),
            version=int(row["version"]),
            metadata=json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
