"""SQLite database layer for PhoneBroker.

WAL mode for concurrency. All writes use BEGIN IMMEDIATE to prevent
race conditions on the single active lease constraint.
"""

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from phonebroker.config import get_data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leases (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    platform TEXT NOT NULL,
    operation TEXT NOT NULL,
    priority TEXT NOT NULL,
    max_duration_s INTEGER NOT NULL,
    acquired_at TEXT,
    last_heartbeat TEXT,
    expires_at TEXT,
    ended_at TEXT,
    status TEXT NOT NULL,
    last_package TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_lease
    ON leases(status) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_leases_project ON leases(project, status);

CREATE TABLE IF NOT EXISTS queue (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    platform TEXT NOT NULL,
    operation TEXT NOT NULL,
    priority TEXT NOT NULL,
    max_duration_s INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting'
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lease_id TEXT,
    project TEXT NOT NULL,
    platform TEXT NOT NULL,
    action TEXT NOT NULL,
    duration_ms INTEGER,
    result TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_journal_lease ON journal(lease_id);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal(created_at);

CREATE TABLE IF NOT EXISTS site_leases (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    project TEXT NOT NULL,
    priority TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_site_platform ON site_leases(platform, priority, ended_at);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS platform_packages (
    platform TEXT PRIMARY KEY,
    package TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    available INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unassigned_packages (
    package TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode."""
    if db_path is None:
        db_path = get_data_dir() / "phonebroker.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript(_SCHEMA)
    conn.commit()


# ─── Leases ───────────────────────────────────────────────────────────────


def create_lease(
    conn: sqlite3.Connection,
    *,
    project: str,
    platform: str,
    operation: str,
    priority: str,
    max_duration_s: int,
) -> str:
    """Create a lease record. Caller must be inside BEGIN IMMEDIATE."""
    lease_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO leases (id, project, platform, operation, priority, "
        "max_duration_s, status) VALUES (?, ?, ?, ?, ?, ?, 'waiting')",
        (lease_id, project, platform, operation, priority, max_duration_s),
    )
    return lease_id


def activate_lease(conn: sqlite3.Connection, lease_id: str) -> None:
    """Activate a lease. Raises sqlite3.IntegrityError if another is active."""
    now = _now()
    conn.execute(
        "UPDATE leases SET status='active', acquired_at=?, last_heartbeat=?, "
        "expires_at=datetime(?, '+' || ? || ' seconds') WHERE id=?",
        (now, now, now, "(SELECT max_duration_s FROM leases WHERE id=?)".replace("?", lease_id), lease_id),
    )
    # Simpler: compute expires_at in Python
    row = conn.execute(
        "SELECT max_duration_s FROM leases WHERE id=?", (lease_id,)
    ).fetchone()
    if row:
        from datetime import timedelta
        expires = datetime.fromisoformat(now) + timedelta(seconds=row["max_duration_s"])
        conn.execute(
            "UPDATE leases SET expires_at=? WHERE id=?",
            (expires.isoformat(), lease_id),
        )


def get_active_lease(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM leases WHERE status='active'"
    ).fetchone()


def get_lease(conn: sqlite3.Connection, lease_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone()


def get_lease_by_project(conn: sqlite3.Connection, project: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM leases WHERE project=? AND status IN ('active','waiting') "
        "ORDER BY acquired_at DESC, created_at DESC LIMIT 1",
        (project,),
    ).fetchone()


def heartbeat_lease(conn: sqlite3.Connection, lease_id: str) -> None:
    conn.execute(
        "UPDATE leases SET last_heartbeat=? WHERE id=? AND status='active'",
        (_now(), lease_id),
    )


def end_lease(conn: sqlite3.Connection, lease_id: str, status: str) -> None:
    conn.execute(
        "UPDATE leases SET status=?, ended_at=? WHERE id=?",
        (status, _now(), lease_id),
    )


def set_lease_package(conn: sqlite3.Connection, lease_id: str, package: str) -> None:
    conn.execute(
        "UPDATE leases SET last_package=? WHERE id=?", (package, lease_id)
    )


def get_project_leases(conn: sqlite3.Connection, project: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM leases WHERE project=? ORDER BY acquired_at DESC LIMIT 50",
        (project,),
    ).fetchall()


# ─── Queue ────────────────────────────────────────────────────────────────


def enqueue(
    conn: sqlite3.Connection,
    *,
    project: str,
    platform: str,
    operation: str,
    priority: str,
    max_duration_s: int,
) -> str:
    """Add a request to the queue. Returns the queue entry id."""
    entry_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO queue (id, project, platform, operation, priority, "
        "max_duration_s, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entry_id, project, platform, operation, priority, max_duration_s, _now()),
    )
    return entry_id


def dequeue_next(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Select the next queue entry respecting priority and FIFO.

    Must be called inside BEGIN IMMEDIATE.
    """
    row = conn.execute(
        "SELECT * FROM queue WHERE status='waiting' "
        "ORDER BY CASE priority WHEN 'interactive' THEN 0 ELSE 1 END, "
        "created_at ASC LIMIT 1"
    ).fetchone()
    return row


def mark_queued_active(conn: sqlite3.Connection, queue_id: str) -> None:
    conn.execute("UPDATE queue SET status='active' WHERE id=?", (queue_id,))


def remove_from_queue(conn: sqlite3.Connection, queue_id: str) -> None:
    conn.execute("DELETE FROM queue WHERE id=?", (queue_id,))


def get_queue_size(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as n FROM queue WHERE status='waiting'"
    ).fetchone()
    return row["n"] if row else 0


def has_background_in_queue(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM queue WHERE status='waiting' AND priority='background' LIMIT 1"
    ).fetchone()
    return row is not None


# ─── Counters (starvation protection) ────────────────────────────────────


def get_counter(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute(
        "SELECT value FROM counters WHERE name=?", (name,)
    ).fetchone()
    return row["value"] if row else 0


def set_counter(conn: sqlite3.Connection, name: str, value: int) -> None:
    conn.execute(
        "INSERT INTO counters (name, value) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
        (name, value),
    )


# ─── Journal ─────────────────────────────────────────────────────────────


def log_action(
    conn: sqlite3.Connection,
    *,
    lease_id: str | None,
    project: str,
    platform: str,
    action: str,
    duration_ms: int | None = None,
    result: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO journal (lease_id, project, platform, action, duration_ms, "
        "result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (lease_id, project, platform, action, duration_ms, result, _now()),
    )


def get_lease_journal(conn: sqlite3.Connection, lease_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM journal WHERE lease_id=? ORDER BY created_at", (lease_id,)
    ).fetchall()


def prune_journal(conn: sqlite3.Connection, older_than: str) -> int:
    """Delete journal entries older than the given ISO timestamp. Returns count."""
    cur = conn.execute("DELETE FROM journal WHERE created_at < ?", (older_than,))
    return cur.rowcount


# ─── Site limits ─────────────────────────────────────────────────────────


def record_site_lease_start(
    conn: sqlite3.Connection, *, platform: str, project: str, priority: str
) -> str:
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO site_leases (id, platform, project, priority, started_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, platform, project, priority, _now()),
    )
    return sid


def record_site_lease_end(conn: sqlite3.Connection, site_lease_id: str) -> None:
    conn.execute(
        "UPDATE site_leases SET ended_at=? WHERE id=?", (_now(), site_lease_id)
    )


def check_site_interval(
    conn: sqlite3.Connection, *, platform: str, priority: str, min_interval_s: int
) -> bool:
    """Returns True if the interval has passed (OK to proceed)."""
    if min_interval_s <= 0:
        return True
    row = conn.execute(
        "SELECT MAX(ended_at) as last_end FROM site_leases "
        "WHERE platform=? AND priority=? AND ended_at IS NOT NULL",
        (platform, priority),
    ).fetchone()
    if not row or row["last_end"] is None:
        return True
    from datetime import timedelta
    last_end = datetime.fromisoformat(row["last_end"])
    return datetime.now(UTC) - last_end >= timedelta(seconds=min_interval_s)


def check_site_daily_limit(
    conn: sqlite3.Connection, *, platform: str, priority: str, max_daily: int
) -> bool:
    """Returns True if the daily limit has NOT been reached."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) as n FROM site_leases "
        "WHERE platform=? AND priority=? AND date(started_at)=?",
        (platform, priority, today),
    ).fetchone()
    return (row["n"] if row else 0) < max_daily


# ─── Platform packages (auto/manual bindings + availability) ──────────────


def upsert_platform_package(
    conn: sqlite3.Connection,
    *,
    platform: str,
    package: str,
    source: str,
    available: bool,
) -> None:
    conn.execute(
        "INSERT INTO platform_packages (platform, package, source, available, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(platform) DO UPDATE SET "
        "package=excluded.package, source=excluded.source, "
        "available=excluded.available, updated_at=excluded.updated_at",
        (platform, package, source, int(available), _now()),
    )


def get_platform_package(conn: sqlite3.Connection, platform: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM platform_packages WHERE platform=?", (platform,)
    ).fetchone()


def get_all_platform_packages(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM platform_packages ORDER BY platform").fetchall()


def get_effective_package(
    conn: sqlite3.Connection, *, platform: str, manual_package: str
) -> tuple[str, bool] | None:
    """Return (package, available) for a platform, respecting priority.

    Manual binding (from /etc config) takes priority over auto (SQLite).
    Returns None if no binding exists.
    """
    if manual_package:
        row = get_platform_package(conn, platform)
        available = row["available"] if row else True
        return manual_package, bool(available)
    row = get_platform_package(conn, platform)
    if row:
        return row["package"], bool(row["available"])
    return None


def set_unassigned_packages(conn: sqlite3.Connection, packages: list[str]) -> None:
    """Replace the unassigned packages list."""
    now = _now()
    conn.execute("DELETE FROM unassigned_packages")
    for pkg in packages:
        existing = conn.execute(
            "SELECT first_seen FROM unassigned_packages WHERE package=?", (pkg,)
        ).fetchone()
        # Since we just deleted all, just insert
        conn.execute(
            "INSERT INTO unassigned_packages (package, first_seen, last_seen) VALUES (?, ?, ?)",
            (pkg, now, now),
        )


def get_unassigned_packages(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT package FROM unassigned_packages ORDER BY package"
    ).fetchall()
    return [r["package"] for r in rows]
