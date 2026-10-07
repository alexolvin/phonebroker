"""Maintenance mode — owner exclusive access.

When active:
- Active lease is revoked immediately with reset
- Queue is paused (no new acquisitions)
- All project requests get 423
- IME set to system default
"""

import sqlite3
from datetime import UTC, datetime, timedelta

from phonebroker import db, lease
from phonebroker.config import load_config
from phonebroker.reset import reset_after_lease

# In-memory state (single worker, no persistence needed)
_maintenance_active = False
_maintenance_started_at: datetime | None = None
_maintenance_last_renew: datetime | None = None
_last_sync_result: dict = {}

MAINTENANCE_TIMEOUT_S = 60


def is_active() -> bool:
    return _maintenance_active


def start(conn: sqlite3.Connection) -> None:
    """Start maintenance mode. Revokes active lease, pauses queue."""
    global _maintenance_active, _maintenance_started_at, _maintenance_last_renew

    now = datetime.now(UTC)
    _maintenance_active = True
    _maintenance_started_at = now
    _maintenance_last_renew = now

    # Revoke active lease if any
    active = db.get_active_lease(conn)
    if active is not None:
        lease.revoke_lease(conn, active["id"], "maintenance_start")

    db.log_action(
        conn,
        lease_id=None,
        project="owner",
        platform="maintenance",
        action="maintenance_start",
        result="ok",
    )
    conn.commit()


def renew(conn: sqlite3.Connection) -> None:
    """Renew maintenance mode (prevents auto-timeout)."""
    global _maintenance_last_renew
    if not _maintenance_active:
        return
    _maintenance_last_renew = datetime.now(UTC)


def get_last_sync_result() -> dict:
    """Return the result of the last package sync."""
    return _last_sync_result


def end(conn: sqlite3.Connection, reason: str) -> dict:
    """End maintenance mode. Resets phone, syncs packages, resumes queue.

    Returns the sync result dict.
    """
    global _maintenance_active, _maintenance_started_at, _maintenance_last_renew
    global _last_sync_result

    if not _maintenance_active:
        return _last_sync_result

    _maintenance_active = False
    _maintenance_started_at = None
    _maintenance_last_renew = None

    # Phone reset
    reset_after_lease()

    db.log_action(
        conn,
        lease_id=None,
        project="owner",
        platform="maintenance",
        action="maintenance_end",
        result=reason,
    )
    conn.commit()

    # Package sync (after reset, so phone is in known state)
    from phonebroker.packages import sync_packages

    _last_sync_result = sync_packages(conn)

    return _last_sync_result


def check_timeout(conn: sqlite3.Connection) -> None:
    """Auto-end maintenance if no renew within 60s."""
    if not _maintenance_active or _maintenance_last_renew is None:
        return
    elapsed = datetime.now(UTC) - _maintenance_last_renew
    if elapsed > timedelta(seconds=MAINTENANCE_TIMEOUT_S):
        end(conn, "renew_timeout")
