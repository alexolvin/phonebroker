#!/usr/bin/env bash
# Direct platform binding: sudo make platform ID=<name> PACKAGE=<pkg>
# Unbind: sudo make platform ID=<name> PACKAGE=-
# Verifies package via pm path, writes /etc/phonebroker/broker.yaml,
# restarts phonebroker, checks /health.
set -euo pipefail

ID="${1:?Usage: make platform ID=<name> PACKAGE=<package>}"
PACKAGE="${2:?Usage: make platform ID=<name> PACKAGE=<package>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/adb_cmd.sh"

ETC_BROKER="/etc/phonebroker/broker.yaml"

[ -f "$ETC_BROKER" ] || { echo "ERROR: $ETC_BROKER not found — run 'sudo make install' first" >&2; exit 1; }

SERIAL=$(python3 -c "import yaml; print(yaml.safe_load(open('$ETC_BROKER'))['adb']['serial'])")

# Verify package is installed (skip for unbind)
if [ "$PACKAGE" != "-" ]; then
    echo "[platform] Verifying package '$PACKAGE' on phone..."
    PM_PATH=$(adb_cmd -s "$SERIAL" shell pm path "$PACKAGE" 2>/dev/null || true)
    if [ -z "$PM_PATH" ]; then
        echo "ERROR: package '$PACKAGE' not found on phone (pm path returned empty)" >&2
        exit 1
    fi
    echo "[platform] Found: $PM_PATH"
fi

# Update /etc/phonebroker/broker.yaml
ID="$ID" PACKAGE="$PACKAGE" ETC_BROKER="$ETC_BROKER" python3 << 'PYEOF'
import os

import yaml

etc_broker = os.environ["ETC_BROKER"]
platform_id = os.environ["ID"]
package = os.environ["PACKAGE"]

with open(etc_broker) as f:
    cfg = yaml.safe_load(f)

if "platforms" not in cfg:
    cfg["platforms"] = {}

if platform_id not in cfg["platforms"]:
    # New platform: add with default limits
    cfg["platforms"][platform_id] = {"package": "", "limits": {}}
    print(f"[platform] Created new platform entry: {platform_id}")

if package == "-":
    cfg["platforms"][platform_id]["package"] = ""
    print(f"[platform] Unbound: {platform_id}")
else:
    cfg["platforms"][platform_id]["package"] = package
    print(f"[platform] Bound: {platform_id} → {package}")

with open(etc_broker, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
PYEOF

# Restart phonebroker
echo "[platform] Restarting phonebroker..."
systemctl restart phonebroker

# Health check
sleep 2
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/health)
if [ "$HTTP_CODE" = "200" ]; then
    echo "[platform] /health: OK (200)"
else
    echo "WARNING: /health returned $HTTP_CODE" >&2
fi

echo "[platform] Done."
