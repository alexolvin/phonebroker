#!/usr/bin/env bash
# T8: nftables isolation — port 5037 accessible only to phonebroker uid.
# Run as root: sudo make acceptance
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "SKIP: must run as root"; exit 0; }

# From uid 'user' — should be DENIED
USER_RC=0
timeout 3 runuser -u user -- nc -z 127.0.0.1 5037 2>/dev/null || USER_RC=$?

# From phonebroker — should SUCCEED
PB_RC=0
timeout 3 runuser -u phonebroker -- nc -z 127.0.0.1 5037 2>/dev/null || PB_RC=$?

echo "user: rc=$USER_RC"
echo "phonebroker: rc=$PB_RC"

if [ $USER_RC -ne 0 ] && [ $PB_RC -eq 0 ]; then
    echo "PASS: T8 nftables isolation (user denied, phonebroker allowed)"
else
    echo "FAIL: T8 nftables isolation (user rc=$USER_RC, phonebroker rc=$PB_RC)"
    exit 1
fi
