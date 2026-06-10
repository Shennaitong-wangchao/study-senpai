from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.db.database import Database
from src.product.store import ProductStore, _redact_log_line


@pytest.fixture()
def product_store(tmp_path) -> Iterator[ProductStore]:
    database = Database(str(tmp_path / "store.sqlite3"))
    database.initialize()
    try:
        yield ProductStore(database)
    finally:
        database.close()


def test_app_settings_dashboard_scope_and_password_change_state(product_store: ProductStore) -> None:
    assert product_store.get_app_setting("missing", {"fallback": True}) == {"fallback": True}

    product_store.set_app_setting("feature", {"enabled": True})
    assert product_store.get_app_setting("feature") == {"enabled": True}
    product_store.delete_app_setting("feature")
    assert product_store.get_app_setting("feature", None) is None

    product_store.set_app_setting("dashboard_active_scope", {"user_id": " ", "conversation_id": "conv-1"})
    assert product_store.get_dashboard_active_scope() is None

    scope = product_store.set_dashboard_active_scope(
        user_id="user-1",
        conversation_id="conv-1",
        channel_id="channel-1",
        guild_id=None,
    )

    assert product_store.get_dashboard_active_scope() == scope
    assert product_store.dashboard_password_change_required(generated_password_in_use=True) is True

    product_store.set_dashboard_password_hash("hash-value")
    assert product_store.get_dashboard_password_hash() == "hash-value"
    assert product_store.dashboard_password_change_required(generated_password_in_use=True) is False

    product_store.set_dashboard_password_change_required(True)
    assert product_store.dashboard_password_change_required(generated_password_in_use=False) is True


def test_mode_state_upsert_merges_metadata(product_store: ProductStore) -> None:
    initial = product_store.get_mode_state("user-1", "conv-1")

    assert initial.mode == "auto"
    assert initial.learning_mode is False

    first = product_store.upsert_mode_state(
        "user-1",
        "conv-1",
        mode="fast",
        learning_mode=True,
        custom_model="model-a",
        backup_model=None,
        metadata={"source": "test"},
    )
    second = product_store.upsert_mode_state(
        "user-1",
        "conv-1",
        mode="thinking",
        learning_mode=False,
        custom_model=None,
        backup_model="backup-a",
        metadata={"updated": True},
    )

    assert first.learning_mode is True
    assert second.mode == "thinking"
    assert second.custom_model is None
    assert second.backup_model == "backup-a"
    assert second.metadata == {"source": "test", "updated": True}


def test_background_task_lifecycle_dedupe_retry_fail_and_cancel(product_store: ProductStore) -> None:
    task_uid = product_store.enqueue_task(
        task_type="summary",
        payload={"conversation_id": "conv-1"},
        dedupe_key="summary:conv-1",
        user_id="user-1",
        conversation_id="conv-1",
        priority=0.9,
        timeout_seconds=30,
        max_attempts=2,
    )
    duplicate_uid = product_store.enqueue_task(
        task_type="summary",
        payload={"conversation_id": "conv-1"},
        dedupe_key="summary:conv-1",
    )

    assert duplicate_uid == task_uid

    claimed = product_store.claim_next_task()

    assert claimed is not None
    assert claimed.task_uid == task_uid
    assert claimed.status == "running"
    assert claimed.attempts == 1
    assert claimed.payload == {"conversation_id": "conv-1"}

    product_store.fail_task(task_uid, error_text="first failure", retry_delay_seconds=0)
    retrying = product_store.get_task(task_uid)

    assert retrying is not None
    assert retrying.status == "retrying"
    assert retrying.last_error == "first failure"

    claimed_again = product_store.claim_next_task()
    assert claimed_again is not None
    assert claimed_again.attempts == 2

    product_store.fail_task(task_uid, error_text="final failure", retry_delay_seconds=0)
    failed = product_store.get_task(task_uid)

    assert failed is not None
    assert failed.status == "failed"
    assert failed.last_error == "final failure"
    assert product_store.retry_task(task_uid) is True
    assert product_store.cancel_task(task_uid) is True
    assert product_store.get_task(task_uid).status == "cancelled"  # type: ignore[union-attr]


def test_background_task_completion_and_listing(product_store: ProductStore) -> None:
    task_uid = product_store.enqueue_task(
        task_type="health",
        payload={"probe": "shallow"},
        dedupe_key=None,
        user_id="user-1",
    )
    claimed = product_store.claim_next_task()

    assert claimed is not None
    assert claimed.task_uid == task_uid

    product_store.complete_task(task_uid, result={"ok": True})

    completed = product_store.get_task(task_uid)
    listed = product_store.list_tasks(status="completed", user_id="user-1")

    assert completed is not None
    assert completed.status == "completed"
    assert completed.result == {"ok": True}
    assert [task.task_uid for task in listed] == [task_uid]


def test_redact_log_line_masks_prompt_context_and_secret_like_values() -> None:
    key_name = "api" + "_key"
    bearer_word = "Bear" + "er"

    assert _redact_log_line("DEBUG Prompt context for user raw payload\n") == "DEBUG Prompt context for [redacted]\n"

    redacted_assignment = _redact_log_line(f"INFO {key_name}=visible-value\n")
    redacted_bearer = _redact_log_line(f"INFO Authorization: {bearer_word} visible-value\n")

    assert "visible-value" not in redacted_assignment
    assert "visible-value" not in redacted_bearer
    assert "[redacted]" in redacted_assignment
    assert "[redacted]" in redacted_bearer
