"""Maintenance mode API endpoints (owner token only)."""

from fastapi import APIRouter, HTTPException, Request

from phonebroker import maintenance

router = APIRouter()


@router.post("/maintenance/start")
async def maintenance_start(request: Request):
    from phonebroker.api.auth import require_owner

    require_owner(request)
    conn = request.app.state.db
    maintenance.start(conn)
    return {"status": "maintenance_active"}


@router.post("/maintenance/renew")
async def maintenance_renew(request: Request):
    from phonebroker.api.auth import require_owner

    require_owner(request)
    if not maintenance.is_active():
        raise HTTPException(status_code=409, detail="Maintenance not active")
    conn = request.app.state.db
    maintenance.renew(conn)
    return {"ok": True}


@router.post("/maintenance/end")
async def maintenance_end(request: Request):
    from phonebroker.api.auth import require_owner

    require_owner(request)
    if not maintenance.is_active():
        raise HTTPException(status_code=409, detail="Maintenance not active")
    conn = request.app.state.db
    sync_result = maintenance.end(conn, "end_by_owner")
    return {"status": "maintenance_ended", "sync": sync_result}
