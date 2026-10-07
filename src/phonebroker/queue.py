"""Queue management — priority, FIFO, starvation protection.

The queue is processed by a background task (in main.py) that runs every
`check_interval_s` seconds. It selects the next entry and attempts to acquire.
"""

import sqlite3

from phonebroker import db


def try_acquire_next(conn: sqlite3.Connection) -> str | None:
    """Try to acquire the next lease from the queue.

    Returns the lease_id if acquired, None if no acquisition happened.
    Must be called with proper locking (BEGIN IMMEDIATE).
    """
    # Check starvation protection
    consecutive = db.get_counter(conn, "consecutive_interactive")
    force_background = (
        consecutive >= _starvation_threshold() and db.has_background_in_queue(conn)
    )

    # Select next candidate
    if force_background:
        row = conn.execute(
            "SELECT * FROM queue WHERE status='waiting' AND priority='background' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM queue WHERE status='waiting' "
            "ORDER BY CASE priority WHEN 'interactive' THEN 0 ELSE 1 END, "
            "created_at ASC LIMIT 1"
        ).fetchone()

    if row is None:
        return None

    return row["id"]


def _starvation_threshold() -> int:
    from phonebroker.config import load_config
    return load_config().starvation_threshold


def update_starvation_counter(conn: sqlite3.Connection, priority: str) -> None:
    """Update the consecutive interactive counter after a lease completes."""
    if priority == "interactive":
        current = db.get_counter(conn, "consecutive_interactive")
        db.set_counter(conn, "consecutive_interactive", current + 1)
    else:
        db.set_counter(conn, "consecutive_interactive", 0)
