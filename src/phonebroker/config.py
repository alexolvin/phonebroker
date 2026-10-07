"""PhoneBroker configuration.

The single source of configuration is /etc/phonebroker/broker.yaml (runtime).
In development/tests, the repo's config/broker.yaml is used as fallback.

All tunables live in YAML, validated by Pydantic models. No hardcoded values
in source code (checked by check_hardcode.py).
"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Runtime config path (production)
_RUNTIME_CONFIG = Path("/etc/phonebroker/broker.yaml")
# Repo defaults (development/tests)
# This file: <root>/src/phonebroker/config.py → root is 3 levels up
_REPO_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "broker.yaml"


class SiteLimits(BaseModel):
    min_interval_s: int = 300
    max_daily_leases: int = 10


class PlatformConfig(BaseModel):
    package: str = ""
    keywords: list[str] = Field(default_factory=list)
    limits: dict[str, SiteLimits] = Field(default_factory=dict)


class ADBConfig(BaseModel):
    serial: str


class UnlockSwipe(BaseModel):
    x1: int = 540
    y1: int = 2000
    x2: int = 540
    y2: int = 500


class IMEConfig(BaseModel):
    system_default: str = ""
    adbkeyboard: str = "com.android.adbkeyboard/.AdbIME"


class ADBKeyBoardConfig(BaseModel):
    url: str = ""
    sha256: str = ""


class ClientConfig(BaseModel):
    env_file: str = ""


class BrokerConfig(BaseModel):
    port: int = 8090
    heartbeat_timeout_s: int = 60
    check_interval_s: int = 2
    starvation_threshold: int = 5
    journal_retention_days: int = 90

    adb: ADBConfig
    unlock_swipe: UnlockSwipe = Field(default_factory=UnlockSwipe)
    ime: IMEConfig = Field(default_factory=IMEConfig)
    adbkeyboard: ADBKeyBoardConfig = Field(default_factory=ADBKeyBoardConfig)
    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)
    defaults: dict[str, SiteLimits] = Field(default_factory=dict)
    clients: dict[str, ClientConfig] = Field(default_factory=dict)
    data_dir: str = "/var/lib/phonebroker"

    def get_limits(self, platform: str, priority: str) -> SiteLimits:
        """Get effective limits for a platform+priority (per-platform override wins)."""
        pf = self.platforms.get(platform)
        if pf:
            override = pf.limits.get(priority)
            if override:
                return override
        return self.defaults.get(priority, SiteLimits())


def _find_config() -> Path:
    if _RUNTIME_CONFIG.is_file() and os.access(_RUNTIME_CONFIG, os.R_OK):
        return _RUNTIME_CONFIG
    if _REPO_CONFIG.is_file():
        return _REPO_CONFIG
    raise FileNotFoundError(
        f"No broker.yaml found: checked {_RUNTIME_CONFIG} and {_REPO_CONFIG}"
    )


_config_instance: BrokerConfig | None = None


def load_config() -> BrokerConfig:
    """Load and validate broker configuration. Cached after first call."""
    global _config_instance
    if _config_instance is not None:
        return _config_instance

    path = _find_config()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    _config_instance = BrokerConfig.model_validate(raw)
    return _config_instance


def get_data_dir() -> Path:
    """The single source of the data directory path."""
    return Path(load_config().data_dir)


def reset_config() -> None:
    """Reset cached config (for tests)."""
    global _config_instance
    _config_instance = None
