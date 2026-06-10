from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scripts.verify_product import FakeLLMClient, ensure_required_env, login_dashboard, seed_dashboard_data
from src.core.settings import Settings
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.store import MemoryStore
from src.product.store import ProductStore


@pytest.fixture()
def dashboard_context() -> Iterator[dict[str, Any]]:
    with TemporaryDirectory(prefix="zhiwei-pytest-dashboard-") as temp_dir_name:
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
        login_dashboard(client, settings.dashboard_auth_username, settings.dashboard_auth_password)

        yield {
            "client": client,
            "product_store": product_store,
            "artifacts": artifacts,
        }

        database.close()


def test_shared_diary_api_filters_and_mobile_bridge(dashboard_context: dict[str, Any]) -> None:
    client: TestClient = dashboard_context["client"]
    product_store: ProductStore = dashboard_context["product_store"]
    artifacts = dashboard_context["artifacts"]

    diary_uid = product_store.create_shared_diary_entry(
        user_id=artifacts["primary_user_id"],
        conversation_id=artifacts["primary_conversation_id"],
        local_date="2026-04-28",
        entry_type="voice_input",
        title="语音复盘",
        content="用户用语音补了一段今天的学习复盘。",
        role_scope="user",
        source="pytest",
        importance=0.84,
        tags=["voice", "review"],
        metadata={"test": True},
    )

    response = client.get(
        "/api/shared-diary",
        params={"q": "学习复盘", "entry_type": "voice_input", "role_scope": "user"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert payload["items"][0]["diary_uid"] == diary_uid
    assert payload["items"][0]["tags"] == ["voice", "review"]
    assert payload["summary"]["visible_type_counts"] == {"voice_input": 1}

    mobile_response = client.get("/mobile/dashboard/shared-diary", params={"q": "学习复盘"})
    assert mobile_response.status_code == 200
    mobile_payload = mobile_response.json()
    assert any(item["diary_uid"] == diary_uid for item in mobile_payload["items"])
