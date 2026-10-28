from fastapi import APIRouter, Depends

from app.deps import ResourcesDep, SessionDep, require_admin
from app.schemas import ReconcileOut, ResetSaleIn, SaleOut, SaleStatsOut
from app.services.sales import reconcile_sale, reset_sale, sale_stats

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/sales/{sale_id}/reset", summary="Restock and reschedule a sale")
async def reset(
    sale_id: int, body: ResetSaleIn, session: SessionDep, resources: ResourcesDep
) -> SaleOut:
    # Drop queued reservations of the previous run before rewriting state.
    await resources.publisher.purge()
    sale = await reset_sale(
        session,
        resources.gate,
        sale_id,
        stock=body.stock,
        starts_in_seconds=body.starts_in_seconds,
        duration_minutes=body.duration_minutes,
    )
    resources.sale_cache.invalidate()
    return sale.to_out()


@router.get("/sales/{sale_id}/stats", summary="Inventory invariants: Redis vs PostgreSQL vs queue")
async def stats(sale_id: int, session: SessionDep, resources: ResourcesDep) -> SaleStatsOut:
    return await sale_stats(
        session, resources.gate, sale_id, queue_depth=await resources.publisher.queue_depth()
    )


@router.post("/sales/{sale_id}/reconcile", summary="Copy PostgreSQL stock back into Redis")
async def reconcile(sale_id: int, session: SessionDep, resources: ResourcesDep) -> ReconcileOut:
    before, after = await reconcile_sale(
        session, resources.gate, sale_id, queue_depth=await resources.publisher.queue_depth()
    )
    return ReconcileOut(sale_id=sale_id, redis_stock_before=before, redis_stock_after=after)
