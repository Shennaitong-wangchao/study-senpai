"""测试 ProductStore.get_memory_health_score — 评分字段、边界情况、零记忆、单记忆"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

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
    database = Database(str(tmp_path / "health_test.sqlite3"))
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
    content: str = "test memory content",
    confidence: float = 0.8,
    updated_at: str | None = None,
    status: str = "active",
) -> str:
    """直接向 DB 插入一条记忆，返回 memory_uid。"""
    memory_uid = f"mem_{uuid.uuid4().hex}"
    now = iso_utc_now()
    ts = updated_at or now
    db.execute(
        """
        INSERT INTO long_term_memories (
            memory_uid, user_id, conversation_id, channel_id, guild_id,
            memory_type, category, content, tags_json, source_message_ids_json,
            confidence, importance, status, last_used_at, supersedes_memory_uid,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '{}', ?, ?)
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
            json_dumps([]),
            json_dumps([]),
            confidence,
            0.5,
            status,
            now,
            ts,
        ),
    )
    return memory_uid


def _old_timestamp(days: int) -> str:
    """返回 N 天前的 ISO8601 时间戳字符串。"""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# 边界测试：零记忆
# ──────────────────────────────────────────────────────────────────────────────


def test_zero_memories_returns_all_zeros(store: ProductStore) -> None:
    """无记忆用户应返回所有评分为 0，并包含建议。"""
    result = store.get_memory_health_score("nonexistent_user")
    assert result["overall"] == 0
    assert result["coverage"] == 0
    assert result["freshness"] == 0
    assert result["confidence"] == 0
    assert result["diversity"] == 0
    assert result["total_memories"] == 0
    assert result["active_memories"] == 0
    assert result["stale_memories"] == 0
    assert result["top_categories"] == []
    assert result["type_distribution"] == {}
    assert isinstance(result["recommendations"], list)
    assert len(result["recommendations"]) > 0


def test_zero_memories_recommendations_not_empty(store: ProductStore) -> None:
    """零记忆时，recommendations 应至少有一条建议内容。"""
    result = store.get_memory_health_score("empty_user")
    assert any(len(r) > 0 for r in result["recommendations"])


# ──────────────────────────────────────────────────────────────────────────────
# 边界测试：单记忆
# ──────────────────────────────────────────────────────────────────────────────


def test_single_memory_returns_valid_structure(store: ProductStore, db: Database) -> None:
    """单条记忆应返回完整的评分字段结构。"""
    _insert_memory(db, user_id="user-single", memory_type="preference", category="food")
    result = store.get_memory_health_score("user-single")

    # 所有字段必须存在
    required_fields = {
        "overall", "coverage", "freshness", "confidence", "diversity",
        "total_memories", "active_memories", "stale_memories",
        "top_categories", "type_distribution", "recommendations",
    }
    for field in required_fields:
        assert field in result, f"缺少字段：{field}"

    assert result["total_memories"] == 1
    assert result["active_memories"] == 1


def test_single_memory_coverage_is_10(store: ProductStore, db: Database) -> None:
    """单条记忆覆盖 1 种 type，coverage 应为 10（1 × 10 分）。"""
    _insert_memory(db, user_id="user-cov1", memory_type="preference")
    result = store.get_memory_health_score("user-cov1")
    assert result["coverage"] == 10


def test_single_memory_diversity_is_zero(store: ProductStore, db: Database) -> None:
    """单条记忆只有 1 个 category，Shannon entropy=0，diversity 应为 0。"""
    _insert_memory(db, user_id="user-div1", category="food")
    result = store.get_memory_health_score("user-div1")
    assert result["diversity"] == 0


def test_single_memory_confidence_reflects_value(store: ProductStore, db: Database) -> None:
    """confidence 评分应等于平均 confidence × 100（取整）。"""
    _insert_memory(db, user_id="user-conf1", confidence=0.75)
    result = store.get_memory_health_score("user-conf1")
    assert result["confidence"] == 75


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：freshness
# ──────────────────────────────────────────────────────────────────────────────


def test_freshness_100_when_all_memories_recent(store: ProductStore, db: Database) -> None:
    """全部记忆在近 30 天内更新，freshness 应为 100。"""
    now = iso_utc_now()
    for _ in range(5):
        _insert_memory(db, user_id="user-fresh1", updated_at=now)
    result = store.get_memory_health_score("user-fresh1")
    assert result["freshness"] == 100


def test_freshness_0_when_all_memories_old(store: ProductStore, db: Database) -> None:
    """全部记忆超过 30 天未更新，freshness 应为 0。"""
    old_ts = _old_timestamp(40)
    for _ in range(5):
        _insert_memory(db, user_id="user-fresh2", updated_at=old_ts)
    result = store.get_memory_health_score("user-fresh2")
    assert result["freshness"] == 0


def test_freshness_partial(store: ProductStore, db: Database) -> None:
    """2/4 的记忆在近 30 天内更新，freshness 应为 50。"""
    now = iso_utc_now()
    old_ts = _old_timestamp(40)
    for _ in range(2):
        _insert_memory(db, user_id="user-fresh3", updated_at=now)
    for _ in range(2):
        _insert_memory(db, user_id="user-fresh3", updated_at=old_ts)
    result = store.get_memory_health_score("user-fresh3")
    assert result["freshness"] == 50


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：stale_memories
# ──────────────────────────────────────────────────────────────────────────────


def test_stale_memories_counted_correctly(store: ProductStore, db: Database) -> None:
    """超过 90 天未更新的记忆应被计入 stale_memories。"""
    stale_ts = _old_timestamp(100)
    fresh_ts = iso_utc_now()
    for _ in range(3):
        _insert_memory(db, user_id="user-stale1", updated_at=stale_ts)
    for _ in range(2):
        _insert_memory(db, user_id="user-stale1", updated_at=fresh_ts)
    result = store.get_memory_health_score("user-stale1")
    assert result["stale_memories"] == 3
    assert result["total_memories"] == 5


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：coverage
# ──────────────────────────────────────────────────────────────────────────────


def test_coverage_increases_with_more_types(store: ProductStore, db: Database) -> None:
    """覆盖更多 type 时，coverage 应更高（每种 10 分）。"""
    types = ["preference", "personal_fact", "relationship", "experience", "goal"]
    for t in types:
        _insert_memory(db, user_id="user-cov2", memory_type=t)
    result = store.get_memory_health_score("user-cov2")
    assert result["coverage"] == 50  # 5 种 × 10 = 50


def test_coverage_caps_at_100(store: ProductStore, db: Database) -> None:
    """即使记忆类型超过 10 种，coverage 也不超过 100。"""
    # 插入包含 10 种已知类型 + 额外未知类型
    known_types = [
        "preference", "personal_fact", "relationship", "experience", "goal",
        "habit", "emotional", "knowledge", "schedule", "imported",
    ]
    for t in known_types:
        _insert_memory(db, user_id="user-cov3", memory_type=t)
    # 额外插入一个未知类型
    _insert_memory(db, user_id="user-cov3", memory_type="custom_type")
    result = store.get_memory_health_score("user-cov3")
    assert result["coverage"] == 100


def test_unknown_types_dont_count_toward_coverage(store: ProductStore, db: Database) -> None:
    """未知类型不计入 coverage。"""
    _insert_memory(db, user_id="user-cov4", memory_type="unknown_custom_type")
    result = store.get_memory_health_score("user-cov4")
    assert result["coverage"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：diversity（Shannon entropy）
# ──────────────────────────────────────────────────────────────────────────────


def test_diversity_100_when_perfectly_uniform(store: ProductStore, db: Database) -> None:
    """均匀分布在多个 category 时，diversity 应为 100。"""
    categories = ["cat_a", "cat_b", "cat_c", "cat_d"]
    for cat in categories:
        # 每个 category 各 2 条，总分布均匀
        for _ in range(2):
            _insert_memory(db, user_id="user-div2", category=cat)
    result = store.get_memory_health_score("user-div2")
    assert result["diversity"] == 100


def test_diversity_0_when_only_one_category(store: ProductStore, db: Database) -> None:
    """所有记忆在同一 category 时，diversity 应为 0。"""
    for _ in range(5):
        _insert_memory(db, user_id="user-div3", category="only_category")
    result = store.get_memory_health_score("user-div3")
    assert result["diversity"] == 0


def test_diversity_between_0_and_100(store: ProductStore, db: Database) -> None:
    """多 category 但分布不均时，diversity 在 0-100 之间。"""
    # 1 条在 cat_a，4 条在 cat_b（不均匀）
    _insert_memory(db, user_id="user-div4", category="cat_a")
    for _ in range(4):
        _insert_memory(db, user_id="user-div4", category="cat_b")
    result = store.get_memory_health_score("user-div4")
    assert 0 < result["diversity"] < 100


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：overall
# ──────────────────────────────────────────────────────────────────────────────


def test_overall_is_average_of_four_dimensions(store: ProductStore, db: Database) -> None:
    """overall 应为 4 个维度（coverage, freshness, confidence, diversity）的均值（取整）。"""
    # 插入均匀、新鲜、高置信度的记忆以使各维度较高
    categories = ["cat_a", "cat_b", "cat_c", "cat_d"]
    types = ["preference", "personal_fact", "relationship", "experience"]
    now = iso_utc_now()
    for cat, t in zip(categories, types):
        _insert_memory(
            db,
            user_id="user-overall1",
            category=cat,
            memory_type=t,
            confidence=1.0,
            updated_at=now,
        )
    result = store.get_memory_health_score("user-overall1")
    expected = round((result["coverage"] + result["freshness"] + result["confidence"] + result["diversity"]) / 4)
    assert result["overall"] == expected


def test_overall_in_valid_range(store: ProductStore, db: Database) -> None:
    """overall 始终在 0-100 范围内。"""
    _insert_memory(db, user_id="user-range1", confidence=0.5)
    result = store.get_memory_health_score("user-range1")
    assert 0 <= result["overall"] <= 100


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：top_categories 和 type_distribution
# ──────────────────────────────────────────────────────────────────────────────


def test_top_categories_returned_sorted_by_count(store: ProductStore, db: Database) -> None:
    """top_categories 应按 count 降序排列，最多返回 5 个。"""
    # 插入 3 个 cat_a，2 个 cat_b，1 个 cat_c
    for _ in range(3):
        _insert_memory(db, user_id="user-topcat1", category="cat_a")
    for _ in range(2):
        _insert_memory(db, user_id="user-topcat1", category="cat_b")
    _insert_memory(db, user_id="user-topcat1", category="cat_c")
    result = store.get_memory_health_score("user-topcat1")
    cats = result["top_categories"]
    assert cats[0]["category"] == "cat_a"
    assert cats[0]["count"] == 3
    assert cats[1]["category"] == "cat_b"
    assert cats[1]["count"] == 2


def test_top_categories_max_5(store: ProductStore, db: Database) -> None:
    """top_categories 最多返回 5 个 category。"""
    for i in range(8):
        _insert_memory(db, user_id="user-topcat2", category=f"cat_{i}")
    result = store.get_memory_health_score("user-topcat2")
    assert len(result["top_categories"]) <= 5


def test_type_distribution_includes_all_types(store: ProductStore, db: Database) -> None:
    """type_distribution 应包含所有出现过的 memory_type 及其数量。"""
    _insert_memory(db, user_id="user-typedist1", memory_type="preference")
    _insert_memory(db, user_id="user-typedist1", memory_type="preference")
    _insert_memory(db, user_id="user-typedist1", memory_type="goal")
    result = store.get_memory_health_score("user-typedist1")
    dist = result["type_distribution"]
    assert dist.get("preference") == 2
    assert dist.get("goal") == 1


# ──────────────────────────────────────────────────────────────────────────────
# 评分字段测试：recommendations 规则
# ──────────────────────────────────────────────────────────────────────────────


def test_recommendations_max_3(store: ProductStore, db: Database) -> None:
    """recommendations 最多返回 3 条。"""
    # 插入旧、低覆盖、低置信度的记忆，触发多条规则
    old_ts = _old_timestamp(60)
    _insert_memory(db, user_id="user-rec1", confidence=0.1, updated_at=old_ts, memory_type="preference")
    result = store.get_memory_health_score("user-rec1")
    assert len(result["recommendations"]) <= 3


def test_recommendations_for_stale_memories(store: ProductStore, db: Database) -> None:
    """当 freshness < 50 时，recommendations 应包含陈旧相关建议。"""
    old_ts = _old_timestamp(40)  # 超过 30 天
    for _ in range(5):
        _insert_memory(db, user_id="user-rec2", updated_at=old_ts)
    result = store.get_memory_health_score("user-rec2")
    assert result["freshness"] == 0
    assert any("陈旧" in r or "更新" in r or "刷新" in r for r in result["recommendations"])


def test_recommendations_for_low_coverage(store: ProductStore, db: Database) -> None:
    """当 coverage < 50 时，recommendations 应包含覆盖不足相关建议。"""
    # 只插入 1 种类型，coverage=10
    for _ in range(5):
        _insert_memory(db, user_id="user-rec3", memory_type="preference")
    result = store.get_memory_health_score("user-rec3")
    assert result["coverage"] == 10
    assert any("覆盖" in r or "类型" in r or "丰富" in r for r in result["recommendations"])


def test_recommendations_empty_when_health_is_perfect(store: ProductStore, db: Database) -> None:
    """当所有维度评分较高时，不应推送陈旧/覆盖/置信度相关警告（但可能有其他建议）。"""
    now = iso_utc_now()
    # 覆盖 10 种已知类型，高置信度，近期更新，均匀分布
    known_types = [
        "preference", "personal_fact", "relationship", "experience", "goal",
        "habit", "emotional", "knowledge", "schedule", "imported",
    ]
    categories = [f"cat_{i}" for i in range(10)]
    for t, cat in zip(known_types, categories):
        _insert_memory(
            db,
            user_id="user-rec4",
            memory_type=t,
            category=cat,
            confidence=1.0,
            updated_at=now,
        )
    result = store.get_memory_health_score("user-rec4")
    # 陈旧/覆盖/置信度建议不应出现
    combined = " ".join(result["recommendations"])
    assert "陈旧" not in combined
    assert "覆盖不足" not in combined
    assert "置信度较低" not in combined


# ──────────────────────────────────────────────────────────────────────────────
# 测试：用户隔离
# ──────────────────────────────────────────────────────────────────────────────


def test_health_is_isolated_per_user(store: ProductStore, db: Database) -> None:
    """不同用户的健康度评分应完全独立。"""
    # alice：有 5 条高质量记忆
    now = iso_utc_now()
    for i in range(5):
        _insert_memory(
            db,
            user_id="alice",
            memory_type="preference",
            category=f"cat_{i}",
            confidence=1.0,
            updated_at=now,
        )
    # bob：无记忆
    result_alice = store.get_memory_health_score("alice")
    result_bob = store.get_memory_health_score("bob")

    assert result_alice["total_memories"] == 5
    assert result_bob["total_memories"] == 0
    assert result_alice["overall"] > 0
    assert result_bob["overall"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 测试：只计算 active 状态记忆
# ──────────────────────────────────────────────────────────────────────────────


def test_health_only_counts_active_memories(store: ProductStore, db: Database) -> None:
    """archived 状态的记忆不应计入健康度统计。"""
    now = iso_utc_now()
    # 1 条 active
    _insert_memory(db, user_id="user-status1", status="active", updated_at=now)
    # 2 条 archived
    _insert_memory(db, user_id="user-status1", status="archived", updated_at=now)
    _insert_memory(db, user_id="user-status1", status="archived", updated_at=now)
    result = store.get_memory_health_score("user-status1")
    assert result["total_memories"] == 1
    assert result["active_memories"] == 1
