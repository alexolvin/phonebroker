#!/usr/bin/env bash
# Run all acceptance tests T1-T9, T12.
# Self-contained: creates temporary clients/platform, cleans up on exit.
# Requires: phonebroker service running, phone connected. Run as root.
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "ERROR: must run as root"; exit 1; }

LOG="/tmp/phonebroker-acceptance.log"
install -m 644 /dev/null "$LOG"
exec > >(tee -a "$LOG") 2>&1

ENV_FILE="/etc/phonebroker/env"
BROKER_YAML="/etc/phonebroker/broker.yaml"
BROKER_URL="http://127.0.0.1:8090"

# ─── Read existing owner token ─────────────────────────────────────────────
OWNER_TOKEN=$(grep '^PHONEBROKER_TOKEN_OWNER=' "$ENV_FILE" | cut -d= -f2-)
[ -n "$OWNER_TOKEN" ] || { echo "ERROR: PHONEBROKER_TOKEN_OWNER not in $ENV_FILE"; exit 1; }

# ─── Generate temporary test tokens ────────────────────────────────────────
TOKEN_A=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
TOKEN_B=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# ─── Setup: add temp clients to env, temp platform to broker.yaml ─────────
setup() {
    # Add temp clients to env file
    echo "PHONEBROKER_TOKEN_ACCEPTANCE_A=$TOKEN_A" >> "$ENV_FILE"
    echo "PHONEBROKER_TOKEN_ACCEPTANCE_B=$TOKEN_B" >> "$ENV_FILE"

    # Add temp platform to broker.yaml
    python3 -c "
import yaml
with open('$BROKER_YAML') as f:
    cfg = yaml.safe_load(f)
cfg.setdefault('platforms', {})['acceptance_test'] = {
    'package': 'com.android.settings',
    'keywords': [],
    'limits': {'background': {'min_interval_s': 0, 'max_daily_leases': 100},
               'interactive': {'min_interval_s': 0, 'max_daily_leases': 100}},
}
with open('$BROKER_YAML', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
"
    echo "[setup] Added acceptance_test platform + temp clients"

    # Restart broker to pick up new config
    systemctl restart phonebroker
    sleep 3

    # Verify broker is healthy
    curl -sf --max-time 5 "$BROKER_URL/health" >/dev/null || {
        echo "ERROR: broker not healthy after restart"
        exit 1
    }
}

# ─── Teardown: remove temp clients and platform ───────────────────────────
teardown() {
    echo ""
    echo "[teardown] Removing temp clients and platform..."

    # Remove temp tokens from env
    sed -i '/^PHONEBROKER_TOKEN_ACCEPTANCE_A=/d' "$ENV_FILE"
    sed -i '/^PHONEBROKER_TOKEN_ACCEPTANCE_B=/d' "$ENV_FILE"

    # Remove temp platform from broker.yaml
    python3 -c "
import yaml
with open('$BROKER_YAML') as f:
    cfg = yaml.safe_load(f)
cfg.get('platforms', {}).pop('acceptance_test', None)
with open('$BROKER_YAML', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
" 2>/dev/null || true

    # Restart broker
    systemctl restart phonebroker 2>/dev/null || true
    echo "[teardown] Done."
}

trap teardown EXIT

# ─── Run setup ─────────────────────────────────────────────────────────────
setup

# ─── Export tokens for test scripts ────────────────────────────────────────
export PHONEBROKER_TOKEN_OWNER="$OWNER_TOKEN"
export ACCEPTANCE_TOKEN_A="$TOKEN_A"
export ACCEPTANCE_TOKEN_B="$TOKEN_B"

# ─── Run tests ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0
OWNER=0
RESULTS=()

run_test() {
    local name="$1" script="$2"
    echo "=== $name ==="
    if bash "$SCRIPT_DIR/$script"; then
        echo "[PASS] $name"
        RESULTS+=("PASS: $name")
        PASS=$((PASS + 1))
    else
        echo "[FAIL] $name"
        RESULTS+=("FAIL: $name")
        FAIL=$((FAIL + 1))
    fi
    echo ""
}

run_test "T1: Concurrent leases" T1_concurrent.sh
run_test "T2: No heartbeat revoke" T2_no_heartbeat.sh
run_test "T3: Priority order" T3_priority.sh
run_test "T4: Site limit interval" T4_site_limit.sh
run_test "T5: Unicode text" T5_unicode.sh
run_test "T6: Maintenance mode" T6_maintenance.sh
run_test "T7: Launch restriction" T7_launch_restriction.sh
run_test "T8: nftables isolation" T8_nft_isolation.sh
run_test "T9: ADB restart" T9_adb_restart.sh
run_test "T12: Package sync" T12_package_sync.sh

# Owner-only tests (run from laptop, not by this script)
RESULTS+=("OWNER: T10: Phone screen (laptop)")
RESULTS+=("OWNER: T11: SSH forced command (laptop)")
OWNER=2

# ─── Summary ───────────────────────────────────────────────────────────────
echo "======================"
echo "SUMMARY:"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo "======================"
echo "Results: $PASS passed, $FAIL failed, $OWNER owner-only"

[ "$FAIL" -eq 0 ]
