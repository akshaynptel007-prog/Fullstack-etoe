from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import ClientIpDep, ResourcesDep, SessionDep, UserIdDep, raise_if_limited
from app.errors import AppError
from app.models import User
from app.schemas import Credentials, TokenOut, UserOut
from app.security import create_access_token, hash_password_async, verify_password_async

router = APIRouter(prefix="/auth", tags=["auth"])


async def _limit_auth(resources: ResourcesDep, ip: str) -> None:
    s = resources.settings
    result = await resources.rate_limiter.hit(
        "auth_ip", ip, limit=s.rate_limit_auth_per_ip, window_ms=60_000
    )
    raise_if_limited(result, "auth_ip")


def _token_response(user: User, resources: ResourcesDep) -> TokenOut:
    token, expires_in = create_access_token(user.id, resources.settings)
    return TokenOut(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: Credentials, session: SessionDep, resources: ResourcesDep, ip: ClientIpDep
) -> TokenOut:
    await _limit_auth(resources, ip)
    password_hash = await hash_password_async(body.password, resources.settings.bcrypt_rounds)
    user = User(email=body.email, password_hash=password_hash)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(409, "EMAIL_TAKEN", "An account with this email already exists.") from exc
    return _token_response(user, resources)


@router.post("/login")
async def login(
    body: Credentials, session: SessionDep, resources: ResourcesDep, ip: ClientIpDep
) -> TokenOut:
    await _limit_auth(resources, ip)
    user = await session.scalar(select(User).where(User.email == body.email))
    ok = await verify_password_async(
        body.password, user.password_hash if user else None, resources.settings.bcrypt_rounds
    )
    if not ok or user is None:
        raise AppError(401, "INVALID_CREDENTIALS", "Incorrect email or password.")
    return _token_response(user, resources)


@router.get("/me")
async def me(user_id: UserIdDep, session: SessionDep) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "Your session has expired. Please sign in again.")
    return UserOut.model_validate(user)
