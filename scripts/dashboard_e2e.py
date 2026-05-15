from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

import uvicorn

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - optional dependency during local setup
    raise SystemExit(
        "Playwright is required for dashboard_e2e.py. Run `pip install -r requirements.txt` "
        "and `python3 -m playwright install chromium` first."
    ) from exc

from verify_product import FakeLLMClient, ensure_required_env, seed_dashboard_data

from src.core.settings import Settings
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.store import MemoryStore
from src.product.store import ProductStore


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _wait_for_dashboard(base_url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(f"{base_url}/login", timeout=1.0) as response:  # noqa: S310
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise RuntimeError(f"dashboard did not become ready within {timeout_seconds} seconds")


class DashboardServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="error")
        )

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


def main() -> None:
    with TemporaryDirectory(prefix="zhiwei-e2e-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ensure_required_env(temp_dir)
        port = _find_free_port()
        os.environ["DASHBOARD_PORT"] = str(port)

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
        server = DashboardServerThread(app, settings.dashboard_host, settings.dashboard_port)
        base_url = f"http://{settings.dashboard_host}:{settings.dashboard_port}"
        server.start()

        try:
            _wait_for_dashboard(base_url)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f"{base_url}/login", wait_until="networkidle")
                page.get_by_label("用户名").fill(settings.dashboard_auth_username)
                page.get_by_label("密码").fill(settings.dashboard_auth_password)
                page.get_by_role("button", name="进入 Dashboard").click()
                page.wait_for_url(f"{base_url}/", timeout=10000)
                page.get_by_text("沈知微长期陪伴系统").wait_for(timeout=10000)
                page.wait_for_function(
                    "() => document.getElementById('scope-select') && document.getElementById('scope-select').options.length >= 2",
                    timeout=10000,
                )

                tab_nav = page.locator(".tab-nav")
                tab_nav.get_by_role("button", name="候选记忆").click()
                page.locator('[data-action="reject-candidate"]').first.wait_for(timeout=10000)
                page.locator('[data-action="reject-candidate"]').first.click()
                page.wait_for_timeout(1200)
                tab_nav.get_by_role("button", name="审计日志").click()
                page.get_by_role("heading", name="审计日志").wait_for(timeout=10000)

                target_scope_value = f"{artifacts['secondary_user_id']}::{artifacts['secondary_conversation_id']}"
                page.evaluate(
                    """
                    (scopeValue) => {
                      const select = document.getElementById('scope-select');
                      select.value = scopeValue;
                    }
                    """,
                    target_scope_value,
                )
                page.evaluate("() => setActiveScope()")
                page.wait_for_timeout(800)
                scope_summary = page.locator("#scope-summary").text_content() or ""
                if artifacts["secondary_conversation_id"] not in scope_summary:
                    page.get_by_role("button", name="立即刷新").click()
                    page.wait_for_timeout(800)
                    scope_summary = page.locator("#scope-summary").text_content() or ""
                if artifacts["secondary_conversation_id"] not in scope_summary:
                    error_text = page.locator("#error-banner").text_content() or ""
                    raise AssertionError(
                        f"scope switch did not update summary: summary={scope_summary!r} error={error_text!r}"
                    )
                tab_nav.get_by_role("button", name="长期记忆").click()
                page.get_by_text("雅思口语").first.wait_for(timeout=10000)

                primary_scope_value = f"{artifacts['primary_user_id']}::{artifacts['primary_conversation_id']}"
                page.evaluate(
                    """
                    (scopeValue) => {
                      const select = document.getElementById('scope-select');
                      select.value = scopeValue;
                    }
                    """,
                    primary_scope_value,
                )
                page.evaluate("() => setActiveScope()")
                page.wait_for_timeout(800)

                tab_nav.get_by_role("button", name="现实锚点").click()
                page.get_by_role("heading", name="现实锚点", exact=True).wait_for(timeout=10000)

                tab_nav.get_by_role("button", name="后台任务").click()
                page.get_by_role("button", name="重试").first.wait_for(timeout=10000)
                page.get_by_role("button", name="重试").first.click()
                page.get_by_role("button", name="提权").first.click()
                page.get_by_role("button", name="取消").first.click()

                page.get_by_role("button", name="退出登录").click()
                page.wait_for_url(f"{base_url}/login", timeout=10000)
                browser.close()
        finally:
            server.stop()
            server.join(timeout=5)
            database.close()

    print("dashboard_e2e.py: browser login/navigation/button flow passed.")


if __name__ == "__main__":
    main()
