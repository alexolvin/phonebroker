"""Tests for SQLite database layer."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from phonebroker import db


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as td:
        connection = db.get_connection(Path(td) / "test.db")
        db.init_db(connection)
        yield connection
        connection.close()


def test_init_db_creates_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "leases" in tables
    assert "queue" in tables
    assert "journal" in tables
    assert "site_leases" in tables
    assert "counters" in tables


def test_unique_active_lease_index(conn):
    """Only one active lease allowed at a time."""
    db.create_lease(
        conn, project="p1", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    conn.commit()

    lease_id = db.create_lease(
        conn, project="p2", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    db.activate_lease(conn, lease_id)
    conn.commit()

    # Second activation should fail
    lease_id2 = db.create_lease(
        conn, project="p3", platform="vinted", operation="test",
        priority="background", max_duration_s=60,
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.activate_lease(conn, lease_id2)
        conn.commit()
    conn.rollback()


def test_queue_fifo(conn):
    db.enqueue(conn, project="p1", platform="vinted", operation="a",
               priority="background", max_duration_s=60)
    db.enqueue(conn, project="p2", platform="vinted", operation="b",
               priority="background", max_duration_s=60)
    conn.commit()

    row = db.dequeue_next(conn)
    assert row is not None
    assert row["operation"] == "a"  # FIFO


def test_queue_priority(conn):
    db.enqueue(conn, project="p1", platform="vinted", operation="bg",
               priority="background", max_duration_s=60)
    db.enqueue(conn, project="p2", platform="vinted", operation="int",
               priority="interactive", max_duration_s=60)
    conn.commit()

    row = db.dequeue_next(conn)
    assert row["operation"] == "int"  # interactive first


def test_counters(conn):
    assert db.get_counter(conn, "consecutive_interactive") == 0
    db.set_counter(conn, "consecutive_interactive", 3)
    conn.commit()
    assert db.get_counter(conn, "consecutive_interactive") == 3


def test_journal(conn):
    db.log_action(conn, lease_id="l1", project="p", platform="vinted",
                  action="test", result="ok")
    conn.commit()
    entries = db.get_lease_journal(conn, "l1")
    assert len(entries) == 1
    assert entries[0]["action"] == "test"


def test_site_limits(conn):
    # Initially no constraints (no ended leases)
    assert db.check_site_interval(conn, platform="vinted", priority="background", min_interval_s=300)
    assert db.check_site_daily_limit(conn, platform="vinted", priority="background", max_daily=10)

    # Record and end a lease
    sid = db.record_site_lease_start(conn, platform="vinted", project="p", priority="background")
    conn.commit()
    db.record_site_lease_end(conn, sid)
    conn.commit()

    # Interval NOT passed (just ended, < 300s ago)
    assert not db.check_site_interval(conn, platform="vinted", priority="background", min_interval_s=300)

    # Zero interval always passes
    assert db.check_site_interval(conn, platform="vinted", priority="background", min_interval_s=0)

    # Interactive has 0 interval by default
    assert db.check_site_interval(conn, platform="vinted", priority="interactive", min_interval_s=0)

    # Daily limit: 1 lease recorded, limit 10 → OK
    assert db.check_site_daily_limit(conn, platform="vinted", priority="background", max_daily=10)

    # Daily limit: 1 lease recorded, limit 1 → exceeded
    assert not db.check_site_daily_limit(conn, platform="vinted", priority="background", max_daily=1)
