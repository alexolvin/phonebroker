"""Tests for maintenance mode (SQLite-persisted state)."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from phonebroker import db, maintenance


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as td:
        connection = db.get_connection(Path(td) / "test.db")
        db.init_db(connection)
        yield connection
        connection.close()


@pytest.fixture(autouse=True)
def _mock_sync():
    with (
        patch("phonebroker.packages.sync_packages", return_value={"bound": [], "unavailable": [], "unassigned": [], "changed": False}),
        patch("phonebroker.lease.reset_after_lease"),
    ):
        yield


def _set_renew_deadline(conn, dt: datetime) -> None:
    conn.execute(
        "UPDATE maintenance SET renew_deadline=? WHERE id=1",
        (dt.isoformat(),),
    )
    conn.commit()


@patch("phonebroker.maintenance.reset_after_lease")
@patch("phonebroker.lease.adb")
def test_start_revokes_active_lease(mock_adb, mock_reset, conn):
    """Maintenance start immediately revokes active lease."""
    mock_adb.get_phone_state.return_value = "device"

    # Create active lease
    lease_id = db.create_lease(
        conn, project="p1", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    db.activate_lease(conn, lease_id)
    conn.commit()

    # Start maintenance
    maintenance.start(conn)

    assert maintenance.is_active(conn)
    row = db.get_lease(conn, lease_id)
    assert row["status"] == "revoked"

    # Check journal
    rows = conn.execute(
        "SELECT * FROM journal WHERE action='maintenance_start'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "ok"


@patch("phonebroker.maintenance.reset_after_lease")
def test_end_by_owner(mock_reset, conn):
    """End by owner records result=end_by_owner."""
    maintenance.start(conn)
    maintenance.end(conn, "end_by_owner")

    assert not maintenance.is_active(conn)
    rows = conn.execute(
        "SELECT * FROM journal WHERE action='maintenance_end'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "end_by_owner"


@patch("phonebroker.maintenance.reset_after_lease")
def test_renew_timeout(mock_reset, conn):
    """Auto-end after renew deadline passes."""
    maintenance.start(conn)

    # Expire the renew deadline
    _set_renew_deadline(conn, datetime.now(UTC) - timedelta(seconds=1))

    maintenance.check_timeout(conn)

    assert not maintenance.is_active(conn)
    rows = conn.execute(
        "SELECT * FROM journal WHERE action='maintenance_end'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "renew_timeout"


@patch("phonebroker.maintenance.reset_after_lease")
def test_ssh_disconnect(mock_reset, conn):
    """End via ssh_disconnect records correct reason."""
    maintenance.start(conn)
    maintenance.end(conn, "ssh_disconnect")

    rows = conn.execute(
        "SELECT * FROM journal WHERE action='maintenance_end'"
    ).fetchall()
    assert rows[0]["result"] == "ssh_disconnect"


@patch("phonebroker.maintenance.reset_after_lease")
def test_startup_continues_active_maintenance(mock_reset, conn):
    """Broker restart with unexpired renew deadline keeps maintenance active."""
    maintenance.start(conn)

    # Simulate broker restart: state is in the DB, new process calls on_startup
    maintenance.on_startup(conn)

    assert maintenance.is_active(conn)
    rows = conn.execute(
        "SELECT * FROM journal WHERE action='maintenance_end'"
    ).fetchall()
    assert len(rows) == 0


@patch("phonebroker.maintenance.reset_after_lease")
def test_startup_expired_renew_ends_with_broker_restart(mock_reset, conn):
    """Broker restart with expired renew deadline ends maintenance."""
    maintenance.start(conn)

    _set_renew_deadline(conn, datetime.now(UTC) - timedelta(seconds=1))

    maintenance.on_startup(conn)

    assert not maintenance.is_active(conn)
    rows = conn.execute(
        "SELECT * FROM journal WHERE action='maintenance_end'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "broker_restart"
