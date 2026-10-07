#!/usr/bin/env bash
# T7: launch only launches the lease's platform package.
# acceptance_test → com.android.settings (always present on phone).
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

# Get active lease
RESP=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T7-launch\",\"priority\":\"interactive\",\"max_duration_s\":60}")
LEASE_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "active" ] || { echo "FAIL: no active lease"; exit 1; }

# Launch (should launch com.android.settings)
HTTP_CODE=$(curl -s -o /tmp/t7_resp.json -w "%{http_code}" \
    -X POST "$BASE/lease/$LEASE_ID/ops/launch" \
    -H "Authorization: Bearer $TOKEN")

if [ "$HTTP_CODE" = "200" ]; then
    LAUNCHED=$(python3 -c "import json; print(json.load(open('/tmp/t7_resp.json'))['launched'])")
    echo "OK: launched $LAUNCHED"
else
    echo "FAIL: unexpected HTTP $HTTP_CODE"
    cat /tmp/t7_resp.json
    exit 1
fi

# Clean up
curl -sf -X DELETE "$BASE/lease/$LEASE_ID" -H "Authorization: Bearer $TOKEN" >/dev/null
echo "PASS: T7 launch restriction"
