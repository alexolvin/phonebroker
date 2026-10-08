#!/usr/bin/env bash
# T13: Maintenance state survives broker restart (SQLite-persisted).
#   1. Start maintenance → restart broker → project lease gets 423.
#   2. Start maintenance → broker down past renew deadline → broker start
#      ends maintenance with result=broker_restart, queue resumed.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN="${ACCEPTANCE_TOKEN_A:?}"
OWNER_TOKEN="${PHONEBROKER_TOKEN_OWNER:?}"
PLATFORM="acceptance_test"
DB_PATH="/var/lib/phonebroker/phonebroker.db"
LEASE_ID=""

cleanup() {
    if [ -n "$LEASE_ID" ]; then
        curl -sf -X DELETE "$BASE/lease/$LEASE_ID" -H "Authorization: Bearer $TOKEN" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

wait_healthy() {
    for _ in $(seq 1 30); do
        if curl -sf --max-time 2 "$BASE/health" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "FAIL: broker not healthy"
    exit 1
}

request_lease() {
    curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/lease" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T13-test\",\"priority\":\"background\",\"max_duration_s\":30}"
}

# ─── Part 1: maintenance survives broker restart ──────────────────────────

curl -sf -X POST "$BASE/maintenance/start" \
    -H "Authorization: Bearer $OWNER_TOKEN" >/dev/null

systemctl restart phonebroker
wait_healthy

HTTP_CODE=$(request_lease)
[ "$HTTP_CODE" = "423" ] || { echo "FAIL: part1 expected 423 after restart, got $HTTP_CODE"; exit 1; }

# ─── Part 2: expired renew deadline → broker_restart on startup ──────────

# Broker is down: renew cannot happen, deadline (60s) expires while stopped
systemctl stop phonebroker
sleep 65
systemctl start phonebroker
wait_healthy

HTTP_CODE=$(request_lease)
case "$HTTP_CODE" in
    201|202) : ;;
    *) echo "FAIL: part2 queue not resumed, got $HTTP_CODE"; exit 1 ;;
esac

# Clean up the resumed lease (201 → active)
if [ "$HTTP_CODE" = "201" ]; then
    LEASE_ID=$(curl -sf "$BASE/leases" -H "Authorization: Bearer $TOKEN" | \
        python3 -c "import json,sys; leases=json.load(sys.stdin); print([l['id'] for l in leases if l['status']=='active'][0])" 2>/dev/null || echo "")
fi

RESULT=$(python3 - "$DB_PATH" <<'EOF'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
row = conn.execute(
    "SELECT result FROM journal WHERE action='maintenance_end' ORDER BY id DESC LIMIT 1"
).fetchone()
print(row[0] if row else "")
EOF
)
[ "$RESULT" = "broker_restart" ] || { echo "FAIL: expected maintenance_end result=broker_restart, got '$RESULT'"; exit 1; }

echo "PASS: T13 maintenance restart"
