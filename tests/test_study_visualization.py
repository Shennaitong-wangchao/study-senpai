"""学习统计可视化数据 API 测试。

覆盖：
- get_heatmap_data：热力图数据、空数据、自定义天数、日期填充
- get_subject_distribution：学科分布、空数据、已掌握计数
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from src.db.database import Database
from src.product.study import StudyService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "viz_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


def _iso_days_ago(days: int) -> str:
    """返回 N 天前的 ISO8601 字符串（UTC）。"""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 热力图数据测试
# ---------------------------------------------------------------------------

class TestGetHeatmapData:
    def test_empty_returns_correct_length(self, study: StudyService):
        """空数据时返回恰好 days 条记录，全部 count/minutes 为 0。"""
        data = study.get_heatmap_data("user-1", days=30)
        assert len(data) == 30
        for entry in data:
            assert entry["count"] == 0
            assert entry["minutes"] == 0

    def test_default_90_days(self, study: StudyService):
        """默认 days=90 时返回 90 条记录。"""
        data = study.get_heatmap_data("user-1")
        assert len(data) == 90

    def test_record_format(self, study: StudyService):
        """每条记录包含 date、count、minutes 三个字段。"""
        data = study.get_heatmap_data("user-1", days=7)
        for entry in data:
            assert "date" in entry
            assert "count" in entry
            assert "minutes" in entry
            # date 格式为 YYYY-MM-DD
            datetime.strptime(entry["date"], "%Y-%m-%d")

    def test_dates_are_ascending(self, study: StudyService):
        """日期序列严格递增。"""
        data = study.get_heatmap_data("user-1", days=14)
        dates = [entry["date"] for entry in data]
        assert dates == sorted(dates)
        assert len(set(dates)) == 14  # 无重复

    def test_today_session_counted(self, study: StudyService):
        """今天完成的学习会话出现在热力图今天的位置。"""
        session_uid = study.start_session("user-1")
        study.end_session(session_uid, focus_minutes=45, items_reviewed=10)

        data = study.get_heatmap_data("user-1", days=7)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_entry = next(e for e in data if e["date"] == today_str)

        assert today_entry["count"] == 1
        assert today_entry["minutes"] == 45

    def test_multiple_sessions_same_day(self, study: StudyService):
        """同一天多个会话的数据正确累加。"""
        for minutes in (20, 30, 50):
            uid = study.start_session("user-1")
            study.end_session(uid, focus_minutes=minutes, items_reviewed=5)

        data = study.get_heatmap_data("user-1", days=3)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_entry = next(e for e in data if e["date"] == today_str)

        assert today_entry["count"] == 3
        assert today_entry["minutes"] == 100  # 20+30+50

    def test_unfinished_session_excluded(self, study: StudyService):
        """未结束（ended_at IS NULL）的会话不计入热力图。"""
        # 未结束的会话
        study.start_session("user-1")
        # 已完成的会话
        uid = study.start_session("user-1")
        study.end_session(uid, focus_minutes=30, items_reviewed=5)

        data = study.get_heatmap_data("user-1", days=3)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_entry = next(e for e in data if e["date"] == today_str)

        assert today_entry["count"] == 1  # 只有 1 个已完成的

    def test_user_isolation(self, study: StudyService):
        """不同用户热力图互相隔离。"""
        uid = study.start_session("user-1")
        study.end_session(uid, focus_minutes=60, items_reviewed=10)

        data1 = study.get_heatmap_data("user-1", days=7)
        data2 = study.get_heatmap_data("user-2", days=7)

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_u1 = next(e for e in data1 if e["date"] == today_str)
        today_u2 = next(e for e in data2 if e["date"] == today_str)

        assert today_u1["count"] == 1
        assert today_u2["count"] == 0

    def test_custom_days_count(self, study: StudyService):
        """自定义 days=1 只返回 1 条记录（今天）。"""
        data = study.get_heatmap_data("user-1", days=1)
        assert len(data) == 1
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert data[0]["date"] == today_str

    def test_old_sessions_outside_window_excluded(self, study: StudyService):
        """超出时间窗口的历史会话不被计入。"""
        # 直接插入 200 天前的会话
        old_start = _iso_days_ago(200)
        study.db.execute(
            """
            INSERT INTO study_sessions (
                session_uid, user_id, goal_uid, started_at, ended_at,
                focus_minutes, items_reviewed, notes, metadata_json, created_at
            ) VALUES ('sess_old', 'user-1', NULL, ?, ?, 60, 10, NULL, '{}', ?)
            """,
            (old_start, old_start, old_start),
        )
        data = study.get_heatmap_data("user-1", days=90)
        # 所有记录 count 应为 0（该会话在 90 天窗口外）
        total_count = sum(e["count"] for e in data)
        assert total_count == 0


# ---------------------------------------------------------------------------
# 学科分布数据测试
# ---------------------------------------------------------------------------

class TestGetSubjectDistribution:
    def test_empty_distribution(self, study: StudyService):
        """没有卡片时返回空列表。"""
        result = study.get_subject_distribution("user-1")
        assert result == []

    def test_basic_distribution(self, study: StudyService):
        """正确统计不同学科的卡片数。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        study.add_review_item(user_id="user-1", front="Q2", back="A2", subject="数学")
        study.add_review_item(user_id="user-1", front="Q3", back="A3", subject="物理")

        result = study.get_subject_distribution("user-1")
        subjects = {item["subject"]: item for item in result}

        assert "数学" in subjects
        assert subjects["数学"]["count"] == 2
        assert "物理" in subjects
        assert subjects["物理"]["count"] == 1

    def test_mastered_count(self, study: StudyService):
        """repetitions >= 3 的卡片视为掌握，mastered 字段正确计算。"""
        item1 = study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        item2 = study.add_review_item(user_id="user-1", front="Q2", back="A2", subject="数学")
        item3 = study.add_review_item(user_id="user-1", front="Q3", back="A3", subject="数学")

        # 设置 item1 repetitions=3（已掌握）
        study.db.execute(
            "UPDATE review_items SET repetitions = 3 WHERE item_uid = ?",
            (item1["item_uid"],),
        )
        # 设置 item2 repetitions=5（已掌握）
        study.db.execute(
            "UPDATE review_items SET repetitions = 5 WHERE item_uid = ?",
            (item2["item_uid"],),
        )
        # item3 repetitions=0（未掌握）

        result = study.get_subject_distribution("user-1")
        math_entry = next(e for e in result if e["subject"] == "数学")

        assert math_entry["count"] == 3
        assert math_entry["mastered"] == 2  # item1 + item2

    def test_no_subject_grouped_as_unclassified(self, study: StudyService):
        """没有 subject 的卡片归入"未分类"。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject=None)
        study.add_review_item(user_id="user-1", front="Q2", back="A2", subject=None)

        result = study.get_subject_distribution("user-1")
        subjects = {item["subject"]: item for item in result}

        assert "未分类" in subjects
        assert subjects["未分类"]["count"] == 2

    def test_sorted_by_count_desc(self, study: StudyService):
        """结果按 count 降序排列（卡片最多的学科排在前面）。"""
        for i in range(5):
            study.add_review_item(user_id="user-1", front=f"Q{i}", back="A", subject="数学")
        for i in range(2):
            study.add_review_item(user_id="user-1", front=f"R{i}", back="B", subject="物理")
        study.add_review_item(user_id="user-1", front="S", back="C", subject="化学")

        result = study.get_subject_distribution("user-1")
        counts = [item["count"] for item in result]
        assert counts == sorted(counts, reverse=True)

    def test_user_isolation(self, study: StudyService):
        """不同用户的学科分布互相隔离。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1", subject="数学")
        study.add_review_item(user_id="user-2", front="Q2", back="A2", subject="英语")

        dist1 = {item["subject"]: item for item in study.get_subject_distribution("user-1")}
        dist2 = {item["subject"]: item for item in study.get_subject_distribution("user-2")}

        assert "数学" in dist1
        assert "英语" not in dist1
        assert "英语" in dist2
        assert "数学" not in dist2

    def test_distribution_result_format(self, study: StudyService):
        """每条记录包含 subject、count、mastered 三个字段，类型正确。"""
        study.add_review_item(user_id="user-1", front="Q", back="A", subject="测试")
        result = study.get_subject_distribution("user-1")
        assert len(result) == 1
        entry = result[0]
        assert "subject" in entry
        assert "count" in entry
        assert "mastered" in entry
        assert isinstance(entry["count"], int)
        assert isinstance(entry["mastered"], int)
        assert entry["mastered"] <= entry["count"]
