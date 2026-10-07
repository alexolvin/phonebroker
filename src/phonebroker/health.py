"""Phone health check + platform status."""

import sqlite3

from phonebroker import adb, db
from phonebroker.packages import get_platform_status


def get_health(conn: sqlite3.Connection | None = None) -> dict:
    """Return broker + phone health status + platform availability."""
    phone_state = adb.get_phone_state()
    result: dict = {
        "broker": "ok",
        "phone": phone_state,
        "phone_available": phone_state == "device",
    }

    if conn is not None:
        result["platforms"] = get_platform_status(conn)
        result["unassigned"] = db.get_unassigned_packages(conn)

    return result
