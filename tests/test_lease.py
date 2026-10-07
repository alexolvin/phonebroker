"""Tests for lease lifecycle with fake ADB."""

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from phonebroker import db, lease
from phonebroker.exceptions import PhoneUnavailableError, SiteLimitExceeded


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as td:
        connection = db.get_connection(Path(td) / "test.db")
        db.init_db(connection)
        yield connection
        connection.close()


@patch("phonebroker.lease.adb")
@patch("phonebroker.lease.reset_before_lease")
@patch("phonebroker.lease.reset_after_lease")
def test_revoke_heartbeat_timeout(mock_reset_after, mock_reset_before, mock_adb, conn):
    """Lease revoked after heartbeat timeout."""
    mock_adb.get_phone_state.return_value = "device"

    # Create and activate a lease
    lease_id = db.create_lease(
        conn, project="p1", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    db.activate_lease(conn, lease_id)
    conn.commit()

    # Rewind heartbeat to be past timeout (default 60s)
    old_hb = (datetime.now(UTC) - timedelta(seconds=61)).isoformat()
    conn.execute("UPDATE leases SET last_heartbeat=? WHERE id=?", (old_hb, lease_id))
    conn.commit()

    # Check timeouts
    lease.check_timeouts(conn)

    row = db.get_lease(conn, lease_id)
    assert row["status"] == "revoked"
    mock_reset_after.assert_called_once()


@patch("phonebroker.lease.adb")
@patch("phonebroker.lease.reset_before_lease")
@patch("phonebroker.lease.reset_after_lease")
def test_revoke_max_duration(mock_reset_after, mock_reset_before, mock_adb, conn):
    """Lease revoked after max_duration_s expires."""
    mock_adb.get_phone_state.return_value = "device"

    lease_id = db.create_lease(
        conn, project="p1", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    db.activate_lease(conn, lease_id)
    conn.commit()

    # Rewind expires_at to the past
    old_exp = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE leases SET expires_at=? WHERE id=?", (old_exp, lease_id))
    conn.commit()

    lease.check_timeouts(conn)

    row = db.get_lease(conn, lease_id)
    assert row["status"] == "revoked"


@patch("phonebroker.lease.adb")
def test_request_lease_phone_unavailable(mock_adb, conn):
    """Request rejected with PhoneUnavailableError if phone not device."""
    mock_adb.get_phone_state.return_value = "offline"
    with pytest.raises(PhoneUnavailableError):
        lease.request_lease(
            conn, project="p1", platform="vinted", operation="test",
            priority="background", max_duration_s=60,
        )


@patch("phonebroker.lease.adb")
@patch("phonebroker.lease.reset_before_lease")
@patch("phonebroker.lease.reset_after_lease")
def test_complete_lease(mock_reset_after, mock_reset_before, mock_adb, conn):
    """Graceful completion ends lease and resets phone."""
    mock_adb.get_phone_state.return_value = "device"

    lease_id, status = lease.request_lease(
        conn, project="p1", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    assert status == "active"

    lease.complete_lease(conn, lease_id, "p1")

    row = db.get_lease(conn, lease_id)
    assert row["status"] == "completed"
    mock_reset_after.assert_called_once()


@patch("phonebroker.lease.adb")
@patch("phonebroker.lease.reset_before_lease")
@patch("phonebroker.lease.reset_after_lease")
def test_site_limit_interval(mock_reset_after, mock_reset_before, mock_adb, conn):
    """Site limit: interval rejects too-soon lease."""
    mock_adb.get_phone_state.return_value = "device"

    # First lease: start and end
    lease_id, _ = lease.request_lease(
        conn, project="p1", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    lease.complete_lease(conn, lease_id, "p1")

    # Second lease immediately: should fail (interval 300s for background)
    with pytest.raises(SiteLimitExceeded) as exc_info:
        lease.request_lease(
            conn, project="p1", platform="vinted", operation="test2",
            priority="background", max_duration_s=60,
        )
    assert "interval" in str(exc_info.value)
