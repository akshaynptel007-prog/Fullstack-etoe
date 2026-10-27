"""Password hashing and stateless JWT auth.

Tokens are verified without a database lookup, so authenticating a checkout
request costs zero I/O. bcrypt is CPU-bound and would stall the event loop,
so hashing always runs in the threadpool.
"""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.errors import AppError


def hash_password(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


@lru_cache
def _dummy_hash(rounds: int) -> str:
    return hash_password("timing-equaliser", rounds)


async def hash_password_async(password: str, rounds: int) -> str:
    return await run_in_threadpool(hash_password, password, rounds)


async def verify_password_async(password: str, password_hash: str | None, rounds: int) -> bool:
    # Always run one bcrypt comparison so "unknown email" and "wrong password"
    # take the same time (no user enumeration via timing).
    target = password_hash or _dummy_hash(rounds)
    ok = await run_in_threadpool(verify_password, password, target)
    return ok and password_hash is not None


def create_access_token(user_id: uuid.UUID, settings: Settings) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_in = settings.jwt_expires_minutes * 60
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "iss": settings.app_name,
    }
    token = jwt.encode(claims, settings.jwt_secret.get_secret_value(), settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["sub", "exp", "iat"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise AppError(
            401,
            "INVALID_TOKEN",
            "Your session has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
