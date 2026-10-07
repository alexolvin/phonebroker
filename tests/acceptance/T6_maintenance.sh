#!/usr/bin/env bash
# T6: Maintenance mode revokes active lease, projects get 423,
#     ending maintenance resumes queue.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN="${ACCEPTANCE_TOKEN_A:?}"
OWNER_TOKEN="${PHONEBROKER_TOKEN_OWNER:?}"
PLATFORM="acceptance_test"
LEASE_ID=""

cleanup() {
    if [ -n "$LEASE_ID" ]; then
        curl -sf -X DELETE "$BASE/lease/$LEASE_ID" -H "Authorization: Bearer $TOKEN" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Get/create active lease
RESP=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T6-test\",\"priority\":\"background\",\"max_duration_s\":120}")
LEASE_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
[ "$STATUS" = "active" ] || { echo "FAIL: no active lease to revoke"; exit 1; }

# Start maintenance
curl -sf -X POST "$BASE/maintenance/start" \
    -H "Authorization: Bearer $OWNER_TOKEN" >/dev/null

# Check lease was revoked
sleep 2
LEASE_STATUS=$(curl -sf "$BASE/lease/$LEASE_ID" \
    -H "Authorization: Bearer $TOKEN" | \
    python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
[ "$LEASE_STATUS" = "revoked" ] || { echo "FAIL: lease not revoked (got $LEASE_STATUS)"; exit 1; }

# Check project gets 423
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T6-after\",\"priority\":\"background\",\"max_duration_s\":30}")
[ "$HTTP_CODE" = "423" ] || { echo "FAIL: expected 423, got $HTTP_CODE"; exit 1; }

# End maintenance
curl -sf -X POST "$BASE/maintenance/end" \
    -H "Authorization: Bearer $OWNER_TOKEN" >/dev/null

# Queue should be resumed (new lease should work)
sleep 2
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T6-resume\",\"priority\":\"background\",\"max_duration_s\":30}")
[ "$HTTP_CODE" = "201" ] || { echo "FAIL: queue not resumed, got $HTTP_CODE"; exit 1; }

# Clean up the resumed lease
LEASE2=$(curl -sf "$BASE/leases" -H "Authorization: Bearer $TOKEN" | \
    python3 -c "import json,sys; leases=json.load(sys.stdin); print([l['id'] for l in leases if l['status']=='active'][0])" 2>/dev/null || echo "")
[ -n "$LEASE2" ] && curl -sf -X DELETE "$BASE/lease/$LEASE2" -H "Authorization: Bearer $TOKEN" >/dev/null

echo "PASS: T6 maintenance mode"
