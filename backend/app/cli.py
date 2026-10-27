"""Operational commands, run inside the backend image.

python -m app.cli seed                      # idempotent demo data + Redis priming
python -m app.cli reset-sale --stock 500 --starts-in 30
python -m app.cli seed-loadtest-users --count 5000 --out /data/tokens.json
python -m app.cli verify-sale --wait 120    # exit 1 if oversold / inconsistent
python -m app.cli reconcile
"""

import argparse
import asyncio
import contextlib
import json
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.logging import configure_logging
from app.messaging import OrderPublisher
from app.models import User
from app.redis_client import create_redis
from app.schemas import SaleStatsOut
from app.security import create_access_token, hash_password
from app.services.inventory import InventoryGate
from app.services.sales import (
    prime_sale,
    reconcile_sale,
    reset_sale,
    sale_stats,
    seed_demo_sale,
)


@dataclass
class Ctx:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    gate: InventoryGate
    publisher: OrderPublisher | None


@contextlib.asynccontextmanager
async def context(*, with_mq: bool = False) -> AsyncIterator[Ctx]:
    settings = get_settings()
    configure_logging(settings.log_level, service="cli")
    engine = create_engine(settings, application_name="flashsale-cli")
    redis = create_redis(settings)
    publisher = OrderPublisher(settings) if with_mq else None
    if publisher:
        await publisher.start()
    try:
        yield Ctx(
            settings, engine, create_sessionmaker(engine), redis, InventoryGate(redis), publisher
        )
    finally:
        if publisher:
            await publisher.close()
        await redis.aclose()
        await engine.dispose()


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


async def cmd_seed(_: argparse.Namespace) -> int:
    async with context() as ctx, ctx.sessionmaker() as session:
        s = ctx.settings
        sale_id, created = await seed_demo_sale(
            session,
            stock=s.seed_sale_stock,
            starts_in_seconds=s.seed_sale_starts_in_seconds,
            duration_minutes=s.seed_sale_duration_minutes,
        )
        primed = await prime_sale(session, ctx.gate, sale_id)
        _print({"sale_id": sale_id, "created": created, "redis_primed": primed})
    return 0


async def cmd_reset(args: argparse.Namespace) -> int:
    async with context(with_mq=True) as ctx, ctx.sessionmaker() as session:
        assert ctx.publisher is not None
        await ctx.publisher.purge()
        sale = await reset_sale(
            session,
            ctx.gate,
            args.sale_id,
            stock=args.stock,
            starts_in_seconds=args.starts_in,
            duration_minutes=args.duration,
        )
        _print(sale.to_out().model_dump())
    return 0


async def cmd_seed_users(args: argparse.Namespace) -> int:
    """Bulk-create load-test users and mint their JWTs (no bcrypt per user)."""
    async with context() as ctx, ctx.sessionmaker() as session:
        password_hash = hash_password("loadtest-password", ctx.settings.bcrypt_rounds)
        emails = [f"{args.prefix}-{i:06d}@example.com" for i in range(args.count)]
        for start in range(0, len(emails), 1000):
            chunk = emails[start : start + 1000]
            await session.execute(
                insert(User)
                .values([{"email": e, "password_hash": password_hash} for e in chunk])
                .on_conflict_do_nothing(index_elements=[User.email])
            )
        await session.commit()
        ids = (await session.scalars(select(User.id).where(User.email.in_(emails)))).all()
        tokens = [create_access_token(uid, ctx.settings)[0] for uid in ids]
    out = Path(args.out)
    await asyncio.to_thread(out.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(out.write_text, json.dumps(tokens))
    _print({"users": len(tokens), "tokens_file": str(out)})
    return 0


async def _stats(ctx: Ctx, sale_id: int) -> SaleStatsOut:
    assert ctx.publisher is not None
    async with ctx.sessionmaker() as session:
        return await sale_stats(
            session, ctx.gate, sale_id, queue_depth=await ctx.publisher.queue_depth()
        )


async def cmd_verify(args: argparse.Namespace) -> int:
    """Wait for every reservation to be persisted, then check the invariants."""
    async with context(with_mq=True) as ctx:
        deadline = time.monotonic() + args.wait
        while True:
            stats = await _stats(ctx, args.sale_id)
            processed = (
                stats.confirmed + stats.rejected_sold_out + stats.rejected_duplicate + stats.failed
            )
            drained = stats.queue_depth == 0 and processed >= stats.reservations
            if drained or time.monotonic() > deadline:
                break
            await asyncio.sleep(1)
        _print(stats.model_dump() | {"drained": drained})
        if stats.oversold or not stats.consistent:
            print("FAIL: inventory invariant violated", file=sys.stderr)
            return 1
        if not drained:
            print("FAIL: queue did not drain in time", file=sys.stderr)
            return 2
        print(
            f"OK: {stats.confirmed}/{stats.total_stock} sold, "
            f"{stats.db_stock} left, oversold={stats.oversold}",
            file=sys.stderr,
        )
    return 0


async def cmd_reconcile(args: argparse.Namespace) -> int:
    async with context(with_mq=True) as ctx, ctx.sessionmaker() as session:
        assert ctx.publisher is not None
        before, after = await reconcile_sale(
            session, ctx.gate, args.sale_id, queue_depth=await ctx.publisher.queue_depth()
        )
        _print({"sale_id": args.sale_id, "redis_stock_before": before, "redis_stock_after": after})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="create demo product/sale if missing; prime Redis").set_defaults(
        fn=cmd_seed
    )

    p = sub.add_parser("reset-sale", help="restock + reschedule a sale (deletes its orders)")
    p.add_argument("--sale-id", type=int, default=1)
    p.add_argument("--stock", type=int, default=500)
    p.add_argument("--starts-in", type=int, default=30, help="seconds from now")
    p.add_argument("--duration", type=int, default=60, help="minutes")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("seed-loadtest-users", help="bulk users + JWTs for k6")
    p.add_argument("--count", type=int, default=5000)
    p.add_argument("--prefix", default="loadtest")
    p.add_argument("--out", default="/data/tokens.json")
    p.set_defaults(fn=cmd_seed_users)

    p = sub.add_parser("verify-sale", help="assert no oversell once the queue drains")
    p.add_argument("--sale-id", type=int, default=1)
    p.add_argument("--wait", type=int, default=120, help="max seconds to wait for drain")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("reconcile", help="copy DB stock into Redis (queue must be empty)")
    p.add_argument("--sale-id", type=int, default=1)
    p.set_defaults(fn=cmd_reconcile)

    args = parser.parse_args(argv)
    result: int = asyncio.run(args.fn(args))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
