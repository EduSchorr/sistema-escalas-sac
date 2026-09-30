from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 240_000


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _ITERATIONS,
    )
    return digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    try:
        actual = hash_password(password, salt)
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected_hash)


def session_token() -> str:
    return secrets.token_urlsafe(32)


def password_reset_token() -> str:
    return secrets.token_urlsafe(32)
