#!/usr/bin/env bash
# T5: Unicode text via ADB_INPUT_B64.
# Launches com.android.settings, types Czech unicode, verifies in ui_dump.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN="${ACCEPTANCE_TOKEN_A:?}"
PLATFORM="acceptance_test"
TEST_TEXT="Příliš žluťoučký kůň"
LEASE_ID=""

cleanup() {
    if [ -n "$LEASE_ID" ]; then
        curl -sf -X DELETE "$BASE/lease/$LEASE_ID" -H "Authorization: Bearer $TOKEN" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Get active lease
RESP=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T5-unicode\",\"priority\":\"interactive\",\"max_duration_s\":120}")
LEASE_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "active" ] || { echo "FAIL: no active lease"; exit 1; }

# Wake screen + dismiss keyguard
curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/keyevent" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"keycode":224}' >/dev/null
sleep 1
curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/swipe" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"x1":540,"y1":2000,"x2":540,"y2":800,"duration_ms":300}' >/dev/null
sleep 1

# Launch Settings (has a search field at top)
curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/launch" \
    -H "Authorization: Bearer $TOKEN" >/dev/null
sleep 3

# Tap the search field (top of Settings screen)
curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/tap" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"x":540,"y":490}' >/dev/null
sleep 2

# Type unicode text
curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/text" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"$TEST_TEXT\"}" >/dev/null
sleep 1

# Get ui_dump and verify text is present
UI_XML=$(curl -sf -X POST "$BASE/lease/$LEASE_ID/ops/ui_dump" \
    -H "Authorization: Bearer $TOKEN")

python3 -c "
import json, sys
data = json.loads(sys.argv[1])
xml = data['xml']
target = 'Příliš žluťoučký kůň'
if target in xml:
    print('PASS: T5 unicode text found in ui_dump')
else:
    print(f'FAIL: target text not found in ui_dump')
    sys.exit(1)
" "$UI_XML"

echo "PASS: T5 unicode text"
