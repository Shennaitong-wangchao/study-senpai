from __future__ import annotations

import hashlib
import secrets
from typing import Final

from fastapi import Request


PBKDF2_ITERATIONS: Final[int] = 390000


def hash_dashboard_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_dashboard_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iterations_text)
    except ValueError:
        return False
    calculated_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return secrets.compare_digest(calculated_digest, expected_digest)


def request_source_ip(request: Request) -> str:
    # P0-3: 之前无条件信任 X-Forwarded-For 的第一跳，容易被伪造源IP。
    # 修复：仅当明确知道运行在受信任反向代理后才读取，默认使用真实直连 IP。
    # 在没有显式配置受信任代理时，fallback 回 request.client.host。
    # 若需支持代理，应用层必须在启动时或者中间件里做处理，在底层获取真实源。
    # 我们这里最安全的基础设施是返回 client.host 首先，如果一定要拿到 forwarded，需要业务做判断，
    # 但根据 P0-3 问题描述，我们应该移除对 x-forwarded-for 无条件信任。
    # 目前改为：只通过 request.client.host 获取直连IP，
    # x-forwarded-for 应该由具备 TrustedHostMiddleware 功能的层去把控 request.client。
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
