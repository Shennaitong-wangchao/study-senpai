"""测试记忆导出和导入功能。

覆盖：
- export_memories / import_memories store 层方法
- GET /api/memories/export 端点（JSON 和 Markdown 格式）
- POST /api/memories/import 端点（成功、去重、无效数据）
"""
from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scripts.verify_product import FakeLLMClient, ensure_required_env, login_dashboard, seed_dashboard_data
from src.core.settings import Settings
from src.core.types import ConversationScope, MessageContext
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.store import MemoryStore
from src.product.store import ProductStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def product_store(tmp_path) -> Iterator[ProductStore]:
    """独立的 ProductStore，不带 Dashboard。"""
    database = Database(str(tmp_path / "store.sqlite3"))
    database.initialize()
    try:
        yield ProductStore(database)
    finally:
        database.close()


@pytest.fixture()
def dashboard_context() -> Iterator[dict[str, Any]]:
    """带登录认证的 Dashboard 测试上下文。"""
    with TemporaryDirectory(prefix="zhiwei-pytest-export-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ensure_required_env(temp_dir)
        settings = Settings.load()
        database = Database(settings.database_path)
        database.initialize()
        memory_store = MemoryStore(database)
        product_store = ProductStore(database)
        artifacts = seed_dashboard_data(settings, memory_store, product_store)

        app = build_dashboard_app(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=FakeLLMClient(),
        )
        client = TestClient(app)
        login_payload = login_dashboard(client, settings.dashboard_auth_username, settings.dashboard_auth_password)
        csrf_token = login_payload["csrf_token"]

        yield {
            "client": client,
            "product_store": product_store,
            "memory_store": memory_store,
            "artifacts": artifacts,
            "settings": settings,
            "csrf_token": csrf_token,
            "auth_headers": {"x-csrf-token": csrf_token, "origin": "http://testserver"},
        }

        database.close()


# ---------------------------------------------------------------------------
# ProductStore 层：export_memories
# ---------------------------------------------------------------------------


def test_export_memories_returns_correct_fields(product_store: ProductStore) -> None:
    """export_memories 应返回包含所有必要字段的列表。"""
    scope = ConversationScope(
        platform="discord",
        conversation_id="conv-export-test",
        user_id="user-export-1",
        channel_id="chan-1",
        guild_id=None,
        session_id="sess-1",
    )
    memory_store = MemoryStore(product_store.db)
    memory_store.insert_message(
        scope,
        sender_type="user",
        content="hello",
        context=MessageContext(platform_message_id="m-exp-1", author_id="user-export-1"),
    )
    memory_store.insert_or_merge_long_term_memory(
        scope,
        memory_type="personal_fact",
        category="hobby",
        content="用户喜欢下围棋",
        tags=["game", "strategy"],
        confidence=0.9,
        importance=0.7,
        source_message_ids=[1],
        metadata={"source": "test"},
    )
    memory_store.insert_or_merge_long_term_memory(
        scope,
        memory_type="preference",
        category="food",
        content="用户不喜欢吃香菜",
        tags=["food"],
        confidence=0.95,
        importance=0.6,
        source_message_ids=[1],
    )

    records = product_store.export_memories(user_id="user-export-1")
    assert len(records) == 2

    required_fields = {
        "memory_uid",
        "user_id",
        "memory_type",
        "category",
        "content",
        "tags",
        "confidence",
        "importance",
        "status",
        "created_at",
        "updated_at",
    }
    for rec in records:
        assert required_fields.issubset(rec.keys()), f"缺少字段：{required_fields - rec.keys()}"
        assert rec["status"] == "active"
        assert rec["user_id"] == "user-export-1"

    contents = {r["content"] for r in records}
    assert "用户喜欢下围棋" in contents
    assert "用户不喜欢吃香菜" in contents


def test_export_memories_filters_by_user_id(product_store: ProductStore) -> None:
    """export_memories 应只返回指定 user_id 的记忆。"""
    memory_store = MemoryStore(product_store.db)

    for user_suffix in ("a", "b"):
        scope = ConversationScope(
            platform="discord",
            conversation_id=f"conv-{user_suffix}",
            user_id=f"user-{user_suffix}",
            channel_id="chan",
            guild_id=None,
            session_id="sess",
        )
        memory_store.insert_or_merge_long_term_memory(
            scope,
            memory_type="fact",
            category="general",
            content=f"用户 {user_suffix} 的记忆",
            tags=[],
            confidence=0.8,
            importance=0.5,
            source_message_ids=[],
        )

    records_a = product_store.export_memories(user_id="user-a")
    records_all = product_store.export_memories()

    assert len(records_a) == 1
    assert records_a[0]["user_id"] == "user-a"
    assert len(records_all) == 2


# ---------------------------------------------------------------------------
# ProductStore 层：import_memories
# ---------------------------------------------------------------------------


def test_import_memories_success(product_store: ProductStore) -> None:
    """import_memories 应成功导入新记忆并返回正确计数。"""
    records = [
        {
            "memory_type": "personal_fact",
            "category": "sport",
            "content": "用户每周跑步两次",
            "tags": ["sport", "health"],
            "confidence": 0.88,
            "importance": 0.72,
        },
        {
            "memory_type": "preference",
            "category": "music",
            "content": "用户喜欢古典音乐",
            "tags": ["music"],
            "confidence": 0.75,
            "importance": 0.55,
        },
    ]

    result = product_store.import_memories(records, user_id="user-import-1")
    assert result["imported"] == 2
    assert result["skipped"] == 0
    assert result["errors"] == []

    exported = product_store.export_memories(user_id="user-import-1")
    assert len(exported) == 2
    contents = {r["content"] for r in exported}
    assert "用户每周跑步两次" in contents
    assert "用户喜欢古典音乐" in contents
    # 导入标记应被设置
    for r in exported:
        assert r["metadata"].get("imported") is True


def test_import_memories_skips_duplicates(product_store: ProductStore) -> None:
    """重复导入相同 content 的记忆应被跳过。"""
    records = [
        {
            "memory_type": "fact",
            "category": "general",
            "content": "用户住在上海",
            "tags": ["location"],
            "confidence": 0.9,
            "importance": 0.8,
        }
    ]

    first_result = product_store.import_memories(records, user_id="user-dedup-1")
    assert first_result["imported"] == 1
    assert first_result["skipped"] == 0

    second_result = product_store.import_memories(records, user_id="user-dedup-1")
    assert second_result["imported"] == 0
    assert second_result["skipped"] == 1
    assert second_result["errors"] == []

    exported = product_store.export_memories(user_id="user-dedup-1")
    assert len(exported) == 1, "重复导入不应增加记录数"


def test_import_memories_invalid_records_reported_as_errors(product_store: ProductStore) -> None:
    """content 为空的记录应被记录为错误，而不是崩溃。"""
    records = [
        {"memory_type": "fact", "category": "general", "content": ""},  # 空 content
        {"memory_type": "fact", "category": "general"},  # 缺少 content
        {"memory_type": "valid", "category": "test", "content": "这是有效记忆"},
    ]

    result = product_store.import_memories(records, user_id="user-err-1")
    assert result["imported"] == 1
    assert result["skipped"] == 0
    assert len(result["errors"]) == 2

    exported = product_store.export_memories(user_id="user-err-1")
    assert len(exported) == 1
    assert exported[0]["content"] == "这是有效记忆"


# ---------------------------------------------------------------------------
# Dashboard API：GET /api/memories/export
# ---------------------------------------------------------------------------


def test_export_api_returns_json_file(dashboard_context: dict[str, Any]) -> None:
    """GET /api/memories/export 应返回 JSON 文件下载响应。"""
    client: TestClient = dashboard_context["client"]

    response = client.get("/api/memories/export")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    assert "attachment" in response.headers.get("content-disposition", "")
    assert "memories_export.json" in response.headers.get("content-disposition", "")

    payload = response.json()
    assert "exported_at" in payload
    assert "memories" in payload
    assert "count" in payload
    assert isinstance(payload["memories"], list)
    # seed_dashboard_data 插入了多条记忆，数量应 > 0
    assert payload["count"] > 0
    assert payload["count"] == len(payload["memories"])


def test_export_api_returns_markdown_file(dashboard_context: dict[str, Any]) -> None:
    """GET /api/memories/export?format=markdown 应返回 Markdown 文件下载响应。"""
    client: TestClient = dashboard_context["client"]

    response = client.get("/api/memories/export", params={"format": "markdown"})
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "attachment" in response.headers.get("content-disposition", "")
    assert "memories_export.md" in response.headers.get("content-disposition", "")

    text = response.text
    assert "# 长期记忆导出" in text
    assert "导出时间" in text
    # Markdown 内容应包含记忆类别标题格式
    assert "##" in text


def test_export_api_json_fields_completeness(dashboard_context: dict[str, Any]) -> None:
    """导出的 JSON 记录应包含关键字段。"""
    client: TestClient = dashboard_context["client"]

    response = client.get("/api/memories/export")
    assert response.status_code == 200
    payload = response.json()

    required_fields = {"memory_uid", "user_id", "memory_type", "category", "content", "tags", "confidence", "importance"}
    for rec in payload["memories"]:
        assert required_fields.issubset(rec.keys()), f"记录缺少字段：{required_fields - rec.keys()}"


# ---------------------------------------------------------------------------
# Dashboard API：POST /api/memories/import
# ---------------------------------------------------------------------------


def test_import_api_imports_new_memories(dashboard_context: dict[str, Any]) -> None:
    """POST /api/memories/import 应成功导入新记忆并返回 imported/skipped/errors。"""
    client: TestClient = dashboard_context["client"]
    auth_headers = dashboard_context["auth_headers"]

    memories_data = {
        "memories": [
            {
                "memory_type": "personal_fact",
                "category": "hobby",
                "content": "用户喜欢收集邮票（导入测试唯一标识符 A1B2C3）",
                "tags": ["hobby"],
                "confidence": 0.85,
                "importance": 0.65,
            }
        ]
    }
    json_bytes = json.dumps(memories_data, ensure_ascii=False).encode("utf-8")
    file_obj = io.BytesIO(json_bytes)

    response = client.post(
        "/api/memories/import",
        files={"file": ("import_test.json", file_obj, "application/json")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["imported"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == []


def test_import_api_skips_duplicate_content(dashboard_context: dict[str, Any]) -> None:
    """重复导入相同 content 时应被跳过。"""
    client: TestClient = dashboard_context["client"]
    auth_headers = dashboard_context["auth_headers"]

    memories_data = {
        "memories": [
            {
                "memory_type": "fact",
                "category": "test",
                "content": "用户有一只猫（重复导入测试唯一标识符 X9Y8Z7）",
                "tags": [],
                "confidence": 0.8,
                "importance": 0.5,
            }
        ]
    }
    json_bytes = json.dumps(memories_data, ensure_ascii=False).encode("utf-8")

    # 第一次导入
    response1 = client.post(
        "/api/memories/import",
        files={"file": ("first.json", io.BytesIO(json_bytes), "application/json")},
        headers=auth_headers,
    )
    assert response1.status_code == 200
    assert response1.json()["imported"] == 1

    # 第二次导入相同内容
    response2 = client.post(
        "/api/memories/import",
        files={"file": ("second.json", io.BytesIO(json_bytes), "application/json")},
        headers=auth_headers,
    )
    assert response2.status_code == 200
    result2 = response2.json()
    assert result2["imported"] == 0
    assert result2["skipped"] == 1


def test_import_api_rejects_invalid_json(dashboard_context: dict[str, Any]) -> None:
    """上传非法 JSON 文件应返回 400。"""
    client: TestClient = dashboard_context["client"]
    auth_headers = dashboard_context["auth_headers"]

    bad_bytes = b"not a json file { invalid"
    response = client.post(
        "/api/memories/import",
        files={"file": ("bad.json", io.BytesIO(bad_bytes), "application/json")},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_import_api_accepts_flat_list_format(dashboard_context: dict[str, Any]) -> None:
    """导入 API 应同时接受列表格式（不含 memories 包装键）。"""
    client: TestClient = dashboard_context["client"]
    auth_headers = dashboard_context["auth_headers"]

    flat_list = [
        {
            "memory_type": "preference",
            "category": "color",
            "content": "用户最喜欢的颜色是深蓝色（列表格式导入测试 L1M2N3）",
            "tags": ["color"],
            "confidence": 0.9,
            "importance": 0.4,
        }
    ]
    json_bytes = json.dumps(flat_list, ensure_ascii=False).encode("utf-8")

    response = client.post(
        "/api/memories/import",
        files={"file": ("flat.json", io.BytesIO(json_bytes), "application/json")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["imported"] == 1
    assert result["errors"] == []


def test_import_api_reports_partial_errors(dashboard_context: dict[str, Any]) -> None:
    """导入含有部分空 content 记录时，应报告错误并导入有效记录。"""
    client: TestClient = dashboard_context["client"]
    auth_headers = dashboard_context["auth_headers"]

    mixed_data = {
        "memories": [
            {
                "memory_type": "fact",
                "category": "general",
                "content": "用户会弹吉他（混合错误测试 P4Q5R6）",
                "tags": [],
                "confidence": 0.8,
                "importance": 0.6,
            },
            {
                "memory_type": "fact",
                "category": "general",
                "content": "",  # 空 content，应报错
            },
        ]
    }
    json_bytes = json.dumps(mixed_data, ensure_ascii=False).encode("utf-8")

    response = client.post(
        "/api/memories/import",
        files={"file": ("mixed.json", io.BytesIO(json_bytes), "application/json")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["imported"] == 1
    assert len(result["errors"]) == 1
