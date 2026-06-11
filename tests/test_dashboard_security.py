from __future__ import annotations

from starlette.requests import Request

from src.dashboard.security import PBKDF2_ITERATIONS, hash_dashboard_password, request_source_ip, verify_dashboard_password


def test_dashboard_password_hash_verifies_and_rejects_wrong_input() -> None:
    stored_hash = hash_dashboard_password("correct horse battery staple")

    algorithm, iterations_text, salt, digest = stored_hash.split("$", 3)
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations_text) == PBKDF2_ITERATIONS
    assert len(salt) == 32
    assert digest
    assert verify_dashboard_password("correct horse battery staple", stored_hash)
    assert not verify_dashboard_password("wrong phrase", stored_hash)


def test_dashboard_password_hash_rejects_invalid_hashes() -> None:
    unsupported_hash = "$".join(("argon2", "1", "salt", "digest"))
    invalid_iteration_hash = "$".join(("pbkdf2_sha256", "not-int", "salt", "digest"))

    assert not verify_dashboard_password("anything", "")
    assert not verify_dashboard_password("anything", "plain")
    assert not verify_dashboard_password("anything", unsupported_hash)
    assert not verify_dashboard_password("anything", invalid_iteration_hash)


def test_request_source_ip_uses_client_host_when_present() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("192.0.2.10", 12345)})
    assert request_source_ip(request) == "192.0.2.10"


def test_request_source_ip_returns_unknown_without_client() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    assert request_source_ip(request) == "unknown"
