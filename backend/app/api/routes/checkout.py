from fastapi import APIRouter, Response, status

from app.deps import ClientIpDep, ResourcesDep, UserIdDep, raise_if_limited
from app.logging import request_id_var
from app.models import OrderStatus
from app.schemas import CheckoutAccepted, ErrorResponse

router = APIRouter(tags=["checkout"])


@router.post(
    "/sales/{sale_id}/checkout",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reserve one unit; the order is persisted asynchronously",
    responses={
        200: {"model": CheckoutAccepted, "description": "Already reserved (idempotent repeat)"},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "SOLD_OUT / SALE_NOT_STARTED / SALE_ENDED"},
        429: {"model": ErrorResponse, "description": "Rate limited (see Retry-After)"},
        503: {"model": ErrorResponse, "description": "Queue unavailable (see Retry-After)"},
    },
)
async def checkout(
    sale_id: int,
    user_id: UserIdDep,
    ip: ClientIpDep,
    resources: ResourcesDep,
    response: Response,
) -> CheckoutAccepted:
    s = resources.settings
    window_ms = s.rate_limit_window_seconds * 1000
    limiter = resources.rate_limiter
    # Per-IP first (cheap rejection of a single noisy source), then per-user
    # (stops one account hammering from many IPs).
    raise_if_limited(
        await limiter.hit(
            "checkout_ip", ip, limit=s.rate_limit_checkout_per_ip, window_ms=window_ms
        ),
        "checkout_ip",
    )
    raise_if_limited(
        await limiter.hit(
            "checkout_user", str(user_id), limit=s.rate_limit_checkout_per_user, window_ms=window_ms
        ),
        "checkout_user",
    )

    result = await resources.checkout.checkout(
        sale_id=sale_id, user_id=user_id, request_id=request_id_var.get()
    )
    status_url = f"/api/v1/orders/{result.order_id}"
    response.headers["Location"] = status_url
    response.headers["Cache-Control"] = "no-store"
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return CheckoutAccepted(
        order_id=result.order_id,
        status=OrderStatus.PENDING,
        status_url=status_url,
        poll_after_ms=s.order_poll_after_ms,
        duplicate=result.duplicate,
    )
