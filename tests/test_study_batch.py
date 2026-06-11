"""闪卡批量管理功能测试。

覆盖：
- batch_add_review_items：批量添加成功、跳过空内容、跳过超长内容、混合场景
- archive_review_item：归档单张、不存在的卡片
- restore_review_item：恢复已归档的卡片、不存在的卡片
- batch_archive_by_subject：按学科批量归档
- list_review_items：按 goal_uid/subject/status 过滤
- 用户隔离
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.db.database import Database
from src.product.study import StudyService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "batch_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


# ---------------------------------------------------------------------------
# 批量添加测试
# ---------------------------------------------------------------------------

class TestBatchAddReviewItems:
    def test_batch_add_basic_success(self, study: StudyService):
        """批量添加正常卡片全部成功。"""
        items = [
            {"front": "光合作用", "back": "叶绿体"},
            {"front": "牛顿第一定律", "back": "惯性定律"},
            {"front": "二氧化碳", "back": "CO₂"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 3
        assert result["skipped"] == 0
        assert result["errors"] == []
        # 验证数据库中确实有 3 张卡片
        cards = study.list_review_items("user-1")
        assert len(cards) == 3

    def test_batch_add_empty_list(self, study: StudyService):
        """空列表返回 added=0, skipped=0, errors=[]。"""
        result = study.batch_add_review_items("user-1", [])
        assert result["added"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []

    def test_batch_add_skips_empty_front(self, study: StudyService):
        """front 为空字符串时跳过并记录错误。"""
        items = [
            {"front": "", "back": "答案"},
            {"front": "正常", "back": "答案"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 1
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1
        assert "front 或 back 为空" in result["errors"][0]

    def test_batch_add_skips_empty_back(self, study: StudyService):
        """back 为空字符串时跳过并记录错误。"""
        items = [
            {"front": "问题", "back": ""},
            {"front": "正常", "back": "答案"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 1
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1

    def test_batch_add_skips_none_fields(self, study: StudyService):
        """front 或 back 为 None 时也跳过。"""
        items = [
            {"front": None, "back": "答案"},
            {"front": "问题", "back": None},
            {"front": "正常", "back": "答案"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 1
        assert result["skipped"] == 2

    def test_batch_add_skips_front_too_long(self, study: StudyService):
        """front 超过 2000 字符时跳过并报错。"""
        long_front = "x" * 2001
        items = [
            {"front": long_front, "back": "答案"},
            {"front": "正常", "back": "答案"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 1
        assert result["skipped"] == 1
        assert any("front 超过" in e for e in result["errors"])

    def test_batch_add_skips_back_too_long(self, study: StudyService):
        """back 超过 2000 字符时跳过并报错。"""
        long_back = "y" * 2001
        items = [
            {"front": "问题", "back": long_back},
            {"front": "正常", "back": "答案"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 1
        assert result["skipped"] == 1
        assert any("back 超过" in e for e in result["errors"])

    def test_batch_add_with_goal_uid(self, study: StudyService):
        """批量添加可以关联 goal_uid。"""
        goal = study.create_goal("user-1", "conv-1", "生物")
        items = [
            {"front": "DNA", "back": "脱氧核糖核酸"},
            {"front": "RNA", "back": "核糖核酸"},
        ]
        result = study.batch_add_review_items("user-1", items, goal_uid=goal["goal_uid"])
        assert result["added"] == 2
        cards = study.list_review_items("user-1", goal_uid=goal["goal_uid"])
        assert len(cards) == 2
        assert all(c["goal_uid"] == goal["goal_uid"] for c in cards)

    def test_batch_add_with_subject_and_tags(self, study: StudyService):
        """批量添加时 subject 和 tags 被正确写入。"""
        items = [
            {"front": "π 的值", "back": "约 3.14159", "subject": "数学", "tags": ["数学", "常数"]},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 1
        cards = study.list_review_items("user-1")
        assert len(cards) == 1
        assert cards[0]["subject"] == "数学"
        assert "数学" in cards[0]["tags"]

    def test_batch_add_mixed_valid_and_invalid(self, study: StudyService):
        """混合有效和无效记录，只有效的被添加。"""
        items = [
            {"front": "有效1", "back": "答案1"},
            {"front": "", "back": "答案"},         # 空 front
            {"front": "有效2", "back": "答案2"},
            {"front": "问题", "back": "x" * 2001}, # back 超长
            {"front": "有效3", "back": "答案3"},
        ]
        result = study.batch_add_review_items("user-1", items)
        assert result["added"] == 3
        assert result["skipped"] == 2
        assert len(result["errors"]) == 2


# ---------------------------------------------------------------------------
# 归档/恢复单张卡片测试
# ---------------------------------------------------------------------------

class TestArchiveRestoreReviewItem:
    def test_archive_existing_item(self, study: StudyService):
        """归档存在的卡片返回 True，状态变为 archived。"""
        item = study.add_review_item(user_id="user-1", front="问题", back="答案")
        success = study.archive_review_item(item["item_uid"])
        assert success is True
        # active 列表中不再出现
        active = study.list_review_items("user-1", status="active")
        assert not any(c["item_uid"] == item["item_uid"] for c in active)
        # archived 列表中可以查到
        archived = study.list_review_items("user-1", status="archived")
        assert any(c["item_uid"] == item["item_uid"] for c in archived)

    def test_archive_nonexistent_item(self, study: StudyService):
        """归档不存在的 item_uid 返回 False。"""
        success = study.archive_review_item("item_nonexistent_uid_000")
        assert success is False

    def test_restore_archived_item(self, study: StudyService):
        """恢复已归档卡片：status 变回 active，next_review_at 是明天。"""
        item = study.add_review_item(user_id="user-1", front="问题", back="答案")
        study.archive_review_item(item["item_uid"])
        success = study.restore_review_item(item["item_uid"])
        assert success is True
        # 在 active 列表中重新出现
        active = study.list_review_items("user-1", status="active")
        assert any(c["item_uid"] == item["item_uid"] for c in active)
        # archived 列表中消失
        archived = study.list_review_items("user-1", status="archived")
        assert not any(c["item_uid"] == item["item_uid"] for c in archived)

    def test_restore_nonexistent_item(self, study: StudyService):
        """恢复不存在的 item_uid 返回 False。"""
        success = study.restore_review_item("item_nonexistent_uid_000")
        assert success is False

    def test_archive_then_restore_next_review_set(self, study: StudyService):
        """恢复后 next_review_at 应为明天（不是原来的值）。"""
        from datetime import datetime, timedelta, timezone
        item = study.add_review_item(user_id="user-1", front="问题", back="答案")
        study.archive_review_item(item["item_uid"])
        study.restore_review_item(item["item_uid"])
        active = study.list_review_items("user-1", status="active")
        restored = next(c for c in active if c["item_uid"] == item["item_uid"])
        next_review = datetime.fromisoformat(restored["next_review_at"])
        if next_review.tzinfo is None:
            next_review = next_review.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        # next_review_at 应该在现在之后（明天）
        assert next_review > now


# ---------------------------------------------------------------------------
# 按学科批量归档测试
# ---------------------------------------------------------------------------

class TestBatchArchiveBySubject:
    def test_archive_by_subject_success(self, study: StudyService):
        """按学科归档，正确数量的卡片被归档。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        study.add_review_item(user_id="user-1", front="Q2", back="A2", subject="数学")
        study.add_review_item(user_id="user-1", front="Q3", back="A3", subject="物理")
        count = study.batch_archive_by_subject("user-1", "数学")
        assert count == 2
        # 数学卡片已归档
        math_active = study.list_review_items("user-1", status="active", subject="数学")
        assert len(math_active) == 0
        # 物理卡片不受影响
        physics_active = study.list_review_items("user-1", status="active", subject="物理")
        assert len(physics_active) == 1

    def test_archive_by_subject_no_match(self, study: StudyService):
        """不存在对应学科时返回 0。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        count = study.batch_archive_by_subject("user-1", "不存在的学科")
        assert count == 0

    def test_archive_by_subject_skips_already_archived(self, study: StudyService):
        """已归档的卡片不被重复计数。"""
        item = study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        study.archive_review_item(item["item_uid"])
        study.add_review_item(user_id="user-1", front="Q2", back="A2", subject="数学")
        count = study.batch_archive_by_subject("user-1", "数学")
        assert count == 1  # 只有 1 张 active 被归档

    def test_archive_by_subject_user_isolation(self, study: StudyService):
        """只归档指定用户的卡片，不影响其他用户。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        study.add_review_item(user_id="user-2", front="Q2", back="A2", subject="数学")
        count = study.batch_archive_by_subject("user-1", "数学")
        assert count == 1
        # user-2 的数学卡片仍是 active
        user2_math = study.list_review_items("user-2", status="active", subject="数学")
        assert len(user2_math) == 1


# ---------------------------------------------------------------------------
# 卡片列表过滤测试
# ---------------------------------------------------------------------------

class TestListReviewItemsFilter:
    def test_filter_by_subject(self, study: StudyService):
        """按 subject 过滤返回正确结果。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        study.add_review_item(user_id="user-1", front="Q2", back="A2", subject="物理")
        math_items = study.list_review_items("user-1", subject="数学")
        assert len(math_items) == 1
        assert math_items[0]["subject"] == "数学"

    def test_filter_by_goal_uid(self, study: StudyService):
        """按 goal_uid 过滤只返回该目标的卡片。"""
        goal = study.create_goal("user-1", "conv-1", "生物")
        study.add_review_item(user_id="user-1", front="全局", back="答案")
        study.add_review_item(user_id="user-1", front="目标", back="答案", goal_uid=goal["goal_uid"])
        items = study.list_review_items("user-1", goal_uid=goal["goal_uid"])
        assert len(items) == 1
        assert items[0]["goal_uid"] == goal["goal_uid"]

    def test_filter_by_status_archived(self, study: StudyService):
        """status=archived 只返回已归档的卡片。"""
        item = study.add_review_item(user_id="user-1", front="问题", back="答案")
        study.archive_review_item(item["item_uid"])
        active = study.list_review_items("user-1", status="active")
        archived = study.list_review_items("user-1", status="archived")
        assert len(active) == 0
        assert len(archived) == 1

    def test_filter_default_returns_active(self, study: StudyService):
        """默认（不传 status）只返回 active 状态卡片。"""
        item = study.add_review_item(user_id="user-1", front="问题", back="答案")
        study.archive_review_item(item["item_uid"])
        study.add_review_item(user_id="user-1", front="问题2", back="答案2")
        items = study.list_review_items("user-1")  # 默认 status="active"
        assert len(items) == 1

    def test_filter_limit(self, study: StudyService):
        """limit 参数限制返回数量。"""
        for i in range(10):
            study.add_review_item(user_id="user-1", front=f"Q{i}", back=f"A{i}")
        items = study.list_review_items("user-1", limit=3)
        assert len(items) == 3
