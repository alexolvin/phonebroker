#!/usr/bin/env bash
# PhoneBroker uninstall — full rollback to pre-install state.
# Run as root: sudo make uninstall
# Supports --dry-run: prints commands instead of executing.
set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

install -m 644 /dev/null /tmp/phonebroker-uninstall.log
exec > >(tee -a /tmp/phonebroker-uninstall.log) 2>&1

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "[DRY-RUN] $*"
    else
        "$@"
    fi
}

PHONEBROKER_USER="phonebroker"
DATA_DIR="/var/lib/phonebroker"
ETC_DIR="/etc/phonebroker"
OPT_DIR="/opt/phonebroker"
OWNER_USER="${SUDO_USER:-user}"
OWNER_HOME=$(getent passwd "$OWNER_USER" | cut -d: -f6)

log() { echo "[uninstall] $*"; }

if [ "$DRY_RUN" -eq 1 ]; then
    log "=== DRY RUN MODE (no system changes) ==="
fi

# ─── 1. Stop services ────────────────────────────────────────────────────

log "Stopping services..."
run systemctl stop phonebroker 2>/dev/null || true
run systemctl stop phonebroker-adb 2>/dev/null || true
run systemctl stop phonebroker-sshd 2>/dev/null || true
run systemctl disable phonebroker 2>/dev/null || true
run systemctl disable phonebroker-adb 2>/dev/null || true
run systemctl disable phonebroker-sshd 2>/dev/null || true

# ─── 2. Remove nftables table ────────────────────────────────────────────

log "Removing nftables table..."
run nft delete table inet phonebroker 2>/dev/null || true
run systemctl stop phonebroker-nft 2>/dev/null || true
run systemctl disable phonebroker-nft 2>/dev/null || true

# ─── 3. Remove systemd units ─────────────────────────────────────────────

log "Removing systemd units..."
run rm -f /etc/systemd/system/phonebroker.service
run rm -f /etc/systemd/system/phonebroker-adb.service
run rm -f /etc/systemd/system/phonebroker-sshd.service
run rm -f /etc/systemd/system/phonebroker-nft.service
run systemctl daemon-reload

# ─── 4. udev → plugdev ───────────────────────────────────────────────────

log "Restoring udev rule (GROUP=plugdev)..."
run bash -c 'cat > /etc/udev/rules.d/99-phonebroker-adb.rules <<'"'"'UDEOF'"'"'
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ENV{ID_USB_INTERFACES}=="*:ff4201:*", MODE="0660", GROUP="plugdev"
UDEOF'
run bash -c 'rm -f /etc/udev/rules.d/51-adb.rules'
run udevadm control --reload
run udevadm trigger

# ─── 5. Restore user-level ADB ───────────────────────────────────────────

log "Enabling user-level adb.service..."
USER_UID=$(id -u "$OWNER_USER" 2>/dev/null || echo "")
if [ -n "$USER_UID" ]; then
    run runuser -u "$OWNER_USER" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        systemctl --user enable adb.service 2>/dev/null || \
        log "User adb.service not found (may need manual re-enable)"
    run runuser -u "$OWNER_USER" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        systemctl --user start adb.service 2>/dev/null || \
        log "User adb.service start failed (may not be installed)"
fi

# ─── 6. Unmask ssh (if we masked it) ─────────────────────────────────────

if [ -f "$ETC_DIR/ssh_masked_by_install" ]; then
    log "Unmasking ssh.service and ssh.socket..."
    run systemctl unmask ssh.service ssh.socket
fi

# ─── 7. Return SSH key to user (original from owner_key.orig) ────────────

log "Returning SSH key to $OWNER_HOME/.ssh/authorized_keys..."
if [ -f "$ETC_DIR/owner_key.orig" ]; then
    ORIGINAL_KEY=$(cat "$ETC_DIR/owner_key.orig")
    run bash -c "mkdir -p '$OWNER_HOME/.ssh' && echo '$ORIGINAL_KEY' >> '$OWNER_HOME/.ssh/authorized_keys'"
    run chown "$OWNER_USER":"$OWNER_USER" "$OWNER_HOME/.ssh/authorized_keys" 2>/dev/null || true
    run chmod 600 "$OWNER_HOME/.ssh/authorized_keys" 2>/dev/null || true
    log "Original SSH key restored from owner_key.orig"
else
    log "WARNING: owner_key.orig not found — manual key restore may be needed"
fi

# ─── 8. Remove /etc/phonebroker ──────────────────────────────────────────

log "Removing $ETC_DIR..."
run rm -rf "$ETC_DIR"

# ─── 9. Remove /opt/phonebroker ──────────────────────────────────────────

log "Removing $OPT_DIR..."
run rm -rf "$OPT_DIR"

# ─── 10. Remove data dir ─────────────────────────────────────────────────

log "Removing $DATA_DIR..."
run rm -rf "$DATA_DIR"

# ─── 11. Remove user ─────────────────────────────────────────────────────

log "Removing user $PHONEBROKER_USER..."
run userdel "$PHONEBROKER_USER" 2>/dev/null || true
run groupdel "$PHONEBROKER_USER" 2>/dev/null || true

# ─── 12. Remove nftables config file ─────────────────────────────────────

run rm -f /etc/nftables/phonebroker.nft

log "Uninstall complete."
log "State restored: udev→plugdev, user ADB enabled, SSH key returned."
log "Log: /tmp/phonebroker-uninstall.log"
