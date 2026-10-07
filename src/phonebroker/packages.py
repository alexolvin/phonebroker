"""Package synchronization: detect installed platform apps, track availability.

Sync is triggered on every maintenance end. Results stored in SQLite.
/etc/phonebroker/broker.yaml is read-only for the broker (keywords, limits,
manual bindings). Manual binding has priority over auto-binding.
"""

import logging
import sqlite3

from phonebroker import adb, db
from phonebroker.config import load_config

logger = logging.getLogger("phonebroker.packages")


def _pm_list(serial: str, *extra: str) -> list[str]:
    """Run pm list packages with optional filters."""
    result = adb._adb(serial, "shell", "pm", "list", "packages", *extra)
    return sorted(
        line.replace("package:", "").strip()
        for line in result.stdout.splitlines()
        if line.strip()
    )


def list_all_packages() -> list[str]:
    """All installed packages (system + third-party)."""
    cfg = load_config()
    return _pm_list(cfg.adb.serial)


def list_third_party_packages() -> list[str]:
    """Third-party packages only (-3 flag)."""
    cfg = load_config()
    return _pm_list(cfg.adb.serial, "-3")


def sync_packages(conn: sqlite3.Connection) -> dict:
    """Run full package sync. Returns result dict.

    Returns:
        {
            "bound": ["platform → package", ...],
            "unavailable": ["platform", ...],
            "unassigned": ["com.example.app", ...],
            "changed": bool,
        }
    """
    try:
        all_packages = list_all_packages()
        third_party = list_third_party_packages()
    except (adb.ADBError, Exception) as e:
        logger.warning("Package sync failed (ADB unavailable): %s", e)
        return {"bound": [], "unavailable": [], "unassigned": [], "changed": False}

    installed_set = set(all_packages)
    cfg = load_config()

    bound: list[str] = []
    unavailable: list[str] = []
    bound_packages: set[str] = set()

    for platform, pcfg in cfg.platforms.items():
        manual_pkg = pcfg.package
        existing = db.get_platform_package(conn, platform)

        if manual_pkg:
            # Manual binding (from /etc config) — priority
            available = manual_pkg in installed_set
            db.upsert_platform_package(
                conn,
                platform=platform,
                package=manual_pkg,
                source="manual",
                available=available,
            )
            bound_packages.add(manual_pkg)
            if not available:
                unavailable.append(platform)
        elif existing:
            # Existing auto-binding — check if still installed
            available = existing["package"] in installed_set
            db.upsert_platform_package(
                conn,
                platform=platform,
                package=existing["package"],
                source="auto",
                available=available,
            )
            bound_packages.add(existing["package"])
            if not available:
                unavailable.append(platform)
        else:
            # No binding — try keyword match
            keywords = pcfg.keywords
            matched = None
            if keywords:
                for pkg in third_party:
                    pkg_lower = pkg.lower()
                    if any(kw in pkg_lower for kw in keywords):
                        matched = pkg
                        break
            if matched:
                db.upsert_platform_package(
                    conn,
                    platform=platform,
                    package=matched,
                    source="auto",
                    available=True,
                )
                bound_packages.add(matched)
                bound.append(f"{platform} \u2192 {matched}")

    # Unassigned: third-party packages not bound to any platform
    unassigned = sorted(p for p in third_party if p not in bound_packages)
    db.set_unassigned_packages(conn, unassigned)

    conn.commit()

    changed = bool(bound or unavailable or unassigned)
    return {
        "bound": bound,
        "unavailable": unavailable,
        "unassigned": unassigned,
        "changed": changed,
    }


def get_platform_status(conn: sqlite3.Connection) -> list[dict]:
    """Return platform status for /health endpoint."""
    cfg = load_config()
    result = []
    for platform, pcfg in cfg.platforms.items():
        eff = db.get_effective_package(conn, platform=platform, manual_package=pcfg.package)
        if eff:
            pkg, available = eff
            result.append({"platform": platform, "package": pkg, "available": available})
        else:
            result.append({"platform": platform, "package": "", "available": False})
    return result
