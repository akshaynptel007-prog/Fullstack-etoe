import hmac
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.metrics import RATE_LIMITED
from app.middleware import client_ip
from app.resources import Resources
from app.security import decode_access_token
from app.services.rate_limit import RateLimitResult

_bearer = HTTPBearer(auto_error=False)


def get_resources(request: Request) -> Resources:
    resources: Resources = request.app.state.resources
    return resources


ResourcesDep = Annotated[Resources, Depends(get_resources)]


async def get_session(resources: ResourcesDep) -> AsyncIterator[AsyncSession]:
    async with resources.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def current_user_id(
    resources: ResourcesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> uuid.UUID:
    if credentials is None:
        raise AppError(
            401, "AUTH_REQUIRED", "Please sign in.", headers={"WWW-Authenticate": "Bearer"}
        )
    return decode_access_token(credentials.credentials, resources.settings)


UserIdDep = Annotated[uuid.UUID, Depends(current_user_id)]


def require_admin(
    resources: ResourcesDep, x_admin_key: Annotated[str | None, Header()] = None
) -> None:
    expected = resources.settings.admin_api_key.get_secret_value()
    if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
        raise AppError(401, "ADMIN_AUTH_REQUIRED", "A valid X-Admin-Key header is required.")


def request_ip(request: Request, resources: ResourcesDep) -> str:
    return client_ip(request, resources.settings.client_ip_trusted_hops)


ClientIpDep = Annotated[str, Depends(request_ip)]


def raise_if_limited(result: RateLimitResult, scope: str) -> None:
    if not result.allowed:
        RATE_LIMITED.labels(scope).inc()
        raise AppError(
            429,
            "RATE_LIMITED",
            "Too many requests — slow down and retry shortly.",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
