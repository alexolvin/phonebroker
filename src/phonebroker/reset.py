"""Phone state reset — before/after each lease and on revoke.

Sequence:
  Start: force-stop platform packages → HOME → WAKEUP → swipe → IME to ADBKeyBoard
  End:   force-stop platform packages → HOME → SLEEP → IME to system default

All ADB calls are wrapped: if the phone is offline, reset degrades gracefully
(logs the error) instead of blocking.
"""

import logging
import subprocess

from phonebroker import adb, db
from phonebroker.config import load_config
from phonebroker.exceptions import ADBError

logger = logging.getLogger(__name__)


def _platform_packages() -> list[str]:
    """Get all effective platform packages (manual from config + auto from
    SQLite). Manual binding takes priority over the auto-binding."""
    cfg = load_config()
    pkgs: list[str] = []
    try:
        conn = db.get_connection()
    except Exception as e:  # DB unavailable (first run / phone offline)
        logger.warning("reset: cannot open DB for platform packages: %s", e)
        return [pf.package for pf in cfg.platforms.values() if pf.package]
    try:
        for platform, pcfg in cfg.platforms.items():
            eff = db.get_effective_package(
                conn, platform=platform, manual_package=pcfg.package
            )
            if eff and eff[0]:
                pkgs.append(eff[0])
    finally:
        conn.close()
    return pkgs


def _safe(fn, *args, **kwargs):
    """Run an ADB operation, log and continue on failure (phone may be offline)."""
    try:
        fn(*args, **kwargs)
    except (ADBError, subprocess.TimeoutExpired) as e:
        logger.warning("reset: %s failed (phone offline?): %s", fn.__name__, e)


def reset_before_lease() -> None:
    """Prepare phone for a new lease: clean state + unlocked + ADBKeyBoard active."""
    cfg = load_config()
    # 1. Force-stop all platform packages
    for pkg in _platform_packages():
        _safe(adb.force_stop, pkg)

    # 2. HOME
    _safe(adb.keyevent, 3)

    # 3. WAKEUP
    _safe(adb.keyevent, 224)

    # 4. Dismiss keyguard (swipe up)
    s = cfg.unlock_swipe
    _safe(adb.swipe, s.x1, s.y1, s.x2, s.y2)

    # 5. Activate ADBKeyBoard
    _safe(adb.set_ime, cfg.ime.adbkeyboard)


def reset_after_lease() -> None:
    """Clean up after lease ends: stop apps, home, sleep, restore IME."""
    # 1. Force-stop all platform packages
    for pkg in _platform_packages():
        _safe(adb.force_stop, pkg)

    # 2. HOME
    _safe(adb.keyevent, 3)

    # 3. SLEEP
    _safe(adb.keyevent, 223)

    # 4. Restore system IME
    cfg = load_config()
    if cfg.ime.system_default:
        _safe(adb.set_ime, cfg.ime.system_default)
