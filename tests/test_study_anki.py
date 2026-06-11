"""Anki TSV 导入/导出功能测试。

覆盖：
- export_to_anki_tsv：正常导出、空数据、含 tags、过滤 goal_uid
- import_from_anki_tsv：正常导入、空文件、注释行、格式错误行
- 安全限制：内容超过 10MB、字段超长、超过 1000 条限制
- 往返一致性：导出后再导入
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
    db = Database(str(tmp_path / "anki_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


# ---------------------------------------------------------------------------
# 导出测试
# ---------------------------------------------------------------------------

class TestExportToAnkiTsv:
    def test_empty_export(self, study: StudyService):
        """没有卡片时导出应为空字符串。"""
        result = study.export_to_anki_tsv("user-1")
        assert result == ""

    def test_basic_export(self, study: StudyService):
        """单张无 tags 卡片正确导出为 TSV。"""
        study.add_review_item(user_id="user-1", front="光合作用", back="叶绿体")
        tsv = study.export_to_anki_tsv("user-1")
        lines = [l for l in tsv.splitlines() if l.strip()]
        assert len(lines) == 1
        parts = lines[0].split("\t")
        assert len(parts) == 3
        assert parts[0] == "光合作用"
        assert parts[1] == "叶绿体"

    def test_export_with_tags(self, study: StudyService):
        """带 tags 的卡片正确序列化到第三列。"""
        study.add_review_item(
            user_id="user-1",
            front="牛顿第一定律",
            back="惯性定律",
            tags=["物理", "高中"],
        )
        tsv = study.export_to_anki_tsv("user-1")
        parts = tsv.splitlines()[0].split("\t")
        assert "物理" in parts[2]
        assert "高中" in parts[2]

    def test_export_multiple_cards(self, study: StudyService):
        """多张卡片每张一行。"""
        for i in range(5):
            study.add_review_item(user_id="user-1", front=f"问题{i}", back=f"答案{i}")
        tsv = study.export_to_anki_tsv("user-1")
        lines = [l for l in tsv.splitlines() if l.strip()]
        assert len(lines) == 5

    def test_export_filters_by_goal_uid(self, study: StudyService):
        """goal_uid 过滤只导出指定目标的卡片。"""
        goal = study.create_goal("user-1", "conv-1", "数学")
        study.add_review_item(user_id="user-1", front="Q全局", back="A全局")
        study.add_review_item(
            user_id="user-1", front="Q目标", back="A目标", goal_uid=goal["goal_uid"]
        )
        tsv_all = study.export_to_anki_tsv("user-1")
        tsv_goal = study.export_to_anki_tsv("user-1", goal_uid=goal["goal_uid"])
        lines_all = [l for l in tsv_all.splitlines() if l.strip()]
        lines_goal = [l for l in tsv_goal.splitlines() if l.strip()]
        assert len(lines_all) == 2
        assert len(lines_goal) == 1
        assert "Q目标" in lines_goal[0]

    def test_export_strips_tabs_in_content(self, study: StudyService):
        """front/back 中的 Tab 字符被替换为空格，不破坏 TSV 结构。"""
        study.add_review_item(user_id="user-1", front="有\tTab", back="答案\tA")
        tsv = study.export_to_anki_tsv("user-1")
        line = tsv.splitlines()[0]
        # 每行恰好有 2 个 Tab 分隔符（3 列）
        assert line.count("\t") == 2

    def test_export_user_isolation(self, study: StudyService):
        """不同用户的卡片互相隔离。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1")
        study.add_review_item(user_id="user-2", front="Q2", back="A2")
        tsv1 = study.export_to_anki_tsv("user-1")
        tsv2 = study.export_to_anki_tsv("user-2")
        assert "Q1" in tsv1 and "Q2" not in tsv1
        assert "Q2" in tsv2 and "Q1" not in tsv2


# ---------------------------------------------------------------------------
# 导入测试
# ---------------------------------------------------------------------------

class TestImportFromAnkiTsv:
    def test_empty_content(self, study: StudyService):
        """空内容导入结果 imported=0, skipped=0, errors=[]。"""
        result = study.import_from_anki_tsv("user-1", "")
        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []

    def test_basic_import(self, study: StudyService):
        """正常两列 TSV 成功导入。"""
        tsv = "光合作用\t叶绿体\n牛顿第一定律\t惯性定律"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 2
        assert result["skipped"] == 0
        items = study.list_review_items("user-1")
        assert len(items) == 2

    def test_import_with_tags(self, study: StudyService):
        """三列 TSV（含 tags）正确写入 tags 字段。"""
        tsv = "光合作用\t叶绿体\t生物 初中"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1
        items = study.list_review_items("user-1")
        assert "生物" in items[0]["tags"] or "初中" in items[0]["tags"]

    def test_skip_comment_lines(self, study: StudyService):
        """# 开头的注释行被跳过。"""
        tsv = "# 这是注释\n光合作用\t叶绿体\n# 另一条注释"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1
        assert result["skipped"] == 2  # 2 条注释行

    def test_skip_empty_lines(self, study: StudyService):
        """空行被跳过。"""
        tsv = "\n光合作用\t叶绿体\n\n\n牛顿\t定律\n"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 2
        assert result["skipped"] >= 3  # 至少 3 个空行

    def test_skip_single_column_line(self, study: StudyService):
        """只有一列的行记录为错误并跳过。"""
        tsv = "光合作用\n牛顿第一定律\t惯性定律"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1

    def test_skip_empty_front_or_back(self, study: StudyService):
        """front 或 back 为空的行被跳过并报错。"""
        tsv = "\t叶绿体\n光合作用\t\n正常\t答案"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1
        assert result["skipped"] == 2
        assert len(result["errors"]) == 2

    def test_max_items_limit(self, study: StudyService):
        """超过 1000 条时，多余的行被跳过（不报错）。"""
        lines = [f"问题{i}\t答案{i}" for i in range(1100)]
        tsv = "\n".join(lines)
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1000
        assert result["skipped"] == 100

    def test_field_too_long(self, study: StudyService):
        """front/back 超过 2000 字符被跳过并报错。"""
        long_front = "x" * 2001
        tsv = f"{long_front}\t答案\n正常\t答案"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1
        assert result["skipped"] == 1
        assert any("front 超过" in e for e in result["errors"])

    def test_content_too_large(self, study: StudyService):
        """内容超过 10MB 直接返回错误，不导入任何数据。"""
        big_content = "x" * (10 * 1024 * 1024 + 1)
        result = study.import_from_anki_tsv("user-1", big_content)
        assert result["imported"] == 0
        assert len(result["errors"]) == 1
        assert "10MB" in result["errors"][0]

    def test_back_field_too_long(self, study: StudyService):
        """back 超过 2000 字符被跳过并报错。"""
        long_back = "y" * 2001
        tsv = f"正常问题\t{long_back}\n正常\t答案"
        result = study.import_from_anki_tsv("user-1", tsv)
        assert result["imported"] == 1
        assert result["skipped"] == 1
        assert any("back 超过" in e for e in result["errors"])

    def test_import_with_goal_uid(self, study: StudyService):
        """导入时可以关联 goal_uid。"""
        goal = study.create_goal("user-1", "conv-1", "生物")
        tsv = "光合作用\t叶绿体"
        result = study.import_from_anki_tsv("user-1", tsv, goal_uid=goal["goal_uid"])
        assert result["imported"] == 1
        items = study.list_review_items("user-1", goal_uid=goal["goal_uid"])
        assert len(items) == 1
        assert items[0]["goal_uid"] == goal["goal_uid"]

    def test_roundtrip_export_import(self, study: StudyService):
        """导出 → 导入后卡片数量一致。"""
        for i in range(5):
            study.add_review_item(
                user_id="user-1",
                front=f"问题{i}",
                back=f"答案{i}",
                tags=[f"tag{i}"],
            )
        tsv = study.export_to_anki_tsv("user-1")
        # 导入到另一个用户
        result = study.import_from_anki_tsv("user-2", tsv)
        assert result["imported"] == 5
        assert result["skipped"] == 0
        items2 = study.list_review_items("user-2")
        assert len(items2) == 5
