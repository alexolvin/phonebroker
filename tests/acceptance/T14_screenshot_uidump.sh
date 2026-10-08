#!/usr/bin/env bash
# T14: screenshot and ui_dump within a lease return PNG and XML;
#      a non-whitelisted shell command is rejected by the ADB white-list.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN="${ACCEPTANCE_TOKEN_A:?}"
PLATFORM="acceptance_test"
LEASE_ID=""

cleanup() {
    if [ -n "$LEASE_ID" ]; then
        curl -sf -X DELETE "$BASE/lease/$LEASE_ID" -H "Authorization: Bearer $TOKEN" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Get an active lease
RESP=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T14-test\",\"priority\":\"background\",\"max_duration_s\":120}")
LEASE_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "active" ] || { echo "FAIL: no active lease (got $STATUS)"; exit 1; }

# 1. screenshot → PNG
SHOT=$(curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/screenshot" \
    -H "Authorization: Bearer $TOKEN")
echo "$SHOT" | python3 -c "
import base64, json, sys
data = base64.b64decode(json.load(sys.stdin)['image'])
assert data[:8] == b'\x89PNG\r\n\x1a\n', 'screenshot is not a PNG'
print(f'  screenshot: {len(data)} bytes PNG')
"

# 2. ui_dump → XML
DUMP=$(curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/ui_dump" \
    -H "Authorization: Bearer $TOKEN")
echo "$DUMP" | python3 -c "
import json, sys
xml = json.load(sys.stdin)['xml']
assert xml.lstrip().startswith('<?xml'), 'ui_dump is not XML'
assert '<hierarchy' in xml, 'ui_dump is not a uiautomator hierarchy'
print(f'  ui_dump: {len(xml)} bytes XML')
"

# 3. Non-whitelisted shell command → rejected (installed code)
/opt/phonebroker/.venv/bin/python - << 'PYEOF'
from phonebroker import adb
from phonebroker.config import load_config

serial = load_config().adb.serial
try:
    adb._adb_shell(serial, "cat /etc/hostname")
except adb.ADBError as e:
    print(f"  non-whitelisted command rejected: {e}")
else:
    raise SystemExit("FAIL: non-whitelisted command was allowed")
PYEOF

echo "PASS: T14 screenshot/ui_dump/white-list"
