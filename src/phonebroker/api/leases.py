"""Lease API endpoints."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from phonebroker import db, lease
from phonebroker.api.auth import require_project
from phonebroker import maintenance
from phonebroker.exceptions import PlatformUnavailableError

router = APIRouter()


class LeaseRequest(BaseModel):
    platform: str
    operation: str
    priority: str  # "interactive" | "background"
    max_duration_s: int

    model_config = {"extra": "forbid"}  # project in body → 422


@router.post("/lease", status_code=201)
async def create_lease(body: LeaseRequest, request: Request):
    """Request a new lease. Returns 201 (active) or 202 (waiting)."""
    project = require_project(request)

    if maintenance.is_active():
        raise HTTPException(status_code=423, detail="maintenance")

    conn = request.app.state.db
    try:
        lease_id, status = lease.request_lease(
            conn,
            project=project,
            platform=body.platform,
            operation=body.operation,
            priority=body.priority,
            max_duration_s=body.max_duration_s,
        )
    except PlatformUnavailableError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except lease.PhoneUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except lease.SiteLimitExceeded as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if status == "waiting":
        return {"id": lease_id, "status": "waiting"}
    return {"id": lease_id, "status": "active"}


@router.get("/lease/{lease_id}")
async def get_lease(lease_id: str, request: Request):
    """Get lease status."""
    project = require_project(request)
    conn = request.app.state.db
    row = db.get_lease(conn, lease_id)
    if row is None or row["project"] != project:
        raise HTTPException(status_code=404, detail="Lease not found")
    return dict(row)


@router.delete("/lease/{lease_id}")
async def delete_lease(lease_id: str, request: Request):
    """Gracefully complete an active lease."""
    project = require_project(request)
    conn = request.app.state.db
    row = db.get_lease(conn, lease_id)
    if row is None or row["project"] != project:
        raise HTTPException(status_code=404, detail="Lease not found")
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail=f"Lease is {row['status']}")

    lease.complete_lease(conn, lease_id, project)
    return {"id": lease_id, "status": "completed"}


@router.post("/lease/{lease_id}/heartbeat")
async def heartbeat(lease_id: str, request: Request):
    """Update lease heartbeat."""
    project = require_project(request)
    conn = request.app.state.db
    row = db.get_lease(conn, lease_id)
    if row is None or row["project"] != project:
        raise HTTPException(status_code=404, detail="Lease not found")
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail=f"Lease is {row['status']}")

    db.heartbeat_lease(conn, lease_id)
    conn.commit()
    return {"ok": True}


@router.get("/leases")
async def list_leases(request: Request):
    """List project's leases."""
    project = require_project(request)
    conn = request.app.state.db
    rows = db.get_project_leases(conn, project)
    return [dict(r) for r in rows]


@router.get("/lease/{lease_id}/history")
async def lease_history(lease_id: str, request: Request):
    """Get journal for a lease."""
    project = require_project(request)
    conn = request.app.state.db
    row = db.get_lease(conn, lease_id)
    if row is None or row["project"] != project:
        raise HTTPException(status_code=404, detail="Lease not found")
    entries = db.get_lease_journal(conn, lease_id)
    return [dict(e) for e in entries]
