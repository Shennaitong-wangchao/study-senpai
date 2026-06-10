from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verify_product import FakeLLMClient, ensure_required_env, login_dashboard, seed_dashboard_data

from src.core.settings import Settings
from src.dashboard.schemas import (
    GlobalSearchResponse,
    HealthResponse,
    OverviewResponse,
    PanelEnvelope,
    PerformanceResponse,
    ScopesResponse,
    SecurityResponse,
)
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.store import MemoryStore
from src.product.store import ProductStore


ENDPOINT_TO_MODEL = {
    "/api/overview": OverviewResponse,
    "/api/scopes": ScopesResponse,
    "/api/security": SecurityResponse,
    "/api/attachments": PanelEnvelope,
    "/api/audits": PanelEnvelope,
    "/api/candidates": PanelEnvelope,
    "/api/companion-day": PanelEnvelope,
    "/api/errors": PanelEnvelope,
    "/api/facts": PanelEnvelope,
    "/api/logs": PanelEnvelope,
    "/api/memories": PanelEnvelope,
    "/api/presence": PanelEnvelope,
    "/api/proactive": PanelEnvelope,
    "/api/reality-context": PanelEnvelope,
    "/api/shared-diary": PanelEnvelope,
    "/api/relationships": PanelEnvelope,
    "/api/snapshots": PanelEnvelope,
    "/api/summaries": PanelEnvelope,
    "/api/tasks": PanelEnvelope,
    "/api/turns": PanelEnvelope,
    "/api/health": HealthResponse,
    "/api/performance": PerformanceResponse,
    "/api/search?q=跑步": GlobalSearchResponse,
}


def main() -> None:
    with TemporaryDirectory(prefix="zhiwei-contracts-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ensure_required_env(temp_dir)
        settings = Settings.load()
        database = Database(settings.database_path)
        database.initialize()
        memory_store = MemoryStore(database)
        product_store = ProductStore(database)
        seed_dashboard_data(settings, memory_store, product_store)

        app = build_dashboard_app(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=FakeLLMClient(),
        )
        client = TestClient(app)
        login_payload = login_dashboard(client, settings.dashboard_auth_username, settings.dashboard_auth_password)
        if not login_payload["csrf_token"]:
            raise AssertionError("dashboard login did not return csrf token")

        for endpoint, model in ENDPOINT_TO_MODEL.items():
            response = client.get(endpoint)
            if response.status_code != 200:
                raise AssertionError(f"{endpoint}: expected 200, got {response.status_code}, body={response.text}")
            payload = response.json()
            try:
                model.model_validate(payload)
            except Exception as exc:  # noqa: BLE001
                raise AssertionError(f"{endpoint}: contract validation failed: {exc}\npayload={payload}") from exc

        database.close()
    print("dashboard_contracts.py: dashboard response-model contracts passed.")


if __name__ == "__main__":
    main()
