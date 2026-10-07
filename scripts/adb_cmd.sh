#!/usr/bin/env bash
# adb_cmd.sh — shared ADB command wrapper. Source this file, do not execute.
#
# Usage:
#   source "$(dirname "$0")/adb_cmd.sh"
#   adb_cmd -s SERIAL shell pm list packages -3
#   adb_cmd 120 -s SERIAL install -r /tmp/apk.apk   # custom timeout (seconds)
#
# Behavior:
#   - phonebroker-adb.service active → runuser -u phonebroker -- timeout N adb ...
#   - otherwise → timeout N adb ...
#   - Timeout default: 20s. On timeout or failure: error to stderr, non-zero exit.
#   - DRY_RUN=1 → prints the command as it would be executed, does not run it.
#
# Also provides:
#   adb_exec_prefix — sets ADB_EXEC_PREFIX array for background/special cases.

_ADB_CMD_USER="phonebroker"
_ADB_CMD_DEFAULT_TIMEOUT=20

adb_exec_prefix() {
    # Sets global ADB_EXEC_PREFIX for background/special cases.
    # shellcheck disable=SC2034
    ADB_EXEC_PREFIX=()
    if systemctl is-active phonebroker-adb &>/dev/null 2>&1; then
        # shellcheck disable=SC2034
        ADB_EXEC_PREFIX=(runuser -u "$_ADB_CMD_USER" --)
    fi
}

adb_cmd() {
    local timeout_s="$_ADB_CMD_DEFAULT_TIMEOUT"

    # Optional first arg: numeric timeout override
    if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
        timeout_s="$1"
        shift
    fi

    local cmd_desc="adb $*"

    # Determine execution prefix
    local exec_prefix=()
    if systemctl is-active phonebroker-adb &>/dev/null 2>&1; then
        exec_prefix=(runuser -u "$_ADB_CMD_USER" --)
    fi

    # Dry-run: print the command as it would execute
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
        echo "[DRY-RUN] ${exec_prefix[*]} timeout $timeout_s $cmd_desc"
        return 0
    fi

    # Execute with timeout (stdout/stderr pass through to caller)
    local rc=0
    timeout "$timeout_s" "${exec_prefix[@]}" adb "$@" || rc=$?

    if [ $rc -eq 124 ]; then
        echo "ERROR: adb_cmd timeout (${timeout_s}s): $cmd_desc" >&2
        echo "       Execution: ${exec_prefix[*]} timeout $timeout_s $cmd_desc" >&2
    elif [ $rc -ne 0 ]; then
        echo "ERROR: adb_cmd failed (rc=$rc): $cmd_desc" >&2
        echo "       Execution: ${exec_prefix[*]} timeout $timeout_s $cmd_desc" >&2
    fi

    return $rc
}
