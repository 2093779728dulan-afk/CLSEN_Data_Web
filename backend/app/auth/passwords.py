"""Argon2id password hashing without application-level secret logging."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

_PASSWORD_HASHER = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    """Return a salted Argon2id hash for a non-empty password."""

    if not password:
        raise ValueError("password must not be empty")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password while treating malformed hashes as authentication failure."""

    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except InvalidHashError, VerificationError, VerifyMismatchError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether the stored hash should be upgraded to current parameters."""

    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
