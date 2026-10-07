#!/usr/bin/env bash
# T2: Lease without heartbeat is revoked after timeout.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN="${ACCEPTANCE_TOKEN_A:?}"
PLATFORM="acceptance_test"

# Request lease
RESP=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T2-test\",\"priority\":\"background\",\"max_duration_s\":30}")

LEASE_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")

[ "$STATUS" = "active" ] || { echo "FAIL: expected active"; exit 1; }

# Do NOT send heartbeat. Wait for timeout (heartbeat_timeout_s=60 + margin)
echo "Waiting for heartbeat timeout (65s)..."
sleep 65

# Check lease status
RESP=$(curl -sf "$BASE/lease/$LEASE_ID" -H "Authorization: Bearer $TOKEN")
STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")

[ "$STATUS" = "revoked" ] || { echo "FAIL: expected revoked, got $STATUS"; exit 1; }

echo "PASS: T2 no-heartbeat revoke (status=$STATUS)"
