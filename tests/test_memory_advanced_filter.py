"""测试长期记忆高级过滤功能。

覆盖：
- MemoryStore.list_long_term_memories 的 min_importance 过滤
- MemoryStore.list_long_term_memories 的 tags 过滤（OR 语义）
- MemoryStore.list_long_term_memories 的 min_confidence 过滤
- MemoryStore.list_long_term_memories 的 memory_type 精确过滤
- MemoryStore.list_long_term_memories 的 created_after/created_before 时间范围过滤
- 组合过滤（多个条件同时生效）
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.core.types import ConversationScope, MessageContext
from src.db.database import Database
from src.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    database = Database(str(tmp_path / "test.sqlite3"))
    database.initialize()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture()
def store(db: Database) -> MemoryStore:
    return MemoryStore(db)


@pytest.fixture()
def scope() -> ConversationScope:
    return ConversationScope(
        platform="discord",
        conversation_id="conv-filter-test",
        user_id="user-filter-1",
        channel_id="chan-1",
        guild_id=None,
        session_id="sess-1",
    )


def _insert(store: MemoryStore, scope: ConversationScope, **kwargs) -> str:
    """辅助函数：插入一条长期记忆，返回 memory_uid。"""
    defaults = dict(
        memory_type="personal_fact",
        category="test",
        content="默认内容",
        tags=[],
        confidence=0.8,
        importance=0.5,
        source_message_ids=[],
    )
    defaults.update(kwargs)
    return store.insert_or_merge_long_term_memory(scope, **defaults)


# ---------------------------------------------------------------------------
# min_importance 过滤测试
# ---------------------------------------------------------------------------

def test_min_importance_filters_correctly(store: MemoryStore, scope: ConversationScope) -> None:
    """min_importance 应只返回 importance >= 阈值的记忆。"""
    _insert(store, scope, content="低重要性记忆", importance=0.2, tags=["low"])
    _insert(store, scope, content="中等重要性记忆", importance=0.5, tags=["mid"])
    _insert(store, scope, content="高重要性记忆", importance=0.9, tags=["high"])

    # 过滤 importance >= 0.5
    results = store.list_long_term_memories(scope.user_id, min_importance=0.5)
    contents = {r.content for r in results}
    assert "高重要性记忆" in contents
    assert "中等重要性记忆" in contents
    assert "低重要性记忆" not in contents

    # 过滤 importance >= 0.8
    results_high = store.list_long_term_memories(scope.user_id, min_importance=0.8)
    contents_high = {r.content for r in results_high}
    assert "高重要性记忆" in contents_high
    assert "中等重要性记忆" not in contents_high
    assert "低重要性记忆" not in contents_high


def test_min_importance_zero_returns_all(store: MemoryStore, scope: ConversationScope) -> None:
    """min_importance=0.0 应返回所有活跃记忆。"""
    _insert(store, scope, content="记忆A", importance=0.0)
    _insert(store, scope, content="记忆B", importance=1.0)
    results = store.list_long_term_memories(scope.user_id, min_importance=0.0)
    assert len(results) == 2


def test_min_importance_none_returns_all(store: MemoryStore, scope: ConversationScope) -> None:
    """不传 min_importance 时应返回所有活跃记忆（向后兼容）。"""
    _insert(store, scope, content="记忆X", importance=0.1)
    _insert(store, scope, content="记忆Y", importance=0.9)
    results = store.list_long_term_memories(scope.user_id)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# tags 过滤测试（OR 语义）
# ---------------------------------------------------------------------------

def test_tags_filter_or_semantics(store: MemoryStore, scope: ConversationScope) -> None:
    """tags 过滤应使用 OR 语义：任意一个标签匹配即返回。"""
    _insert(store, scope, content="数学记忆", tags=["math", "exam"])
    _insert(store, scope, content="英语记忆", tags=["english", "exam"])
    _insert(store, scope, content="体育记忆", tags=["sports"])
    _insert(store, scope, content="无标签记忆", tags=[])

    # 搜索 math → 只匹配"数学记忆"
    results = store.list_long_term_memories(scope.user_id, tags=["math"])
    contents = {r.content for r in results}
    assert "数学记忆" in contents
    assert "英语记忆" not in contents
    assert "体育记忆" not in contents

    # 搜索 exam → 匹配"数学记忆"和"英语记忆"
    results_exam = store.list_long_term_memories(scope.user_id, tags=["exam"])
    contents_exam = {r.content for r in results_exam}
    assert "数学记忆" in contents_exam
    assert "英语记忆" in contents_exam
    assert "体育记忆" not in contents_exam

    # 搜索 math OR sports → 匹配"数学记忆"和"体育记忆"
    results_multi = store.list_long_term_memories(scope.user_id, tags=["math", "sports"])
    contents_multi = {r.content for r in results_multi}
    assert "数学记忆" in contents_multi
    assert "体育记忆" in contents_multi
    assert "英语记忆" not in contents_multi


def test_tags_filter_no_match_returns_empty(store: MemoryStore, scope: ConversationScope) -> None:
    """tags 过滤无匹配时应返回空列表。"""
    _insert(store, scope, content="测试记忆", tags=["abc"])
    results = store.list_long_term_memories(scope.user_id, tags=["xyz"])
    assert results == []


def test_tags_filter_none_returns_all(store: MemoryStore, scope: ConversationScope) -> None:
    """tags=None 时应返回所有活跃记忆（向后兼容）。"""
    _insert(store, scope, content="有标签", tags=["a"])
    _insert(store, scope, content="无标签", tags=[])
    results = store.list_long_term_memories(scope.user_id, tags=None)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# min_confidence 过滤测试
# ---------------------------------------------------------------------------

def test_min_confidence_filters_correctly(store: MemoryStore, scope: ConversationScope) -> None:
    """min_confidence 应只返回 confidence >= 阈值的记忆。"""
    _insert(store, scope, content="低置信度", confidence=0.3)
    _insert(store, scope, content="高置信度", confidence=0.9)

    results = store.list_long_term_memories(scope.user_id, min_confidence=0.7)
    contents = {r.content for r in results}
    assert "高置信度" in contents
    assert "低置信度" not in contents


# ---------------------------------------------------------------------------
# memory_type 精确过滤测试
# ---------------------------------------------------------------------------

def test_memory_type_exact_match(store: MemoryStore, scope: ConversationScope) -> None:
    """memory_type 应精确匹配，不返回其他类型。"""
    _insert(store, scope, content="个人事实", memory_type="personal_fact")
    _insert(store, scope, content="偏好记忆", memory_type="preference")

    results = store.list_long_term_memories(scope.user_id, memory_type="personal_fact")
    contents = {r.content for r in results}
    assert "个人事实" in contents
    assert "偏好记忆" not in contents


# ---------------------------------------------------------------------------
# created_after / created_before 时间范围过滤测试
# ---------------------------------------------------------------------------

def test_created_after_filters_correctly(store: MemoryStore, scope: ConversationScope) -> None:
    """created_after 应只返回指定时间之后创建的记忆。"""
    uid1 = _insert(store, scope, content="旧记忆")
    # 直接修改 created_at 为较早时间来模拟旧记忆
    store.db.execute(
        "UPDATE long_term_memories SET created_at = ? WHERE memory_uid = ?",
        ("2020-01-01T00:00:00Z", uid1),
    )
    _insert(store, scope, content="新记忆")

    results = store.list_long_term_memories(scope.user_id, created_after="2023-01-01T00:00:00Z")
    contents = {r.content for r in results}
    assert "新记忆" in contents
    assert "旧记忆" not in contents


def test_created_before_filters_correctly(store: MemoryStore, scope: ConversationScope) -> None:
    """created_before 应只返回指定时间之前创建的记忆。"""
    uid1 = _insert(store, scope, content="很旧的记忆")
    store.db.execute(
        "UPDATE long_term_memories SET created_at = ? WHERE memory_uid = ?",
        ("2020-01-01T00:00:00Z", uid1),
    )
    _insert(store, scope, content="最新记忆")

    results = store.list_long_term_memories(scope.user_id, created_before="2021-01-01T00:00:00Z")
    contents = {r.content for r in results}
    assert "很旧的记忆" in contents
    assert "最新记忆" not in contents


# ---------------------------------------------------------------------------
# 组合过滤测试
# ---------------------------------------------------------------------------

def test_combined_filters(store: MemoryStore, scope: ConversationScope) -> None:
    """多个过滤条件应同时生效（AND 语义）。"""
    _insert(store, scope, content="高重要+数学标签", importance=0.9, tags=["math"], memory_type="personal_fact")
    _insert(store, scope, content="低重要+数学标签", importance=0.2, tags=["math"], memory_type="personal_fact")
    _insert(store, scope, content="高重要+英语标签", importance=0.9, tags=["english"], memory_type="personal_fact")
    _insert(store, scope, content="高重要+偏好类型", importance=0.9, tags=["math"], memory_type="preference")

    results = store.list_long_term_memories(
        scope.user_id,
        min_importance=0.8,
        tags=["math"],
        memory_type="personal_fact",
    )
    contents = {r.content for r in results}
    assert "高重要+数学标签" in contents
    assert "低重要+数学标签" not in contents
    assert "高重要+英语标签" not in contents
    assert "高重要+偏好类型" not in contents


def test_user_isolation(store: MemoryStore, scope: ConversationScope) -> None:
    """list_long_term_memories 应只返回指定 user_id 的记忆。"""
    _insert(store, scope, content="用户1的记忆")
    other_scope = ConversationScope(
        platform="discord",
        conversation_id="conv-other",
        user_id="user-other-999",
        channel_id="chan-1",
        guild_id=None,
        session_id="sess-2",
    )
    _insert(store, other_scope, content="用户2的记忆")

    results = store.list_long_term_memories(scope.user_id)
    contents = {r.content for r in results}
    assert "用户1的记忆" in contents
    assert "用户2的记忆" not in contents
