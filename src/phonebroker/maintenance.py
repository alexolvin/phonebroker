"""Maintenance mode — owner exclusive access.

State is persisted in SQLite (maintenance table) so a broker restart
keeps an active session (queue stays paused) and always records
maintenance_end.

When active:
- Active lease is revoked immediately with reset
- Queue is paused (no new acquisitions)
- All project requests get 423
- IME set to system default
"""

import sqlite3
from datetime import UTC, datetime, timedelta

from phonebroker import db, lease
from phonebroker.reset import reset_after_lease

MAINTENANCE_TIMEOUT_S = 60

_last_sync_result: dict = {}


def _get_state(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM maintenance WHERE id=1").fetchone()


def _set_state(
    conn: sqlite3.Connection,
    *,
    active: bool,
    started_at: str | None,
    renew_deadline: str | None,
) -> None:
    conn.execute(
        "INSERT INTO maintenance (id, active, started_at, renew_deadline) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET active=excluded.active, "
        "started_at=excluded.started_at, renew_deadline=excluded.renew_deadline",
        (int(active), started_at, renew_deadline),
    )


def is_active(conn: sqlite3.Connection) -> bool:
    row = _get_state(conn)
    return bool(row and row["active"])


def start(conn: sqlite3.Connection) -> None:
    """Start maintenance mode. Revokes active lease, pauses queue."""
    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=MAINTENANCE_TIMEOUT_S)
    _set_state(
        conn,
        active=True,
        started_at=now.isoformat(),
        renew_deadline=deadline.isoformat(),
    )

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
    if not is_active(conn):
        return
    deadline = datetime.now(UTC) + timedelta(seconds=MAINTENANCE_TIMEOUT_S)
    conn.execute(
        "UPDATE maintenance SET renew_deadline=? WHERE id=1",
        (deadline.isoformat(),),
    )
    conn.commit()


def get_last_sync_result() -> dict:
    """Return the result of the last package sync."""
    return _last_sync_result


def end(conn: sqlite3.Connection, reason: str) -> dict:
    """End maintenance mode. Resets phone, syncs packages, resumes queue.

    Returns the sync result dict.
    """
    global _last_sync_result

    if not is_active(conn):
        return _last_sync_result

    _set_state(conn, active=False, started_at=None, renew_deadline=None)

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
    row = _get_state(conn)
    if not row or not row["active"] or row["renew_deadline"] is None:
        return
    if datetime.fromisoformat(row["renew_deadline"]) < datetime.now(UTC):
        end(conn, "renew_timeout")


def on_startup(conn: sqlite3.Connection) -> None:
    """Restore maintenance state after broker restart.

    Active with unexpired renew deadline → maintenance continues (queue
    stays paused). Deadline expired → end with result=broker_restart.
    """
    row = _get_state(conn)
    if not row or not row["active"]:
        return
    if row["renew_deadline"] is not None and (
        datetime.fromisoformat(row["renew_deadline"]) > datetime.now(UTC)
    ):
        return
    end(conn, "broker_restart")
