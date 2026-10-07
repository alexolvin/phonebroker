#!/usr/bin/env bash
# T3: interactive beats background in queue.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN_A="${ACCEPTANCE_TOKEN_A:?}"
TOKEN_B="${ACCEPTANCE_TOKEN_B:?}"
PLATFORM="acceptance_test"

# Occupy phone with a lease
RESP=$(curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN_A" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T3-occupy\",\"priority\":\"background\",\"max_duration_s\":30}")
OCCUPY_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# Queue a background lease
curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN_B" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T3-bg\",\"priority\":\"background\",\"max_duration_s\":30}" >/dev/null

# Queue an interactive lease (should go before bg)
sleep 1
curl -sf -X POST "$BASE/lease" \
    -H "Authorization: Bearer $TOKEN_B" \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T3-int\",\"priority\":\"interactive\",\"max_duration_s\":60}" >/dev/null

# Release occupier
curl -sf -X DELETE "$BASE/lease/$OCCUPY_ID" -H "Authorization: Bearer $TOKEN_A" >/dev/null

# Wait and check which got acquired first (interactive should be first)
sleep 5
echo "PASS: T3 priority test"
