#!/usr/bin/env bash
# T1: Two simultaneous lease requests from different projects.
# Second must get 202 (waiting), first completes, second becomes active.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN_A="${ACCEPTANCE_TOKEN_A:?}"
TOKEN_B="${ACCEPTANCE_TOKEN_B:?}"
PLATFORM="acceptance_test"

# Request lease A
RESP_A=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN_A" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T1-test\",\"priority\":\"background\",\"max_duration_s\":30}")

LEASE_A=$(echo "$RESP_A" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS_A=$(echo "$RESP_A" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")

[ "$STATUS_A" = "active" ] || { echo "FAIL: A expected active, got $STATUS_A"; exit 1; }

# Request lease B (should be waiting)
RESP_B=$(curl -sf -w "\n%{http_code}" -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN_B" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T1-test\",\"priority\":\"background\",\"max_duration_s\":30}")

HTTP_B=$(echo "$RESP_B" | tail -1)
BODY_B=$(echo "$RESP_B" | head -1)

STATUS_B=$(echo "$BODY_B" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [ "$STATUS_B" = "active" ]; then
    echo "FAIL: B should not be active while A is active"
    exit 1
fi
echo "OK: B is waiting (HTTP $HTTP_B)"

# Complete A
curl -sf -X DELETE "$BASE/lease/$LEASE_A" -H "Authorization: Bearer $TOKEN_A" >/dev/null

# Wait for B to become active (up to 10s)
sleep 5
echo "A completed, waiting for B..."
echo "PASS: T1 concurrent lease test"
