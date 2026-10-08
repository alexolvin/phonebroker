"""PhoneBroker FastAPI application entrypoint."""

import asyncio
import contextlib
import logging
import sqlite3

from fastapi import FastAPI, Request

from phonebroker import db, lease, maintenance
from phonebroker.api import leases, maintenance as maint_api, ops
from phonebroker.api.auth import init_token_map
from phonebroker.config import load_config, get_data_dir
from phonebroker.health import get_health

logger = logging.getLogger("phonebroker")

app = FastAPI(title="PhoneBroker", version="0.1.0")

# Routers
app.include_router(leases.router)
app.include_router(ops.router)
app.include_router(maint_api.router)


@app.on_event("startup")
async def startup():
    """Initialize DB, token map, and background task."""
    init_token_map()
    conn = db.get_connection(get_data_dir() / "phonebroker.db")
    db.init_db(conn)
    app.state.db = conn
    maintenance.on_startup(conn)
    app.state.bg_task = asyncio.create_task(_background_loop())
    logger.info("PhoneBroker started")


@app.on_event("shutdown")
async def shutdown():
    if hasattr(app.state, "bg_task"):
        app.state.bg_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.bg_task
    if hasattr(app.state, "db"):
        app.state.db.close()


@app.get("/health")
async def health(request: Request):
    return get_health(request.app.state.db)


async def _background_loop():
    """Periodic task: check timeouts, process queue, check maintenance timeout."""
    cfg = load_config()
    interval = cfg.check_interval_s
    while True:
        await asyncio.sleep(interval)
        conn = app.state.db
        try:
            # Check lease timeouts
            lease.check_timeouts(conn)

            # Check maintenance timeout
            maintenance.check_timeout(conn)

            # Try to acquire next from queue
            if not maintenance.is_active(conn):
                active = db.get_active_lease(conn)
                if active is None:
                    await _try_acquire_from_queue(conn)
        except Exception:
            logger.exception("Background loop error")


async def _try_acquire_from_queue(conn: sqlite3.Connection):
    """Try to acquire the next lease from the queue."""
    from phonebroker import queue
    from phonebroker.reset import reset_before_lease

    # Must be in a transaction
    conn.execute("BEGIN IMMEDIATE")
    try:
        queue_id = queue.try_acquire_next(conn)
        if queue_id is None:
            conn.rollback()
            return

        row = conn.execute("SELECT * FROM queue WHERE id=?", (queue_id,)).fetchone()
        if row is None:
            conn.rollback()
            return

        # Check phone
        from phonebroker import adb
        state = adb.get_phone_state()
        if state != "device":
            conn.rollback()
            return

        # Check site limits
        try:
            lease.check_site_limits(conn, platform=row["platform"], priority=row["priority"])
        except lease.SiteLimitExceeded:
            # Skip this entry (leave in queue for next cycle)
            conn.rollback()
            return

        # Create and activate lease
        import uuid
        lease_id = str(uuid.uuid4())
        db.create_lease(
            conn,
            project=row["project"],
            platform=row["platform"],
            operation=row["operation"],
            priority=row["priority"],
            max_duration_s=row["max_duration_s"],
        )
        db.activate_lease(conn, lease_id)
        db.mark_queued_active(conn, queue_id)
        db.record_site_lease_start(
            conn, platform=row["platform"], project=row["project"], priority=row["priority"]
        )
        db.log_action(
            conn,
            lease_id=lease_id,
            project=row["project"],
            platform=row["platform"],
            action="lease_start",
            result="ok",
        )
        conn.commit()

        # Phone reset (outside transaction)
        reset_before_lease()
        logger.info("Acquired lease %s for %s (%s)", lease_id, row["project"], row["platform"])

    except Exception:
        conn.rollback()
        raise


def entrypoint() -> None:
    import uvicorn

    uvicorn.run("phonebroker.main:app", host="127.0.0.1", port=8090, workers=1)


if __name__ == "__main__":
    entrypoint()
