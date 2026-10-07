"""Lease lifecycle: acquire, heartbeat check, revoke, complete."""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from phonebroker import adb, db, queue
from phonebroker.config import load_config
from phonebroker.exceptions import (
    LeaseNotActiveError,
    PhoneUnavailableError,
    PlatformUnavailableError,
    SiteLimitExceeded,
)
from phonebroker.reset import reset_after_lease, reset_before_lease


def check_phone_available() -> None:
    """Raise 503 if phone is not in 'device' state."""
    state = adb.get_phone_state()
    if state != "device":
        raise PhoneUnavailableError(f"Phone state: {state}")


def _check_platform_available(conn: sqlite3.Connection, platform: str) -> None:
    """Raise PlatformUnavailableError if the platform's package is not installed."""
    cfg = load_config()
    pcfg = cfg.platforms.get(platform)
    if pcfg is None:
        return
    eff = db.get_effective_package(conn, platform=platform, manual_package=pcfg.package)
    if eff is None:
        # No binding at all — no package configured, allow (legacy behavior)
        return
    _, available = eff
    if not available:
        raise PlatformUnavailableError(
            f"Platform '{platform}': application not installed"
        )


def check_site_limits(
    conn: sqlite3.Connection, *, platform: str, priority: str
) -> None:
    """Check site limits. Raises SiteLimitExceeded if violated."""
    cfg = load_config()
    limits = cfg.get_limits(platform, priority)

    if not db.check_site_interval(
        conn, platform=platform, priority=priority, min_interval_s=limits.min_interval_s
    ):
        raise SiteLimitExceeded(
            "interval",
            f"Minimum interval {limits.min_interval_s}s not passed for {platform}/{priority}",
        )

    if not db.check_site_daily_limit(
        conn, platform=platform, priority=priority, max_daily=limits.max_daily_leases
    ):
        raise SiteLimitExceeded(
            "daily_limit",
            f"Daily limit {limits.max_daily_leases} reached for {platform}/{priority}",
        )


def request_lease(
    conn: sqlite3.Connection,
    *,
    project: str,
    platform: str,
    operation: str,
    priority: str,
    max_duration_s: int,
) -> tuple[str, str]:
    """Request a lease. Returns (lease_id, status).

    Status is 'active' if acquired immediately, 'waiting' if queued.
    """
    # Validate
    cfg = load_config()
    if platform not in cfg.platforms:
        raise ValueError(f"Unknown platform: {platform}")

    if priority == "interactive" and max_duration_s > 600:
        raise ValueError("interactive: max_duration_s must be <= 600")
    if priority == "background" and max_duration_s > 300:
        raise ValueError("background: max_duration_s must be <= 300")
    if max_duration_s < 1:
        raise ValueError("max_duration_s must be >= 1")

    # Check platform availability (package installed?)
    _check_platform_available(conn, platform)

    # Check phone
    check_phone_available()

    # Check site limits
    check_site_limits(conn, platform=platform, priority=priority)

    # Try to acquire immediately
    active = db.get_active_lease(conn)
    if active is None:
        # No active lease — acquire now
        lease_id = db.create_lease(
            conn,
            project=project,
            platform=platform,
            operation=operation,
            priority=priority,
            max_duration_s=max_duration_s,
        )
        db.activate_lease(conn, lease_id)
        db.record_site_lease_start(
            conn, platform=platform, project=project, priority=priority
        )
        db.log_action(
            conn,
            lease_id=lease_id,
            project=project,
            platform=platform,
            action="lease_start",
            result="ok",
        )
        # Perform phone reset
        reset_before_lease()
        conn.commit()
        return lease_id, "active"
    else:
        # Queue it
        queue_id = db.enqueue(
            conn,
            project=project,
            platform=platform,
            operation=operation,
            priority=priority,
            max_duration_s=max_duration_s,
        )
        conn.commit()
        return queue_id, "waiting"


def complete_lease(conn: sqlite3.Connection, lease_id: str, project: str) -> None:
    """Gracefully complete an active lease."""
    lease = db.get_lease(conn, lease_id)
    if lease is None:
        raise ValueError(f"Lease {lease_id} not found")
    if lease["status"] != "active":
        raise LeaseNotActiveError(f"Lease {lease_id} is {lease['status']}")
    if lease["project"] != project:
        raise PermissionError("Not your lease")

    db.end_lease(conn, lease_id, "completed")
    # Find and close the site_lease record
    _close_site_lease(conn, lease_id)
    db.log_action(
        conn,
        lease_id=lease_id,
        project=project,
        platform=lease["platform"],
        action="lease_end",
        result="completed",
    )
    queue.update_starvation_counter(conn, lease["priority"])
    conn.commit()

    # Phone reset (after commit so the lease is no longer 'active' in DB)
    reset_after_lease()


def revoke_lease(conn: sqlite3.Connection, lease_id: str, reason: str) -> None:
    """Revoke a lease (timeout, no heartbeat, maintenance)."""
    lease = db.get_lease(conn, lease_id)
    if lease is None or lease["status"] != "active":
        return

    db.end_lease(conn, lease_id, "revoked")
    _close_site_lease(conn, lease_id)
    db.log_action(
        conn,
        lease_id=lease_id,
        project=lease["project"],
        platform=lease["platform"],
        action="lease_revoke",
        result=reason,
    )
    queue.update_starvation_counter(conn, lease["priority"])
    conn.commit()

    reset_after_lease()


def _close_site_lease(conn: sqlite3.Connection, lease_id: str) -> None:
    """Close the most recent open site_lease for this lease's platform/project."""
    lease = db.get_lease(conn, lease_id)
    if lease is None:
        return
    row = conn.execute(
        "SELECT id FROM site_leases WHERE platform=? AND project=? "
        "AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
        (lease["platform"], lease["project"]),
    ).fetchone()
    if row:
        db.record_site_lease_end(conn, row["id"])


def check_timeouts(conn: sqlite3.Connection) -> None:
    """Background task: check for expired leases and missed heartbeats."""
    now = datetime.now(UTC)
    active = db.get_active_lease(conn)
    if active is None:
        return

    # Check max duration
    if active["expires_at"]:
        expires = datetime.fromisoformat(active["expires_at"])
        if now > expires:
            revoke_lease(conn, active["id"], "max_duration_exceeded")
            return

    # Check heartbeat
    if active["last_heartbeat"]:
        last_hb = datetime.fromisoformat(active["last_heartbeat"])
        timeout_s = load_config().heartbeat_timeout_s
        if now - last_hb > timedelta(seconds=timeout_s):
            revoke_lease(conn, active["id"], "heartbeat_timeout")
