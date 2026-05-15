from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from src.core.settings import Settings
from src.product.store import ProductStore


logger = logging.getLogger(__name__)

TaskHandler = Callable[[dict[str, Any]], Awaitable[Optional[dict[str, Any]]]]


class BackgroundTaskManager:
    def __init__(self, *, settings: Settings, product_store: ProductStore) -> None:
        self.settings = settings
        self.product_store = product_store
        self.handlers: dict[str, TaskHandler] = {}
        self._worker_task: asyncio.Task | None = None
        self._periodic_tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        self.handlers[task_type] = handler

    def enqueue(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        dedupe_key: str | None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        session_id: str | None = None,
        priority: float = 0.5,
        timeout_seconds: int | None = None,
        max_attempts: int | None = None,
        delay_seconds: int = 0,
    ) -> str | None:
        return self.product_store.enqueue_task(
            task_type=task_type,
            payload=payload,
            dedupe_key=dedupe_key,
            user_id=user_id,
            conversation_id=conversation_id,
            session_id=session_id,
            priority=priority,
            timeout_seconds=timeout_seconds or self.settings.background_task_timeout_seconds,
            max_attempts=max_attempts or self.settings.background_task_max_attempts,
            delay_seconds=delay_seconds,
        )

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._stop_event.clear()
            recovered = self.product_store.recover_stale_tasks()
            if recovered:
                logger.warning("Recovered %s stale background task(s) before worker start", recovered)
            self._worker_task = asyncio.create_task(self._worker_loop(), name="background-task-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._worker_task is not None:
            await asyncio.wait([self._worker_task], timeout=5)
        for periodic in self._periodic_tasks:
            periodic.cancel()
        self._periodic_tasks.clear()

    def schedule_periodic(
        self,
        *,
        task_type: str,
        payload_factory: Callable[[], dict[str, Any]] | None,
        dedupe_key: str,
        interval_seconds: int,
        priority: float = 0.4,
    ) -> None:
        async def _loop() -> None:
            while not self._stop_event.is_set():
                self.enqueue(
                    task_type=task_type,
                    payload=payload_factory() if payload_factory else {},
                    dedupe_key=dedupe_key,
                    priority=priority,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                except asyncio.TimeoutError:
                    continue

        self._periodic_tasks.append(asyncio.create_task(_loop(), name=f"periodic-{task_type}"))

    async def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            self.product_store.recover_stale_tasks()
            task = self.product_store.claim_next_task()
            if task is None:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.background_poll_seconds)
                except asyncio.TimeoutError:
                    continue
                continue
            handler = self.handlers.get(task.task_type)
            if handler is None:
                logger.warning("No background handler registered for task %s", task.task_type)
                self.product_store.fail_task(task.task_uid, error_text=f"No handler for {task.task_type}")
                continue
            try:
                result = await asyncio.wait_for(handler(task.payload), timeout=task.timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning("Background task timed out: %s", task.task_uid)
                self.product_store.mark_task_timed_out(task.task_uid, error_text="Task timed out")
                continue
            except Exception as exc:  # noqa: BLE001
                logger.exception("Background task failed: %s", task.task_uid)
                self.product_store.fail_task(task.task_uid, error_text=f"{type(exc).__name__}: {exc}")
                continue
            self.product_store.complete_task(task.task_uid, result=result or {})
