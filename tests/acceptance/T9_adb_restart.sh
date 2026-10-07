#!/usr/bin/env bash
# T9: ADB server restart — phone back to 'device' without screen taps.
# Run as root: sudo make acceptance
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "SKIP: must run as root"; exit 0; }

source "$(cd "$(dirname "$0")/../../scripts" && pwd)/adb_cmd.sh"

echo "Restarting phonebroker-adb..."
systemctl restart phonebroker-adb
sleep 3

SERIAL=$(python3 -c "import yaml; print(yaml.safe_load(open('/etc/phonebroker/broker.yaml'))['adb']['serial'])")

# Check phone state
STATE=$(adb_cmd -s "$SERIAL" get-state 2>/dev/null || echo "unknown")
echo "Phone state after restart: $STATE"

if [ "$STATE" = "device" ]; then
    echo "PASS: T9 ADB restart (phone=device without screen interaction)"
else
    echo "FAIL: T9 ADB restart (state=$STATE, expected device)"
    exit 1
fi
