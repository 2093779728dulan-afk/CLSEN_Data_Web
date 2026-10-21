from __future__ import annotations

from app.auth.passwords import hash_password, password_needs_rehash, verify_password


def test_passwords_are_salted_and_verified_with_argon2id() -> None:
    password = "correct horse battery staple"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash.startswith("$argon2id$")
    assert second_hash.startswith("$argon2id$")
    assert first_hash != second_hash
    assert verify_password(first_hash, password)
    assert verify_password(second_hash, password)
    assert not verify_password(first_hash, "incorrect password")


def test_current_password_hash_does_not_need_rehash() -> None:
    password_hash = hash_password("a local administrator password")

    assert not password_needs_rehash(password_hash)
