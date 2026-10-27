import uuid

import jwt
import pytest

from app.config import Settings
from app.errors import AppError
from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_password_async,
)

SETTINGS = Settings(_env_file=None, bcrypt_rounds=4)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery", rounds=4)
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong password", hashed)


async def test_unknown_user_still_runs_bcrypt_and_fails() -> None:
    assert await verify_password_async("whatever-password", None, rounds=4) is False


def test_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, SETTINGS)
    assert expires_in == SETTINGS.jwt_expires_minutes * 60
    assert decode_access_token(token, SETTINGS) == user_id


def test_tampered_token_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), SETTINGS)
    forged = jwt.encode(
        {"sub": str(uuid.uuid4())},
        "attacker-secret-that-is-long-enough-0123456789",
        algorithm="HS256",
    )
    with pytest.raises(AppError) as exc:
        decode_access_token(forged, SETTINGS)
    assert exc.value.status_code == 401
    with pytest.raises(AppError):
        decode_access_token(token[:-2] + "xx", SETTINGS)


def test_expired_token_is_rejected() -> None:
    settings = SETTINGS.model_copy(update={"jwt_expires_minutes": -1})
    token, _ = create_access_token(uuid.uuid4(), settings)
    with pytest.raises(AppError):
        decode_access_token(token, SETTINGS)
