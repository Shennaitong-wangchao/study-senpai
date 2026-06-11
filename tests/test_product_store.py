from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.core.types import ConversationScope
from src.db.database import Database
from src.memory.models import LongTermMemoryCandidate
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


def test_candidate_memory_review_reopen_and_dedupe(product_store: ProductStore) -> None:
    scope = ConversationScope(
        platform="discord",
        conversation_id="conv-1",
        user_id="user-1",
        channel_id="channel-1",
        guild_id=None,
        session_id="session-1",
    )
    candidate = LongTermMemoryCandidate(
        memory_type="preference",
        category="study",
        content="likes quiet evening review",
        tags=["study"],
        importance=0.8,
        confidence=0.7,
        reason="explicit preference",
        source_message_ids=[101],
        metadata={"source": "test"},
    )

    candidate_uid = product_store.create_candidate_memory(scope, candidate)
    duplicate_uid = product_store.create_candidate_memory(scope, candidate)

    assert candidate_uid is not None
    assert duplicate_uid is None
    pending = product_store.list_candidate_memories(user_id="user-1", status="pending")
    assert [item.candidate_uid for item in pending] == [candidate_uid]
    assert pending[0].tags == ["study"]
    assert pending[0].metadata == {"source": "test"}

    assert (
        product_store.mark_candidate_reviewed(
            candidate_uid,
            status="approved",
            review_note="promote",
            approved_memory_uid="mem-1",
            expected_status="rejected",
        )
        is False
    )
    assert product_store.mark_candidate_reviewed(candidate_uid, status="rejected", expected_status="pending") is True
    assert product_store.reopen_candidate_memory(candidate_uid) is True
    assert product_store.reopen_candidate_memory(candidate_uid) is False

    reopened = product_store.get_candidate_memory(candidate_uid)
    assert reopened is not None
    assert reopened.status == "pending"
    assert reopened.review_note is None


def test_memory_hit_tracking_lists_active_memories_by_hit_count(product_store: ProductStore) -> None:
    now = "2026-06-11T00:00:00+00:00"
    rows = [
        ("mem-a", "user-1", "preference", "study", "quiet review", 0.9, 0.8, "active"),
        ("mem-b", "user-1", "fact", "school", "exam next week", 0.6, 0.7, "active"),
        ("mem-c", "user-1", "fact", "archived", "old detail", 0.5, 0.6, "archived"),
    ]
    product_store.db.executemany(
        """
        INSERT INTO long_term_memories (
            memory_uid, user_id, memory_type, category, content, confidence, importance, status,
            tags_json, source_message_ids_json, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', '{}', ?, ?)
        """,
        [(*row, now, now) for row in rows],
    )

    product_store.record_memory_hits("user-1", ["mem-b"], context_type="search")
    product_store.record_memory_hits("user-1", ["mem-a", "mem-b", "mem-c"], context_type="reply")

    top_hits = product_store.list_top_memory_hits("user-1")

    assert [item["memory_uid"] for item in top_hits] == ["mem-b", "mem-a"]
    assert top_hits[0]["hit_count"] == 2
    assert top_hits[1]["hit_count"] == 1


def test_dashboard_security_events_metrics_and_action_audit(product_store: ProductStore) -> None:
    product_store.record_dashboard_security_event(
        event_type="login_failure",
        username="admin",
        source_ip="198.51.100.10",
        success=False,
        details={"reason": "bad code"},
    )
    product_store.record_dashboard_security_event(
        event_type="login_failure",
        username="admin",
        source_ip="198.51.100.10",
        success=False,
    )
    product_store.record_dashboard_security_event(
        event_type="login_success",
        username="admin",
        source_ip="198.51.100.11",
        success=True,
    )

    lock_status = product_store.get_dashboard_lock_status(
        source_ip="198.51.100.10",
        window_seconds=300,
        max_attempts=2,
        lockout_seconds=600,
    )
    metrics = product_store.get_dashboard_security_metrics(
        window_seconds=300,
        max_attempts=2,
        lockout_seconds=600,
    )
    events = product_store.list_dashboard_security_events()

    assert lock_status["locked"] is True
    assert metrics["failed_last_window"] == 2
    assert metrics["success_last_window"] == 1
    assert metrics["locked_sources"][0]["source_ip"] == "198.51.100.10"
    assert events[-1]["details"] == {"reason": "bad code"}

    audit_uid = product_store.record_dashboard_action_audit(
        actor_username="admin",
        source_ip="198.51.100.10",
        action_type="approve_memory",
        target_type="candidate_memory",
        target_id="cand-1",
        scope_user_id="user-1",
        scope_conversation_id="conv-1",
        details={"status": "approved"},
        undo_available=True,
        undo_payload={"candidate_uid": "cand-1"},
    )

    assert product_store.mark_dashboard_action_undone(audit_uid) is True
    assert product_store.mark_dashboard_action_undone(audit_uid) is False
    audit = product_store.get_dashboard_action_audit(audit_uid)
    listed = product_store.list_dashboard_action_audits()

    assert audit is not None
    assert audit["status"] == "undone"
    assert audit["undo_available"] is True
    assert audit["undo_payload"] == {"candidate_uid": "cand-1"}
    assert listed[0]["audit_uid"] == audit_uid
    assert listed[0]["details"] == {"status": "approved"}


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
