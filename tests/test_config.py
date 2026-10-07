"""Tests for config loading and validation."""

from pathlib import Path

import pytest
import yaml

from phonebroker.config import BrokerConfig, SiteLimits, load_config, reset_config


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def test_load_config_from_repo():
    cfg = load_config()
    assert cfg.port == 8090
    assert cfg.adb.serial
    assert "vinted" in cfg.platforms
    assert "facebook_marketplace" in cfg.platforms
    assert "sbazar_cz" in cfg.platforms
    assert "kleinanzeigen_de" in cfg.platforms
    assert "willhaben_at" in cfg.platforms
    assert "olx_pl" in cfg.platforms


def test_get_limits_default():
    cfg = load_config()
    limits = cfg.get_limits("vinted", "background")
    assert limits.min_interval_s == 300
    assert limits.max_daily_leases == 10


def test_get_limits_interactive():
    cfg = load_config()
    limits = cfg.get_limits("vinted", "interactive")
    assert limits.min_interval_s == 0
    assert limits.max_daily_leases == 50


def test_unlock_swipe():
    cfg = load_config()
    assert cfg.unlock_swipe.x1 == 540
    assert cfg.unlock_swipe.y1 == 2000
    assert cfg.unlock_swipe.x2 == 540
    assert cfg.unlock_swipe.y2 == 500


def test_site_limits_model():
    sl = SiteLimits(min_interval_s=100, max_daily_leases=5)
    assert sl.min_interval_s == 100
    assert sl.max_daily_leases == 5
