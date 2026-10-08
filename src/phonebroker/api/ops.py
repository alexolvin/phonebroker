"""Operation endpoints — execute within an active lease."""

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from phonebroker import adb, db
from phonebroker.api.auth import require_project
from phonebroker import maintenance
from phonebroker.config import load_config

router = APIRouter()


class TapBody(BaseModel):
    x: int
    y: int


class TapSelectorBody(BaseModel):
    selector: str


class SwipeBody(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = 300


class TextBody(BaseModel):
    text: str


class KeyEventBody(BaseModel):
    keycode: int


class WaitForBody(BaseModel):
    selector: str
    timeout_s: int = 30


def _require_active_lease(request: Request, lease_id: str, project: str):
    """Validate lease is active and belongs to project."""
    if maintenance.is_active(request.app.state.db):
        raise HTTPException(status_code=423, detail="maintenance")
    conn = request.app.state.db
    row = db.get_lease(conn, lease_id)
    if row is None or row["project"] != project:
        raise HTTPException(status_code=404, detail="Lease not found")
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail=f"Lease is {row['status']}")
    return row


@router.post("/lease/{lease_id}/ops/launch")
async def op_launch(lease_id: str, request: Request):
    """Launch the platform package for this lease. No parameters allowed."""
    project = require_project(request)
    lease_row = _require_active_lease(request, lease_id, project)

    conn = request.app.state.db
    cfg = load_config()
    platform = lease_row["platform"]
    platform_cfg = cfg.platforms.get(platform)
    if platform_cfg is None:
        raise HTTPException(
            status_code=500,
            detail=f"Unknown platform '{platform}'",
        )

    eff = db.get_effective_package(conn, platform=platform, manual_package=platform_cfg.package)
    if eff is None:
        raise HTTPException(
            status_code=500,
            detail=f"No package configured for platform '{platform}'",
        )
    package, available = eff
    if not available:
        raise HTTPException(
            status_code=409,
            detail=f"Platform '{platform}': application not installed",
        )

    try:
        activity = adb.launch_package(package)
    except adb.ADBError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Track the launched package for reset
    db.set_lease_package(conn, lease_id, package)
    conn.commit()

    return {"launched": package, "activity": activity}


@router.post("/lease/{lease_id}/ops/tap")
async def op_tap(lease_id: str, body: TapBody, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    adb.tap(body.x, body.y)
    return {"ok": True}


@router.post("/lease/{lease_id}/ops/tap_selector")
async def op_tap_selector(lease_id: str, body: TapSelectorBody, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    pos = adb.find_element(body.selector)
    if pos is None:
        raise HTTPException(status_code=404, detail="Element not found")
    adb.tap(pos[0], pos[1])
    return {"ok": True, "tapped": list(pos)}


@router.post("/lease/{lease_id}/ops/swipe")
async def op_swipe(lease_id: str, body: SwipeBody, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    adb.swipe(body.x1, body.y1, body.x2, body.y2, body.duration_ms)
    return {"ok": True}


@router.post("/lease/{lease_id}/ops/text")
async def op_text(lease_id: str, body: TextBody, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    adb.type_text(body.text)
    return {"ok": True}


@router.post("/lease/{lease_id}/ops/keyevent")
async def op_keyevent(lease_id: str, body: KeyEventBody, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    adb.keyevent(body.keycode)
    return {"ok": True}


@router.post("/lease/{lease_id}/ops/screenshot")
async def op_screenshot(lease_id: str, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)

    png_data = adb.screenshot()

    # Save to data dir
    cfg = load_config()
    shot_dir = Path(cfg.data_dir) / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / f"{lease_id}.png"
    shot_path.write_bytes(png_data)

    b64 = base64.b64encode(png_data).decode("ascii")
    return {"image": b64, "path": str(shot_path)}


@router.post("/lease/{lease_id}/ops/ui_dump")
async def op_ui_dump(lease_id: str, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    xml = adb.ui_dump()
    return {"xml": xml}


@router.post("/lease/{lease_id}/ops/wait_for")
async def op_wait_for(lease_id: str, body: WaitForBody, request: Request):
    project = require_project(request)
    _require_active_lease(request, lease_id, project)
    found = adb.wait_for(body.selector, body.timeout_s)
    if not found:
        raise HTTPException(status_code=408, detail="Timeout waiting for element")
    return {"ok": True}
