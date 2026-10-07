#!/usr/bin/env bash
# Detect platform packages on phone and write to /etc/phonebroker/broker.yaml.
# For unmatched platforms: interactive selection from unbound packages.
# After config write: restart phonebroker + health check.
# Run as root: sudo make platforms
set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

LOG="/tmp/phonebroker-platforms.log"
install -m 644 /dev/null "$LOG"
exec > >(tee -a "$LOG") 2>&1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/adb_cmd.sh"

ETC_BROKER="/etc/phonebroker/broker.yaml"
REPO_CONFIG="config/broker.yaml"

[ -f "$ETC_BROKER" ] || { echo "ERROR: $ETC_BROKER not found — run 'sudo make install' first" >&2; exit 1; }
[ -f "$REPO_CONFIG" ] || { echo "ERROR: $REPO_CONFIG not found" >&2; exit 1; }

SERIAL=$(python3 -c "import yaml; print(yaml.safe_load(open('$ETC_BROKER'))['adb']['serial'])")

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY-RUN] Would read packages from phone and match platforms."
    echo "[DRY-RUN] Would update $ETC_BROKER"
    echo "[DRY-RUN] Would restart phonebroker and check /health"
    exit 0
fi

echo "[platforms] Reading third-party packages from phone..."
PACKAGES=$(adb_cmd -s "$SERIAL" shell pm list packages -3 2>/dev/null | \
    sed 's/^package://' | sort)

[ -n "$PACKAGES" ] || { echo "ERROR: no packages found (phone connected?)" >&2; exit 1; }

echo "[platforms] Matching against platform keywords..."

PACKAGES="$PACKAGES" ETC_BROKER="$ETC_BROKER" REPO_CONFIG="$REPO_CONFIG" python3 << 'PYEOF'
import os
import subprocess
import sys
import time
import urllib.request

import yaml

etc_broker = os.environ["ETC_BROKER"]
repo_config = os.environ["REPO_CONFIG"]
packages = [p.strip() for p in os.environ["PACKAGES"].splitlines() if p.strip()]

# Read keywords from repo config
with open(repo_config) as f:
    repo_cfg = yaml.safe_load(f)

with open(etc_broker) as f:
    cfg = yaml.safe_load(f)

platforms_cfg = repo_cfg.get("platforms", {})
keyword_map = {}
for platform, pcfg in platforms_cfg.items():
    kws = pcfg.get("keywords", [])
    if kws:
        keyword_map[platform] = kws

# Match packages to platforms by keywords
found = {}
not_found = []
bound_packages = set()

for platform, keywords in keyword_map.items():
    matched = None
    for pkg in packages:
        pkg_lower = pkg.lower()
        if any(kw in pkg_lower for kw in keywords):
            matched = pkg
            break
    if matched:
        found[platform] = matched
        bound_packages.add(matched)
    else:
        not_found.append(platform)

# Already-bound packages from current config
for platform, pcfg in cfg.get("platforms", {}).items():
    pkg = pcfg.get("package", "")
    if pkg:
        bound_packages.add(pkg)

# Unbound: installed but not matched by keyword and not already bound
unbound = [p for p in packages if p not in bound_packages]

# Interactive: assign unbound packages to unmatched platforms
if not_found and unbound:
    print(f"\nНе найдены по ключевым словам: {', '.join(not_found)}")
    print("Установленные сторонние пакеты, ещё не привязанные:")
    for i, pkg in enumerate(unbound, 1):
        print(f"  {i}. {pkg}")

    for platform in list(not_found):
        if not unbound:
            break
        print(f"\n[{platform}] Введите номер пакета (Enter — пропустить): ", end="", flush=True)
        try:
            choice = input().strip()
        except (EOFError, KeyboardInterrupt):
            choice = ""
        if choice and choice.isdigit() and 1 <= int(choice) <= len(unbound):
            idx = int(choice) - 1
            pkg = unbound.pop(idx)
            found[platform] = pkg
            bound_packages.add(pkg)
            not_found.remove(platform)
            print(f"  → {pkg}")

# Write updated config
for platform, pkg in found.items():
    if platform in cfg.get("platforms", {}):
        cfg["platforms"][platform]["package"] = pkg

with open(etc_broker, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

# Report table
print(f"\n{'Площадка':<25s} {'Пакет':<45s}")
print(f"{'─' * 25:<25s} {'─' * 45:<45s}")
for platform in keyword_map:
    if platform in found:
        print(f"{platform:<25s} {found[platform]:<45s}")
    else:
        print(f"{platform:<25s} {'(не привязан)':<45s}")

if not_found:
    print(f"\nНе привязаны: {', '.join(not_found)}")
    print("Привязать вручную: sudo make platform ID=<площадка> PACKAGE=<пакет>")

print(f"\n[platforms] {etc_broker} updated ({len(found)}/{len(keyword_map)} platforms)")

# Restart phonebroker
print("\n[platforms] Restarting phonebroker...")
result = subprocess.run(["systemctl", "restart", "phonebroker"], capture_output=True, text=True)
if result.returncode != 0:
    print(f"ERROR: restart failed: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Health check
time.sleep(2)
try:
    with urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=10) as resp:
        body = resp.read().decode()
        print(f"[platforms] /health: {resp.status} {body}")
except Exception as e:
    print(f"WARNING: /health check failed: {e}", file=sys.stderr)
PYEOF

echo "[platforms] Log: $LOG"
