#!/usr/bin/env bash
# T12: Package sync — maintenance end triggers sync, /health shows platform status.
# Run as root: sudo make acceptance
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "SKIP: must run as root"; exit 0; }

BROKER_URL="http://127.0.0.1:8090"
TOKEN=$(grep '^PHONEBROKER_TOKEN_OWNER=' /etc/phonebroker/env | cut -d= -f2-)

[ -n "$TOKEN" ] || { echo "SKIP: no owner token"; exit 0; }

# 1. Start maintenance
START_RESP=$(curl -sf -X POST "$BROKER_URL/maintenance/start" \
    -H "Authorization: Bearer $TOKEN")
echo "start: $START_RESP"

# 2. End maintenance (triggers package sync)
END_RESP=$(curl -sf -X POST "$BROKER_URL/maintenance/end" \
    -H "Authorization: Bearer $TOKEN")
echo "end: $END_RESP"

# 3. Verify response contains sync key
echo "$END_RESP" | python3 -c "
import json, sys
data = json.load(sys.stdin)
assert 'sync' in data, f'No sync key in response: {data}'
sync = data['sync']
assert 'bound' in sync, f'No bound in sync: {sync}'
assert 'unavailable' in sync, f'No unavailable in sync: {sync}'
assert 'unassigned' in sync, f'No unassigned in sync: {sync}'
print(f'  sync: bound={len(sync[\"bound\"])}, unavailable={len(sync[\"unavailable\"])}, unassigned={len(sync[\"unassigned\"])}')
"

# 4. Check /health includes platforms
HEALTH=$(curl -sf "$BROKER_URL/health")
echo "$HEALTH" | python3 -c "
import json, sys
data = json.load(sys.stdin)
assert 'platforms' in data, f'No platforms in /health: {list(data.keys())}'
platforms = data['platforms']
assert len(platforms) > 0, 'No platforms listed'
for p in platforms:
    assert 'platform' in p and 'package' in p and 'available' in p, f'Bad platform entry: {p}'
    print(f'  {p[\"platform\"]}: pkg={p[\"package\"] or \"(none)\"} available={p[\"available\"]}')
if 'unassigned' in data:
    print(f'  unassigned: {data[\"unassigned\"]}')
"

echo "PASS: T12 package sync (maintenance end → sync → /health)"
