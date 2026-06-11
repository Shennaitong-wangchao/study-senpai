"""记忆复盘功能测试。

覆盖：
1. 空数据返回空列表
2. 近期使用的记忆不在队列中
3. 超过 30 天未使用的记忆出现在队列中
4. 按 importance 倒序排列
5. confirm 操作更新 last_used_at 并从队列中移除
6. archive 操作将记忆状态设为 archived
7. update 操作在 metadata 中标记 review_action
8. 非法 action 抛出 ValueError
9. 不存在的 memory_uid 返回 False
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from src.db.database import Database
from src.product.store import ProductStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "memory_review_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def store(database: Database) -> ProductStore:
    return ProductStore(database)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _iso_days_ago(days: int) -> str:
    """返回 N 天前的 UTC ISO8601 字符串。"""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat()


def _insert_memory(store: ProductStore, user_id: str, *,
                   importance: float = 0.5,
                   last_used_days_ago: int | None = None,
                   status: str = "active") -> str:
    """直接插入一条长期记忆，返回 memory_uid。"""
    memory_uid = f"mem_{uuid.uuid4().hex}"
    now = _iso_days_ago(0)
    last_used_at = _iso_days_ago(last_used_days_ago) if last_used_days_ago is not None else None
    store.db.execute(
        """
        INSERT INTO long_term_memories (
            memory_uid, user_id, conversation_id, channel_id, guild_id,
            memory_type, category, content, tags_json, source_message_ids_json,
            confidence, importance, status, last_used_at, supersedes_memory_uid,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, '', NULL, NULL, 'preference', 'general', ?, '[]', '[]',
                  0.8, ?, ?, ?, NULL, '{}', ?, ?)
        """,
        (memory_uid, user_id, f"记忆内容 {memory_uid[:8]}", importance,
         status, last_used_at, now, now),
    )
    return memory_uid


# ---------------------------------------------------------------------------
# 测试：空数据
# ---------------------------------------------------------------------------

class TestGetMemoriesForReviewEmpty:
    def test_empty_user_returns_empty_list(self, store: ProductStore) -> None:
        """不存在任何记忆时返回空列表。"""
        result = store.get_memories_for_review("user-empty")
        assert result == []

    def test_recently_used_not_in_queue(self, store: ProductStore) -> None:
        """5 天前使用过的记忆不应在待复盘队列中。"""
        _insert_memory(store, "user-recent", last_used_days_ago=5)
        result = store.get_memories_for_review("user-recent")
        assert result == []

    def test_archived_memory_not_in_queue(self, store: ProductStore) -> None:
        """已归档的记忆不应出现在待复盘队列中。"""
        _insert_memory(store, "user-archived", last_used_days_ago=60, status="archived")
        result = store.get_memories_for_review("user-archived")
        assert result == []


# ---------------------------------------------------------------------------
# 测试：基本列表
# ---------------------------------------------------------------------------

class TestGetMemoriesForReviewBasic:
    def test_stale_memory_in_queue(self, store: ProductStore) -> None:
        """超过 30 天未使用的记忆应出现在队列中。"""
        mem_uid = _insert_memory(store, "user-stale", last_used_days_ago=45)
        result = store.get_memories_for_review("user-stale")
        assert len(result) == 1
        assert result[0]["memory_uid"] == mem_uid

    def test_never_used_memory_in_queue(self, store: ProductStore) -> None:
        """从未使用过（last_used_at IS NULL）的记忆应出现在队列中。"""
        mem_uid = _insert_memory(store, "user-never-used", last_used_days_ago=None)
        result = store.get_memories_for_review("user-never-used")
        uids = [m["memory_uid"] for m in result]
        assert mem_uid in uids

    def test_sorted_by_importance_desc(self, store: ProductStore) -> None:
        """返回结果按 importance 倒序排列。"""
        low_uid = _insert_memory(store, "user-order", importance=0.2, last_used_days_ago=60)
        high_uid = _insert_memory(store, "user-order", importance=0.9, last_used_days_ago=60)
        mid_uid = _insert_memory(store, "user-order", importance=0.5, last_used_days_ago=60)
        result = store.get_memories_for_review("user-order", limit=3)
        importances = [m["importance"] for m in result]
        assert importances == sorted(importances, reverse=True)
        assert result[0]["memory_uid"] == high_uid

    def test_limit_respected(self, store: ProductStore) -> None:
        """limit 参数限制返回条数。"""
        for _ in range(5):
            _insert_memory(store, "user-limit", last_used_days_ago=60)
        result = store.get_memories_for_review("user-limit", limit=3)
        assert len(result) <= 3


# ---------------------------------------------------------------------------
# 测试：record_memory_review - confirm
# ---------------------------------------------------------------------------

class TestRecordMemoryReviewConfirm:
    def test_confirm_returns_true(self, store: ProductStore) -> None:
        mem_uid = _insert_memory(store, "user-confirm", last_used_days_ago=60)
        assert store.record_memory_review(mem_uid, "confirm") is True

    def test_confirm_updates_last_used_at(self, store: ProductStore) -> None:
        """confirm 后 last_used_at 被更新为当前时间，记忆不再在队列中。"""
        mem_uid = _insert_memory(store, "user-confirm2", last_used_days_ago=60)
        store.record_memory_review(mem_uid, "confirm")
        result = store.get_memories_for_review("user-confirm2")
        uids = [m["memory_uid"] for m in result]
        assert mem_uid not in uids


# ---------------------------------------------------------------------------
# 测试：record_memory_review - archive
# ---------------------------------------------------------------------------

class TestRecordMemoryReviewArchive:
    def test_archive_returns_true(self, store: ProductStore) -> None:
        mem_uid = _insert_memory(store, "user-arch", last_used_days_ago=60)
        assert store.record_memory_review(mem_uid, "archive") is True

    def test_archive_changes_status(self, store: ProductStore) -> None:
        mem_uid = _insert_memory(store, "user-arch2", last_used_days_ago=60)
        store.record_memory_review(mem_uid, "archive")
        mem = store.get_long_term_memory(mem_uid)
        assert mem is not None
        assert mem["status"] == "archived"

    def test_archive_removes_from_queue(self, store: ProductStore) -> None:
        mem_uid = _insert_memory(store, "user-arch3", last_used_days_ago=60)
        store.record_memory_review(mem_uid, "archive")
        result = store.get_memories_for_review("user-arch3")
        uids = [m["memory_uid"] for m in result]
        assert mem_uid not in uids


# ---------------------------------------------------------------------------
# 测试：record_memory_review - update
# ---------------------------------------------------------------------------

class TestRecordMemoryReviewUpdate:
    def test_update_returns_true(self, store: ProductStore) -> None:
        mem_uid = _insert_memory(store, "user-upd", last_used_days_ago=60)
        assert store.record_memory_review(mem_uid, "update") is True

    def test_update_sets_metadata_flag(self, store: ProductStore) -> None:
        """update 操作在 metadata 中标记 review_action = 'update'。"""
        from src.utils.json_utils import json_loads
        mem_uid = _insert_memory(store, "user-upd2", last_used_days_ago=60)
        store.record_memory_review(mem_uid, "update")
        row = store.db.fetchone(
            "SELECT metadata_json FROM long_term_memories WHERE memory_uid = ? LIMIT 1",
            (mem_uid,),
        )
        assert row is not None
        metadata = json_loads(row["metadata_json"], {})
        assert metadata.get("review_action") == "update"
        assert "review_flagged_at" in metadata


# ---------------------------------------------------------------------------
# 测试：错误处理
# ---------------------------------------------------------------------------

class TestRecordMemoryReviewErrors:
    def test_invalid_action_raises_value_error(self, store: ProductStore) -> None:
        """非法 action 应抛出 ValueError。"""
        mem_uid = _insert_memory(store, "user-err", last_used_days_ago=60)
        with pytest.raises(ValueError, match="不合法的 action"):
            store.record_memory_review(mem_uid, "delete")

    def test_nonexistent_memory_returns_false(self, store: ProductStore) -> None:
        """不存在的 memory_uid 返回 False。"""
        result = store.record_memory_review("mem_nonexistent", "confirm")
        assert result is False
