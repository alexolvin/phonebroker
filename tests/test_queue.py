"""Tests for queue priority, FIFO, and starvation protection."""

import tempfile
from pathlib import Path

import pytest

from phonebroker import db, queue


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as td:
        connection = db.get_connection(Path(td) / "test.db")
        db.init_db(connection)
        yield connection
        connection.close()


def test_fifo_within_class(conn):
    db.enqueue(conn, project="p1", platform="vinted", operation="first",
               priority="background", max_duration_s=60)
    db.enqueue(conn, project="p2", platform="vinted", operation="second",
               priority="background", max_duration_s=60)
    conn.commit()

    row = queue.try_acquire_next(conn)
    entry = conn.execute("SELECT * FROM queue WHERE id=?", (row,)).fetchone()
    assert entry["operation"] == "first"


def test_interactive_beats_background(conn):
    db.enqueue(conn, project="p1", platform="vinted", operation="bg",
               priority="background", max_duration_s=60)
    db.enqueue(conn, project="p2", platform="vinted", operation="int",
               priority="interactive", max_duration_s=60)
    conn.commit()

    row = queue.try_acquire_next(conn)
    entry = conn.execute("SELECT * FROM queue WHERE id=?", (row,)).fetchone()
    assert entry["operation"] == "int"


def test_starvation_protection(conn):
    """After 5 consecutive interactive, background is forced."""
    # Simulate 5 consecutive interactive
    db.set_counter(conn, "consecutive_interactive", 5)
    conn.commit()

    # Add both types to queue
    db.enqueue(conn, project="p1", platform="vinted", operation="int6",
               priority="interactive", max_duration_s=60)
    db.enqueue(conn, project="p2", platform="vinted", operation="bg1",
               priority="background", max_duration_s=60)
    conn.commit()

    # Should pick background (starvation protection)
    row = queue.try_acquire_next(conn)
    entry = conn.execute("SELECT * FROM queue WHERE id=?", (row,)).fetchone()
    assert entry["operation"] == "bg1"


def test_starvation_counter_reset_on_background(conn):
    db.set_counter(conn, "consecutive_interactive", 5)
    conn.commit()

    queue.update_starvation_counter(conn, "background")
    assert db.get_counter(conn, "consecutive_interactive") == 0


def test_starvation_counter_increment_on_interactive(conn):
    db.set_counter(conn, "consecutive_interactive", 2)
    conn.commit()

    queue.update_starvation_counter(conn, "interactive")
    assert db.get_counter(conn, "consecutive_interactive") == 3


def test_empty_queue_returns_none(conn):
    assert queue.try_acquire_next(conn) is None
