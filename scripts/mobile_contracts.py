from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verify_product import FakeLLMClient, build_test_client, ensure_required_env, seed_dashboard_data

from src.core.settings import Settings
from src.dashboard.schemas import ActionResponse, ModeStateResponse, PanelEnvelope
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.store import MemoryStore
from src.mobile.schemas import (
    MobileBootstrapResponse,
    MobileMessagesResponse,
    MobileProactiveResponse,
    MobileStatusResponse,
    MobileTimelineResponse,
)
from src.product.store import ProductStore


MOBILE_PANEL_ENDPOINTS = {
    "/mobile/dashboard/overview": None,
    "/mobile/dashboard/scopes": None,
    "/mobile/dashboard/search?q=测试": None,
    "/mobile/dashboard/memories": PanelEnvelope,
    "/mobile/dashboard/candidates": PanelEnvelope,
    "/mobile/dashboard/turns": PanelEnvelope,
    "/mobile/dashboard/attachments": PanelEnvelope,
    "/mobile/dashboard/proactive": PanelEnvelope,
    "/mobile/dashboard/presence": PanelEnvelope,
    "/mobile/dashboard/reality-context": PanelEnvelope,
    "/mobile/dashboard/facts": PanelEnvelope,
    "/mobile/dashboard/relationships": PanelEnvelope,
    "/mobile/dashboard/summaries": PanelEnvelope,
    "/mobile/dashboard/modes": ModeStateResponse,
}


def main() -> None:
    with TemporaryDirectory(prefix="zhiwei-mobile-contracts-") as temp_dir_name:
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
        remote_client = build_test_client(app, client_addr=("203.0.113.10", 49152))
        remote_without_token = remote_client.get("/mobile/bootstrap", headers={"host": "example.com"})
        if remote_without_token.status_code != 403:
            raise AssertionError(
                f"mobile no-token remote gate expected 403, got {remote_without_token.status_code}"
            )

        token_app = build_dashboard_app(
            settings=replace(settings, mobile_api_token="mobile-contract-token"),
            product_store=product_store,
            memory_store=memory_store,
            llm_client=FakeLLMClient(),
        )
        token_client = TestClient(token_app)
        unauthenticated = token_client.get("/mobile/bootstrap")
        if unauthenticated.status_code != 401:
            raise AssertionError(f"mobile token gate expected 401, got {unauthenticated.status_code}")
        authenticated = token_client.get(
            "/mobile/bootstrap",
            headers={"Authorization": "Bearer mobile-contract-token"},
        )
        if authenticated.status_code != 200:
            raise AssertionError(f"mobile token auth failed: {authenticated.status_code} {authenticated.text}")

        response = client.get("/mobile/bootstrap")
        if response.status_code != 200:
            raise AssertionError(f"mobile bootstrap failed: {response.status_code} {response.text}")
        MobileBootstrapResponse.model_validate(response.json())

        response = client.get("/mobile/messages")
        if response.status_code != 200:
            raise AssertionError(f"mobile messages failed: {response.status_code} {response.text}")
        messages = MobileMessagesResponse.model_validate(response.json())
        if len(messages.items) < 2:
            raise AssertionError("mobile messages did not return seeded chat history")

        response = client.get("/mobile/timeline")
        if response.status_code != 200:
            raise AssertionError(f"mobile timeline failed: {response.status_code} {response.text}")
        timeline = MobileTimelineResponse.model_validate(response.json())
        if len(timeline.items) < 2:
            raise AssertionError("mobile timeline did not return seeded items")

        response = client.get("/mobile/status")
        if response.status_code != 200:
            raise AssertionError(f"mobile status failed: {response.status_code} {response.text}")
        MobileStatusResponse.model_validate(response.json())

        response = client.get("/mobile/proactive")
        if response.status_code != 200:
            raise AssertionError(f"mobile proactive failed: {response.status_code} {response.text}")
        MobileProactiveResponse.model_validate(response.json())

        with client.stream(
            "POST",
            "/mobile/chat/stream",
            json={
                "content": "手机端契约测试",
                "client_message_id": "mobile-contract-user-1",
                "tool_overrides": {"search": False, "draw": False},
                "client_scene": "morning",
                "client_timezone": "Asia/Shanghai",
            },
        ) as response:
            if response.status_code != 200:
                raise AssertionError(f"mobile stream failed: {response.status_code} {response.text}")
            body = "".join(response.iter_text())
            if "event: final" not in body:
                raise AssertionError(f"mobile stream did not emit final event: {body}")

        mode_response = client.post("/mobile/mode", json={"mode": "fast", "learning_mode": True})
        if mode_response.status_code != 200:
            raise AssertionError(f"mobile mode update failed: {mode_response.status_code} {mode_response.text}")
        ModeStateResponse.model_validate(mode_response.json())

        location_response = client.post(
            "/mobile/device-context",
            json={
                "location": {"label": "iPhone 测试位置", "latitude": 39.9, "longitude": 116.4},
                "calendar_events": [
                    {
                        "title": "移动端契约测试日程",
                        "start_at": "2026-04-27T10:00:00+08:00",
                        "end_at": "2026-04-27T11:00:00+08:00",
                    }
                ],
            },
        )
        if location_response.status_code != 200:
            raise AssertionError(f"mobile device context failed: {location_response.status_code} {location_response.text}")
        if location_response.json().get("calendar_event_count") != 1:
            raise AssertionError(f"mobile device context did not record the calendar event: {location_response.json()}")

        for endpoint, model in MOBILE_PANEL_ENDPOINTS.items():
            response = client.get(endpoint)
            if response.status_code != 200:
                raise AssertionError(f"{endpoint}: expected 200, got {response.status_code}, body={response.text}")
            if model is not None:
                model.model_validate(response.json())

        archive_uid = artifacts["archive_memory_uid"]
        archive_response = client.post(f"/mobile/dashboard/memories/{archive_uid}/archive")
        if archive_response.status_code != 200:
            raise AssertionError(f"mobile memory archive failed: {archive_response.status_code} {archive_response.text}")
        ActionResponse.model_validate(archive_response.json())

        database.close()
    print("mobile_contracts.py: mobile API contracts passed.")


if __name__ == "__main__":
    main()
