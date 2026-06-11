from __future__ import annotations

import hashlib
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
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Playwright is required for dashboard_visual_regression.py. "
        "Run `pip install -r requirements.txt` and `python3 -m playwright install chromium` first."
    ) from exc

from verify_product import FakeLLMClient, ensure_required_env, seed_dashboard_data

from src.core.settings import Settings
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.store import MemoryStore
from src.product.store import ProductStore


def _join_hash(*parts: str) -> str:
    return "".join(parts)


EXPECTED_HASHES = {
    "login": "83ddd4d79cbaa71cfb0ff64d48513705d0c569f0ae8de6788afe497e3e2121a6",
    "overview": "141e9c2b658a65bee638809c3f268d5c29bea737a24578f6e3b1a85d7bd1f5ea",
    "candidates": _join_hash(
        "6dac",
        "cbf672533b131d3e8ce16bc053500571b924710bf7443e41aeabf1af5b3e",
    ),
}


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
        self.server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="error"))

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


def screenshot_hash(target, *, full_page: bool = True) -> str:
    if full_page:
        image = target.screenshot(full_page=True, animations="disabled")
    else:
        image = target.screenshot(animations="disabled")
    return hashlib.sha256(image).hexdigest()


def normalize_dashboard_for_snapshot(page) -> None:
    page.evaluate(
        """
        () => {
          const refresh = document.getElementById('last-refresh-info');
          const panel = document.getElementById('panel-refresh-info');
          if (refresh) refresh.textContent = '上次刷新：固定';
          if (panel) panel.textContent = '当前面板：固定';
        }
        """
    )


def main() -> None:
    with TemporaryDirectory(prefix="zhiwei-visual-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ensure_required_env(temp_dir)
        port = _find_free_port()
        os.environ["DASHBOARD_PORT"] = str(port)

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
        server = DashboardServerThread(app, settings.dashboard_host, settings.dashboard_port)
        base_url = f"http://{settings.dashboard_host}:{settings.dashboard_port}"
        server.start()

        try:
            _wait_for_dashboard(base_url)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1320}, color_scheme="light")
                page.goto(f"{base_url}/login", wait_until="networkidle")
                hashes = {"login": screenshot_hash(page)}

                page.get_by_label("用户名").fill(settings.dashboard_auth_username)
                page.get_by_label("密码").fill(settings.dashboard_auth_password)
                page.get_by_role("button", name="进入 Dashboard").click()
                page.wait_for_url(f"{base_url}/", timeout=10000)
                page.get_by_text("沈知微长期陪伴系统").wait_for(timeout=10000)
                normalize_dashboard_for_snapshot(page)
                hashes["overview"] = screenshot_hash(page)

                page.locator(".tab-nav").get_by_role("button", name="候选记忆").click()
                page.get_by_role("button", name="拒绝").first.wait_for(timeout=10000)
                normalize_dashboard_for_snapshot(page)
                page.wait_for_timeout(600)
                hashes["candidates"] = screenshot_hash(page.locator("#panel-host"), full_page=False)
                browser.close()

            mismatches = {
                key: value
                for key, value in hashes.items()
                if EXPECTED_HASHES.get(key) != value
            }
            if mismatches:
                raise AssertionError(
                    "visual snapshot mismatch. Update EXPECTED_HASHES if the change is intentional:\n"
                    + "\n".join(f"{key}={value}" for key, value in mismatches.items())
                )
        finally:
            server.stop()
            server.join(timeout=5)
            database.close()

    print("dashboard_visual_regression.py: snapshot hashes passed.")


if __name__ == "__main__":
    main()
