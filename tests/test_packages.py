"""Unit tests for package synchronization logic."""

import sqlite3
from unittest.mock import patch

import pytest

from phonebroker import db
from phonebroker.config import BrokerConfig, PlatformConfig
from phonebroker.packages import sync_packages


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def make_config():
    """Factory for creating test configs with specific platforms."""

    def _make(platforms: dict[str, dict]):
        return BrokerConfig(
            adb={"serial": "TESTSERIAL"},
            platforms={
                name: PlatformConfig(**params) for name, params in platforms.items()
            },
        )

    return _make


def _run_sync(conn, installed: list[str], config: BrokerConfig) -> dict:
    """Run sync with mocked ADB and config."""
    with (
        patch("phonebroker.packages.list_all_packages", return_value=installed),
        patch("phonebroker.packages.list_third_party_packages", return_value=installed),
        patch("phonebroker.packages.load_config", return_value=config),
    ):
        return sync_packages(conn)


class TestAutoBind:
    def test_keyword_match_binds(self, conn, make_config):
        cfg = make_config({
            "olx_pl": {"package": "", "keywords": ["olx", "tablica"]},
        })
        result = _run_sync(conn, ["pl.tablica", "com.other.app"], cfg)

        assert result["bound"] == ["olx_pl \u2192 pl.tablica"]
        assert result["changed"] is True
        row = db.get_platform_package(conn, "olx_pl")
        assert row["package"] == "pl.tablica"
        assert row["source"] == "auto"
        assert row["available"] == 1

    def test_no_keyword_match_no_bind(self, conn, make_config):
        cfg = make_config({
            "vinted": {"package": "", "keywords": ["vinted"]},
        })
        result = _run_sync(conn, ["com.other.app"], cfg)

        assert result["bound"] == []
        assert db.get_platform_package(conn, "vinted") is None

    def test_multiple_keywords_first_match_wins(self, conn, make_config):
        cfg = make_config({
            "fb": {"package": "", "keywords": ["facebook", "fb", "messenger"]},
        })
        result = _run_sync(conn, ["com.facebook.lite"], cfg)

        assert result["bound"] == ["fb \u2192 com.facebook.lite"]


class TestUnavailability:
    def test_removed_package_marks_unavailable(self, conn, make_config):
        # Pre-bind a package
        db.upsert_platform_package(
            conn, platform="vinted", package="com.vinted.app",
            source="auto", available=True,
        )
        conn.commit()

        cfg = make_config({
            "vinted": {"package": "", "keywords": ["vinted"]},
        })
        # Package no longer installed
        result = _run_sync(conn, ["com.other.app"], cfg)

        assert "vinted" in result["unavailable"]
        row = db.get_platform_package(conn, "vinted")
        assert row["available"] == 0

    def test_still_installed_stays_available(self, conn, make_config):
        db.upsert_platform_package(
            conn, platform="vinted", package="com.vinted.app",
            source="auto", available=True,
        )
        conn.commit()

        cfg = make_config({
            "vinted": {"package": "", "keywords": ["vinted"]},
        })
        result = _run_sync(conn, ["com.vinted.app"], cfg)

        assert result["unavailable"] == []
        row = db.get_platform_package(conn, "vinted")
        assert row["available"] == 1


class TestUnassigned:
    def test_unassigned_packages_tracked(self, conn, make_config):
        cfg = make_config({
            "vinted": {"package": "", "keywords": ["vinted"]},
        })
        result = _run_sync(conn, ["com.vinted.app", "com.random.game"], cfg)

        assert "com.random.game" in result["unassigned"]
        assert "com.vinted.app" not in result["unassigned"]
        assert db.get_unassigned_packages(conn) == ["com.random.game"]

    def test_all_bound_no_unassigned(self, conn, make_config):
        cfg = make_config({
            "vinted": {"package": "", "keywords": ["vinted"]},
        })
        result = _run_sync(conn, ["com.vinted.app"], cfg)

        assert result["unassigned"] == []
        assert db.get_unassigned_packages(conn) == []


class TestManualPriority:
    def test_manual_binding_overrides_auto(self, conn, make_config):
        # Auto-binding exists
        db.upsert_platform_package(
            conn, platform="olx_pl", package="pl.tablica",
            source="auto", available=True,
        )
        conn.commit()

        # Manual binding in config (simulates /etc/phonebroker/broker.yaml)
        cfg = make_config({
            "olx_pl": {"package": "pl.olx.manual", "keywords": ["olx", "tablica"]},
        })
        result = _run_sync(conn, ["pl.olx.manual", "pl.tablica"], cfg)

        # Manual binding wins
        row = db.get_platform_package(conn, "olx_pl")
        assert row["package"] == "pl.olx.manual"
        assert row["source"] == "manual"
        assert row["available"] == 1

    def test_manual_binding_unavailable(self, conn, make_config):
        cfg = make_config({
            "vinted": {"package": "com.vinted.app", "keywords": ["vinted"]},
        })
        # Manual package not installed
        result = _run_sync(conn, ["com.other.app"], cfg)

        assert "vinted" in result["unavailable"]
        row = db.get_platform_package(conn, "vinted")
        assert row["package"] == "com.vinted.app"
        assert row["source"] == "manual"
        assert row["available"] == 0

    def test_manual_priority_in_get_effective(self, conn, make_config):
        db.upsert_platform_package(
            conn, platform="olx_pl", package="pl.tablica",
            source="auto", available=True,
        )
        conn.commit()

        eff = db.get_effective_package(conn, platform="olx_pl", manual_package="pl.manual")
        assert eff == ("pl.manual", True)


class TestNoChanges:
    def test_no_changes_flag(self, conn, make_config):
        # Pre-bind and have it still installed
        db.upsert_platform_package(
            conn, platform="vinted", package="com.vinted.app",
            source="auto", available=True,
        )
        conn.commit()
        db.set_unassigned_packages(conn, [])
        conn.commit()

        cfg = make_config({
            "vinted": {"package": "", "keywords": ["vinted"]},
        })
        result = _run_sync(conn, ["com.vinted.app"], cfg)

        # No new bindings, no unavailable, no unassigned → changed should reflect state
        assert result["bound"] == []
        assert result["unavailable"] == []
        assert result["unassigned"] == []
