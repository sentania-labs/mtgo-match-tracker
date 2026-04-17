"""Password and bearer-token hashing.

Uses `bcrypt` directly — passlib 1.7.4 is unmaintained and breaks
against bcrypt ≥ 4.1 because of a removed `__about__` attribute.
Bearer tokens are 256 bits of secrets.token_urlsafe entropy and are
hashed with SHA-256 (slow-hashing random tokens gains nothing and
makes the auth dep hot path meaningfully slower).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

import bcrypt


_BCRYPT_MAX_BYTES = 72


def _password_bytes(password: str) -> bytes:
    # bcrypt truncates silently at 72 bytes on some builds and rejects
    # with ValueError on others. Truncate explicitly so behavior is the
    # same across versions and so extremely long passwords can't cause
    # a 500.
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt())
    return hashed.decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), hashed.encode("ascii"))
    except ValueError:
        return False


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_token(token), hashed)
