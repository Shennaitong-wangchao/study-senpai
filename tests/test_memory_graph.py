"""测试 ProductStore.get_memory_graph — 节点生成、边的 category 匹配、tags 匹配"""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from src.db.database import Database
from src.product.store import ProductStore
from src.utils.json_utils import json_dumps
from src.utils.time_utils import iso_utc_now


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    database = Database(str(tmp_path / "graph_test.sqlite3"))
    database.initialize()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture()
def store(db) -> ProductStore:
    return ProductStore(db)


def _insert_memory(
    db: Database,
    *,
    user_id: str,
    memory_type: str = "preference",
    category: str = "general",
    content: str,
    tags: list[str] | None = None,
    importance: float = 0.5,
) -> str:
    """直接向 DB 插入一条活跃记忆，返回 memory_uid。"""
    memory_uid = f"mem_{uuid.uuid4().hex}"
    now = iso_utc_now()
    db.execute(
        """
        INSERT INTO long_term_memories (
            memory_uid, user_id, conversation_id, channel_id, guild_id,
            memory_type, category, content, tags_json, source_message_ids_json,
            confidence, importance, status, last_used_at, supersedes_memory_uid,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, '{}', ?, ?)
        """,
        (
            memory_uid,
            user_id,
            "conv-test",
            "ch-test",
            None,
            memory_type,
            category,
            content,
            json_dumps(tags or []),
            json_dumps([]),
            0.8,
            importance,
            now,
            now,
        ),
    )
    return memory_uid


# ──────────────────────────────────────────────────────────────────────────────
# 测试：基本结构
# ──────────────────────────────────────────────────────────────────────────────


def test_empty_graph_for_unknown_user(store: ProductStore) -> None:
    """没有记忆的用户应返回空节点和空边列表。"""
    result = store.get_memory_graph("nonexistent_user")
    assert result["nodes"] == []
    assert result["edges"] == []


def test_single_memory_produces_one_node_no_edges(store: ProductStore, db: Database) -> None:
    """单条记忆只生成一个节点，没有边。"""
    uid = _insert_memory(db, user_id="user-1", content="我喜欢咖啡")
    result = store.get_memory_graph("user-1")
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["id"] == uid
    assert result["edges"] == []


def test_node_fields_are_correct(store: ProductStore, db: Database) -> None:
    """节点字段（id, label, type, importance）应正确填充。"""
    long_content = "A" * 80
    uid = _insert_memory(
        db,
        user_id="user-2",
        content=long_content,
        memory_type="fact",
        importance=0.9,
    )
    result = store.get_memory_graph("user-2")
    node = result["nodes"][0]
    assert node["id"] == uid
    assert node["label"] == long_content[:40]  # label 截断到 40 字符
    assert node["type"] == "fact"
    assert node["importance"] == pytest.approx(0.9)


# ──────────────────────────────────────────────────────────────────────────────
# 测试：边 — category 匹配（weight 0.5）
# ──────────────────────────────────────────────────────────────────────────────


def test_same_category_creates_edge_with_weight_05(store: ProductStore, db: Database) -> None:
    """两条记忆 category 相同时应产生 weight=0.5 的边。"""
    uid_a = _insert_memory(db, user_id="user-3", category="food", content="我喜欢拉面")
    uid_b = _insert_memory(db, user_id="user-3", category="food", content="我喜欢寿司")
    result = store.get_memory_graph("user-3")
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    edge = result["edges"][0]
    assert {edge["source"], edge["target"]} == {uid_a, uid_b}
    assert edge["weight"] == pytest.approx(0.5)


def test_different_category_no_edge_without_other_signals(store: ProductStore, db: Database) -> None:
    """category 不同、tags/content 也无重叠时，不应产生边。"""
    _insert_memory(db, user_id="user-4", category="food", content="abc")
    _insert_memory(db, user_id="user-4", category="work", content="xyz")
    result = store.get_memory_graph("user-4")
    assert result["edges"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 测试：边 — tags 匹配（Jaccard × 0.6）
# ──────────────────────────────────────────────────────────────────────────────


def test_shared_tags_create_edge_with_jaccard_weight(store: ProductStore, db: Database) -> None:
    """tags 完全相同时 Jaccard=1.0，weight=0.6。"""
    uid_a = _insert_memory(db, user_id="user-5", tags=["python", "coding"], content="mem a")
    uid_b = _insert_memory(db, user_id="user-5", tags=["python", "coding"], content="mem b")
    result = store.get_memory_graph("user-5")
    edges_map = {frozenset([e["source"], e["target"]]): e for e in result["edges"]}
    key = frozenset([uid_a, uid_b])
    assert key in edges_map
    assert edges_map[key]["weight"] == pytest.approx(0.6, abs=1e-3)


def test_partial_tag_overlap_uses_jaccard(store: ProductStore, db: Database) -> None:
    """tags 部分重叠时，weight = 0.6 × (1/5)。"""
    # a: {python, coding, ml}  b: {python, data, viz}
    # 交集={python} → |I|=1, |U|=5 → jaccard=1/5=0.2 → weight≈0.12  (< 0.3 → 无边)
    # 注意：使用不同 category，避免 category 规则干扰
    _insert_memory(db, user_id="user-6", category="catA", tags=["python", "coding", "ml"], content="mem a")
    _insert_memory(db, user_id="user-6", category="catB", tags=["python", "data", "viz"], content="mem b")
    result = store.get_memory_graph("user-6")
    # jaccard=0.2 → weight=0.12 < 0.3，不应有边
    assert result["edges"] == []


def test_tags_two_thirds_overlap_creates_edge(store: ProductStore, db: Database) -> None:
    """tags 2/3 重叠时 weight = 0.6 × (2/3) ≈ 0.4 ≥ 0.3 → 应有边。"""
    # a: {x, y}  b: {x, y, z}  → |I|=2, |U|=3 → jaccard=2/3 → 0.6×(2/3)≈0.4
    # 使用不同 category，排除 category 规则干扰
    uid_a = _insert_memory(db, user_id="user-7", category="cat1", tags=["x", "y"], content="mem a")
    uid_b = _insert_memory(db, user_id="user-7", category="cat2", tags=["x", "y", "z"], content="mem b")
    result = store.get_memory_graph("user-7")
    edges_map = {frozenset([e["source"], e["target"]]): e for e in result["edges"]}
    key = frozenset([uid_a, uid_b])
    assert key in edges_map
    assert edges_map[key]["weight"] == pytest.approx(0.6 * 2 / 3, abs=1e-3)


# ──────────────────────────────────────────────────────────────────────────────
# 测试：边 — content 词汇重叠（>2 个词，weight 0.4）
# ──────────────────────────────────────────────────────────────────────────────


def test_content_word_overlap_more_than_two_creates_edge(store: ProductStore, db: Database) -> None:
    """content 有 3+ 个公共词时应产生 weight=0.4 的边。"""
    # 使用不同 category，排除 category 规则干扰
    uid_a = _insert_memory(
        db, user_id="user-8",
        category="cat_a",
        content="python machine learning deep neural network",
    )
    uid_b = _insert_memory(
        db, user_id="user-8",
        category="cat_b",
        content="python machine learning classification tree",
    )
    result = store.get_memory_graph("user-8")
    # 公共词: python, machine, learning（3 个 > 2）→ weight=0.4
    edges_map = {frozenset([e["source"], e["target"]]): e for e in result["edges"]}
    key = frozenset([uid_a, uid_b])
    assert key in edges_map
    assert edges_map[key]["weight"] == pytest.approx(0.4)


def test_content_word_overlap_two_or_less_no_edge(store: ProductStore, db: Database) -> None:
    """content 公共词 ≤ 2 时不应产生边（无其他信号）。"""
    # 使用不同 category，排除 category 规则干扰
    _insert_memory(db, user_id="user-9", category="cat_a", content="python flask web")
    _insert_memory(db, user_id="user-9", category="cat_b", content="python django rest")
    # 公共词: python（1 个，≤ 2）→ 无边
    result = store.get_memory_graph("user-9")
    assert result["edges"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 测试：多信号叠加时取最高权重
# ──────────────────────────────────────────────────────────────────────────────


def test_best_weight_wins_when_multiple_signals(store: ProductStore, db: Database) -> None:
    """category 匹配（0.5）+ tags 全匹配（0.6），应取 weight=0.6。"""
    uid_a = _insert_memory(
        db, user_id="user-10",
        category="tech",
        tags=["ai", "ml"],
        content="some tech mem",
    )
    uid_b = _insert_memory(
        db, user_id="user-10",
        category="tech",
        tags=["ai", "ml"],
        content="other tech mem",
    )
    result = store.get_memory_graph("user-10")
    edges_map = {frozenset([e["source"], e["target"]]): e for e in result["edges"]}
    key = frozenset([uid_a, uid_b])
    assert key in edges_map
    # tags 全匹配 → 0.6，category 匹配 → 0.5，取最大
    assert edges_map[key]["weight"] == pytest.approx(0.6, abs=1e-3)


# ──────────────────────────────────────────────────────────────────────────────
# 测试：limit 控制返回节点数
# ──────────────────────────────────────────────────────────────────────────────


def test_limit_controls_node_count(store: ProductStore, db: Database) -> None:
    """limit 参数应控制返回节点数量上限。"""
    for i in range(10):
        _insert_memory(db, user_id="user-11", content=f"memory number {i}", importance=float(i) / 10)
    result_5 = store.get_memory_graph("user-11", limit=5)
    result_all = store.get_memory_graph("user-11", limit=20)
    assert len(result_5["nodes"]) == 5
    assert len(result_all["nodes"]) == 10


# ──────────────────────────────────────────────────────────────────────────────
# 测试：用户隔离——不同用户的记忆互不影响
# ──────────────────────────────────────────────────────────────────────────────


def test_graph_is_isolated_per_user(store: ProductStore, db: Database) -> None:
    """不同用户的记忆应完全隔离，互不干扰。"""
    _insert_memory(db, user_id="alice", category="food", content="ramen noodles soup")
    _insert_memory(db, user_id="bob", category="food", content="ramen noodles soup")
    result_alice = store.get_memory_graph("alice")
    result_bob = store.get_memory_graph("bob")
    # 各自只有 1 条记忆，无边
    assert len(result_alice["nodes"]) == 1
    assert len(result_bob["nodes"]) == 1
    assert result_alice["edges"] == []
    assert result_bob["edges"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 测试：只返回 active 状态的记忆
# ──────────────────────────────────────────────────────────────────────────────


def test_graph_only_includes_active_memories(store: ProductStore, db: Database) -> None:
    """归档状态的记忆不应出现在图中。"""
    uid_active = _insert_memory(db, user_id="user-12", content="active memory here")
    # 插入一条 archived 记忆
    archived_uid = f"mem_{uuid.uuid4().hex}"
    now = iso_utc_now()
    db.execute(
        """
        INSERT INTO long_term_memories (
            memory_uid, user_id, conversation_id, channel_id, guild_id,
            memory_type, category, content, tags_json, source_message_ids_json,
            confidence, importance, status, last_used_at, supersedes_memory_uid,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'archived', NULL, NULL, '{}', ?, ?)
        """,
        (archived_uid, "user-12", "conv", "ch", None, "preference", "general",
         "archived memory", "[]", "[]", 0.8, 0.5, now, now),
    )
    result = store.get_memory_graph("user-12")
    node_ids = {n["id"] for n in result["nodes"]}
    assert uid_active in node_ids
    assert archived_uid not in node_ids
