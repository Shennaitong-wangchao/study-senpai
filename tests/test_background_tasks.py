from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable

from src.product.tasks import BackgroundTaskManager


class FakeTaskStore:
    def __init__(self, tasks: list[SimpleNamespace] | None = None) -> None:
        self.tasks = list(tasks or [])
        self.enqueued: list[dict[str, Any]] = []
        self.completed: list[tuple[str, dict[str, Any]]] = []
        self.failed: list[tuple[str, str]] = []
        self.timed_out: list[tuple[str, str]] = []
        self.recovered_calls = 0
        self.on_complete: Callable[[], None] | None = None
        self.on_fail: Callable[[], None] | None = None
        self.on_timeout: Callable[[], None] | None = None

    def enqueue_task(self, **kwargs: Any) -> str:
        self.enqueued.append(kwargs)
        return "task-enqueued"

    def recover_stale_tasks(self) -> int:
        self.recovered_calls += 1
        return 0

    def claim_next_task(self) -> SimpleNamespace | None:
        if not self.tasks:
            return None
        return self.tasks.pop(0)

    def complete_task(self, task_uid: str, result: dict[str, Any]) -> None:
        self.completed.append((task_uid, result))
        if self.on_complete:
            self.on_complete()

    def fail_task(self, task_uid: str, error_text: str) -> None:
        self.failed.append((task_uid, error_text))
        if self.on_fail:
            self.on_fail()

    def mark_task_timed_out(self, task_uid: str, error_text: str) -> None:
        self.timed_out.append((task_uid, error_text))
        if self.on_timeout:
            self.on_timeout()


def task_record(
    *,
    task_uid: str = "task-1",
    task_type: str = "demo",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 1.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_uid=task_uid,
        task_type=task_type,
        payload=payload or {},
        timeout_seconds=timeout_seconds,
    )


def manager_for(store: FakeTaskStore) -> BackgroundTaskManager:
    settings = SimpleNamespace(
        background_poll_seconds=60,
        background_task_timeout_seconds=30,
        background_task_max_attempts=4,
    )
    return BackgroundTaskManager(settings=settings, product_store=store)  # type: ignore[arg-type]


def test_enqueue_uses_settings_defaults_and_preserves_payload() -> None:
    store = FakeTaskStore()
    manager = manager_for(store)

    task_uid = manager.enqueue(
        task_type="summarize",
        payload={"conversation_id": "conv-1"},
        dedupe_key="summary:conv-1",
        user_id="user-1",
        priority=0.8,
    )

    assert task_uid == "task-enqueued"
    assert store.enqueued == [
        {
            "task_type": "summarize",
            "payload": {"conversation_id": "conv-1"},
            "dedupe_key": "summary:conv-1",
            "user_id": "user-1",
            "conversation_id": None,
            "session_id": None,
            "priority": 0.8,
            "timeout_seconds": 30,
            "max_attempts": 4,
            "delay_seconds": 0,
        }
    ]


def test_worker_loop_completes_registered_task() -> None:
    async def scenario() -> FakeTaskStore:
        store = FakeTaskStore([task_record(payload={"value": 7})])
        manager = manager_for(store)
        store.on_complete = manager._stop_event.set

        async def handle(payload: dict[str, Any]) -> dict[str, Any]:
            return {"value": payload["value"] + 1}

        manager.register_handler("demo", handle)
        await manager._worker_loop()
        return store

    store = asyncio.run(scenario())

    assert store.completed == [("task-1", {"value": 8})]
    assert store.failed == []
    assert store.timed_out == []


def test_worker_loop_fails_task_without_registered_handler() -> None:
    async def scenario() -> FakeTaskStore:
        store = FakeTaskStore([task_record(task_type="missing")])
        manager = manager_for(store)
        store.on_fail = manager._stop_event.set
        await manager._worker_loop()
        return store

    store = asyncio.run(scenario())

    assert store.failed == [("task-1", "No handler for missing")]
    assert store.completed == []
    assert store.timed_out == []


def test_worker_loop_marks_task_timed_out() -> None:
    async def scenario() -> FakeTaskStore:
        store = FakeTaskStore([task_record(timeout_seconds=0.001)])
        manager = manager_for(store)
        store.on_timeout = manager._stop_event.set

        async def slow_handler(payload: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(1)
            return {"unexpected": True}

        manager.register_handler("demo", slow_handler)
        await manager._worker_loop()
        return store

    store = asyncio.run(scenario())

    assert store.timed_out == [("task-1", "Task timed out")]
    assert store.completed == []
    assert store.failed == []
