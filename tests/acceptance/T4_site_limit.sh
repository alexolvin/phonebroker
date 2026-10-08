#!/usr/bin/env bash
# T4: Site limits — background min_interval_s=5, max_daily_leases=3.
#   1. Second lease within 5s of the previous end → 403 interval.
#   2. After 5s → 201.
#   3. Fourth lease of the day → 403 daily_limit.
# Limits are applied to acceptance_test for the duration of this test and
# restored in cleanup; site_leases counters are deleted in teardown.
set -euo pipefail

BASE="http://127.0.0.1:8090"
TOKEN="${ACCEPTANCE_TOKEN_A:?}"
PLATFORM="acceptance_test"
BROKER_YAML="/etc/phonebroker/broker.yaml"
DB_PATH="/var/lib/phonebroker/phonebroker.db"
BODY_FILE="/tmp/t4_body.json"

set_limits() {  # $1=min_interval_s $2=max_daily_leases
    python3 - "$BROKER_YAML" "$1" "$2" << 'PYEOF'
import sys, yaml
path, interval, daily = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with open(path) as f:
    cfg = yaml.safe_load(f)
cfg["platforms"]["acceptance_test"]["limits"]["background"] = {
    "min_interval_s": interval, "max_daily_leases": daily,
}
with open(path, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
PYEOF
}

clear_counters() {
    python3 - "$DB_PATH" << 'PYEOF'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("DELETE FROM site_leases WHERE platform='acceptance_test'")
conn.commit()
PYEOF
}

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

# Teardown: restore limits, restart broker, delete test platform counters
cleanup() {
    set_limits 0 100
    systemctl restart phonebroker 2>/dev/null || true
    wait_healthy
    clear_counters
}
trap cleanup EXIT

# Apply test limits, clean counters, restart broker (config is cached)
set_limits 5 3
clear_counters
systemctl restart phonebroker
wait_healthy

request_lease() {
    curl -s -o "$BODY_FILE" -w "%{http_code}" -X POST "$BASE/lease" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"platform\":\"$PLATFORM\",\"operation\":\"T4-test\",\"priority\":\"background\",\"max_duration_s\":30}"
}

complete_active_lease() {
    local id
    id=$(curl -sf "$BASE/leases" -H "Authorization: Bearer $TOKEN" | \
        python3 -c "import json,sys; leases=json.load(sys.stdin); print([l['id'] for l in leases if l['status']=='active'][0])")
    curl -sf -X DELETE "$BASE/lease/$id" -H "Authorization: Bearer $TOKEN" >/dev/null
}

# 1. First lease → 201, then complete
HTTP_CODE=$(request_lease)
[ "$HTTP_CODE" = "201" ] || { echo "FAIL: lease1 expected 201, got $HTTP_CODE"; exit 1; }
complete_active_lease

# 2. Second lease immediately (<5s) → 403 interval
HTTP_CODE=$(request_lease)
echo "second lease (immediate): HTTP $HTTP_CODE"
echo "body: $(cat "$BODY_FILE")"
[ "$HTTP_CODE" = "403" ] || { echo "FAIL: expected 403, got $HTTP_CODE"; exit 1; }
grep -q 'interval: Minimum interval' "$BODY_FILE" || { echo "FAIL: body missing interval reason"; exit 1; }

# 3. After 5s → 201
sleep 6
HTTP_CODE=$(request_lease)
[ "$HTTP_CODE" = "201" ] || { echo "FAIL: lease after interval expected 201, got $HTTP_CODE"; exit 1; }
complete_active_lease

# 4. Third lease (after interval) → 201 (daily count becomes 3)
sleep 6
HTTP_CODE=$(request_lease)
[ "$HTTP_CODE" = "201" ] || { echo "FAIL: lease3 expected 201, got $HTTP_CODE"; exit 1; }
complete_active_lease

# 5. Fourth lease of the day → 403 daily_limit
sleep 6
HTTP_CODE=$(request_lease)
echo "fourth lease (daily limit): HTTP $HTTP_CODE"
echo "body: $(cat "$BODY_FILE")"
[ "$HTTP_CODE" = "403" ] || { echo "FAIL: expected 403, got $HTTP_CODE"; exit 1; }
grep -q 'daily_limit: Daily limit' "$BODY_FILE" || { echo "FAIL: body missing daily_limit reason"; exit 1; }

echo "PASS: T4 site limit (403 interval / 201 after 5s / 403 daily_limit)"
