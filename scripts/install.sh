#!/usr/bin/env bash
# PhoneBroker installer — run as root: sudo make install
# Supports --dry-run: prints system-modifying commands instead of executing.
# Idempotent: safe to re-run after any partial failure.
set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

# Log (real run only; dry-run prints to stdout)
if [ "$DRY_RUN" -eq 0 ]; then
    if [ -w /tmp/phonebroker-install.log ] || [ ! -e /tmp/phonebroker-install.log ]; then
        install -m 644 /dev/null /tmp/phonebroker-install.log 2>/dev/null || true
    fi
    exec > >(tee -a /tmp/phonebroker-install.log) 2>&1
fi

# Step tracking + error trap
CURRENT_STEP=""
# shellcheck disable=SC2154
trap 'rc=$?; if [ $rc -ne 0 ]; then echo ""; echo "Установка прервана на шаге ${CURRENT_STEP}. Откат: sudo make uninstall"; exit $rc; fi' EXIT

set_step() { CURRENT_STEP="$1"; }

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "[DRY-RUN] $*"
    else
        "$@"
    fi
}

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_ROOT/scripts/adb_cmd.sh"
PHONEBROKER_USER="phonebroker"
DATA_DIR="/var/lib/phonebroker"
ETC_DIR="/etc/phonebroker"
OPT_DIR="/opt/phonebroker"
PHONEBROKER_SHELL="$OPT_DIR/scripts/phonebroker-maintenance"
OWNER_USER="${SUDO_USER:-user}"
OWNER_HOME=$(getent passwd "$OWNER_USER" | cut -d: -f6)
SERIAL=$(python3 -c "import yaml; print(yaml.safe_load(open('$REPO_ROOT/config/broker.yaml'))['adb']['serial'])")
IME_TMP="/tmp/phonebroker-default-ime"

log() { echo "[install] $*"; }
die() { echo "[install] ERROR: $*" >&2; exit 1; }

if [ -z "$SERIAL" ] || [ "$SERIAL" = "YOUR_ADB_SERIAL" ]; then
    die "adb.serial is not set in config/broker.yaml — fill in the real ADB serial"
fi

# Extract "type b64 [comment]" from an authorized_keys line, discarding any options prefix.
# Handles: [options] keytype base64 [comment]
_extract_key_parts() {
    local line="$1"
    local key_part
    if [[ "$line" =~ ^(ssh-|ecdsa-|sk-) ]]; then
        key_part="$line"
    else
        key_part="${line#* }"
    fi
    local key_type="${key_part%% *}"
    local rest="${key_part#* }"
    local key_b64="${rest%% *}"
    local comment=""
    if [ "${#rest}" -gt "${#key_b64}" ]; then
        comment="${rest#* }"
    fi
    if [ -n "$comment" ]; then
        printf '%s %s %s' "$key_type" "$key_b64" "$comment"
    else
        printf '%s %s' "$key_type" "$key_b64"
    fi
}

if [ "$DRY_RUN" -eq 1 ]; then
    log "=== DRY RUN MODE (no system changes) ==="
fi

# ═══════════════════════════════════════════════════════════════════════════
# PREFLIGHT (runs in both dry-run and real mode, before any system change)
# ═══════════════════════════════════════════════════════════════════════════

set_step "preflight"
log "Preflight checks:"
printf "%-40s %-20s %s\n" "CHECK" "STATE" "ACTION"
printf "%-40s %-20s %s\n" "-----" "-----" "------"

# 1. User and group
if getent group "$PHONEBROKER_USER" &>/dev/null && getent passwd "$PHONEBROKER_USER" &>/dev/null; then
    printf "%-40s %-20s %s\n" "user+group phonebroker" "exists" "skip"
elif getent group "$PHONEBROKER_USER" &>/dev/null && ! getent passwd "$PHONEBROKER_USER" &>/dev/null; then
    printf "%-40s %-20s %s\n" "user+group phonebroker" "partial (group only)" "create user"
elif ! getent group "$PHONEBROKER_USER" &>/dev/null && ! getent passwd "$PHONEBROKER_USER" &>/dev/null; then
    printf "%-40s %-20s %s\n" "user+group phonebroker" "absent" "create both"
else
    printf "%-40s %-20s %s\n" "user+group phonebroker" "CONFLICT (user w/o group)" "STOP"
    die "User phonebroker exists without group — manual cleanup needed"
fi

# 2. Port 2222 free (or used by our sshd)
if ss -ltn 2>/dev/null | grep -q ':2222 '; then
    if systemctl is-active phonebroker-sshd &>/dev/null; then
        printf "%-40s %-20s %s\n" "port 2222" "phonebroker-sshd" "will restart"
    else
        printf "%-40s %-20s %s\n" "port 2222" "IN USE (foreign)" "STOP"
        die "Port 2222 is in use by a non-phonebroker process. Stop it first."
    fi
else
    printf "%-40s %-20s %s\n" "port 2222" "free" "ok"
fi

# 3. Tailscale IP
TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
if [ -n "$TS_IP" ]; then
    printf "%-40s %-20s %s\n" "tailscale ip -4" "$TS_IP" "ok"
else
    printf "%-40s %-20s %s\n" "tailscale ip -4" "NOT AVAILABLE" "will use 0.0.0.0"
fi

# 4. SSH host key
if [ -f /etc/ssh/ssh_host_ed25519_key ]; then
    printf "%-40s %-20s %s\n" "ssh_host_ed25519_key" "exists" "ok"
elif dpkg -s openssh-server &>/dev/null 2>&1; then
    printf "%-40s %-20s %s\n" "ssh_host_ed25519_key" "MISSING (openssh installed)" "STOP"
    die "openssh-server installed but /etc/ssh/ssh_host_ed25519_key missing"
else
    printf "%-40s %-20s %s\n" "ssh_host_ed25519_key" "absent (openssh not installed)" "will install"
fi

# 5. ADB keys
if [ -f "$OWNER_HOME/.android/adbkey" ] && [ -f "$OWNER_HOME/.android/adbkey.pub" ]; then
    printf "%-40s %-20s %s\n" "adbkey + adbkey.pub" "exist" "ok"
else
    printf "%-40s %-20s %s\n" "adbkey + adbkey.pub" "MISSING" "STOP"
    die "ADB key not found at $OWNER_HOME/.android/adbkey{,.pub}"
fi

# 6. Owner SSH key (in user authorized_keys OR already transferred to phonebroker)
if grep -q 'phone-admin' "$OWNER_HOME/.ssh/authorized_keys" 2>/dev/null; then
    printf "%-40s %-20s %s\n" "phone-admin key" "in user authorized_keys" "ok"
elif [ -f "$DATA_DIR/.ssh/authorized_keys" ] 2>/dev/null; then
    printf "%-40s %-20s %s\n" "phone-admin key" "transferred (phonebroker)" "ok"
elif [ -f "$ETC_DIR/owner_key.orig" ]; then
    printf "%-40s %-20s %s\n" "phone-admin key" "saved in owner_key.orig" "ok"
else
    printf "%-40s %-20s %s\n" "phone-admin key" "NOT FOUND" "STOP"
    die "Owner SSH key (phone-admin) not found in authorized_keys or owner_key.orig"
fi

# 7. ADB device — strategy depends on system state
#   - Dry-run on installed system (user, nft blocks port 5037): HTTP health
#   - Otherwise: adb_cmd (auto-detects runuser vs direct)
if [ "$DRY_RUN" -eq 1 ] && id -u "$PHONEBROKER_USER" &>/dev/null && \
   systemctl is-active phonebroker-adb &>/dev/null 2>&1; then
    ADB_STATE=$(curl -s --max-time 5 http://127.0.0.1:8090/health 2>/dev/null | \
        python3 -c "import json,sys; print(json.load(sys.stdin).get('phone','unavailable'))" 2>/dev/null || echo "unavailable")
else
    ADB_STATE=$(adb_cmd 10 -s "$SERIAL" get-state 2>/dev/null || echo "unavailable")
fi
if [ "$ADB_STATE" = "device" ]; then
    printf "%-40s %-20s %s\n" "adb $SERIAL" "device" "ok"
else
    printf "%-40s %-20s %s\n" "adb $SERIAL" "$ADB_STATE" "STOP"
    die "Phone $SERIAL not available via ADB (state: $ADB_STATE). Connect the phone and retry."
fi

log "Preflight complete."
log ""

# ═══════════════════════════════════════════════════════════════════════════
# PHONE PREP (ADB work via current user-level ADB, before any system change)
# Failure here → stop, no system changes made, no rollback needed.
# ═══════════════════════════════════════════════════════════════════════════

set_step "phone-prep"
log "Phone prep (via adb_cmd):"

# 1. Disable Play Protect verification for ADB installs
adb_cmd -s "$SERIAL" shell settings put global verifier_verify_adb_installs 0
log "  verifier_verify_adb_installs=0"

# 2. ADBKeyBoard: check hash, install if needed, enable IME
PINNED_SHA=$(python3 -c "
import yaml
with open('$REPO_ROOT/config/broker.yaml') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('adbkeyboard', {}).get('sha256', ''))
")
PINNED_URL=$(python3 -c "
import yaml
with open('$REPO_ROOT/config/broker.yaml') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('adbkeyboard', {}).get('url', ''))
")
APK_PATH="$REPO_ROOT/assets/ADBKeyBoard.apk"

# Check if already installed with correct version
INSTALLED=$(adb_cmd -s "$SERIAL" shell dumpsys package com.android.adbkeyboard 2>/dev/null | grep -oP 'lastUpdateTime=\K[0-9]+' | head -1 || echo "")
if [ -f "$APK_PATH" ] && [ -n "$INSTALLED" ]; then
    CACHED_SHA=$(sha256sum "$APK_PATH" | awk '{print $1}')
    if [ "$CACHED_SHA" = "$PINNED_SHA" ]; then
        log "  ADBKeyBoard already installed (SHA match), skipping install"
    else
        log "  ADBKeyBoard version mismatch, reinstalling"
        adb_cmd 120 -s "$SERIAL" install -r "$APK_PATH"
    fi
else
    # Download APK if not cached
    if [ ! -f "$APK_PATH" ]; then
        log "  Downloading ADBKeyBoard APK..."
        mkdir -p "$REPO_ROOT/assets"
        if [ "$DRY_RUN" -ne 1 ]; then
            curl -fsSL -o "$APK_PATH" "$PINNED_URL" || die "ADBKeyBoard download failed"
        fi
    fi
    if [ "$DRY_RUN" -ne 1 ] && [ -f "$APK_PATH" ]; then
        ACTUAL_SHA=$(sha256sum "$APK_PATH" | awk '{print $1}')
        if [ "$ACTUAL_SHA" != "$PINNED_SHA" ]; then
            die "ADBKeyBoard SHA-256 MISMATCH: expected $PINNED_SHA, got $ACTUAL_SHA"
        fi
    fi
    log "  Installing ADBKeyBoard..."
    # Copy APK to world-readable location (phonebroker may need access)
    APK_TMP="/tmp/phonebroker-adbkeyboard.apk"
    if [ "$DRY_RUN" -ne 1 ] && [ -f "$APK_PATH" ]; then
        cp "$APK_PATH" "$APK_TMP"
        chmod 644 "$APK_TMP"
    fi
    # Start install in background (may show MIUI dialog)
    adb_exec_prefix
    if [ "$DRY_RUN" -ne 1 ]; then
        timeout 120 "${ADB_EXEC_PREFIX[@]}" adb -s "$SERIAL" install -r "$APK_TMP" > /tmp/phonebroker-adb-install.log 2>&1 &
        INSTALL_PID=$!
        # Poll for MIUI ADB install dialog (up to 15s)
        for _ in $(seq 1 15); do
            sleep 1
            if ! kill -0 $INSTALL_PID 2>/dev/null; then
                break
            fi
            BTN=$(adb_cmd -s "$SERIAL" shell "uiautomator dump /sdcard/phonebroker_ui.xml" 2>/dev/null && \
                  adb_cmd -s "$SERIAL" shell "cat /sdcard/phonebroker_ui.xml" 2>/dev/null | \
                  python3 -c "
import sys, re
from xml.etree import ElementTree
try:
    root = ElementTree.fromstring(sys.stdin.read())
    for node in root.iter('node'):
        if node.get('text','') == 'Install':
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds',''))
            if m:
                print(f'{(int(m.group(1))+int(m.group(3)))//2} {(int(m.group(2))+int(m.group(4)))//2}')
except: pass
" 2>/dev/null || echo "")
            if [ -n "$BTN" ]; then
                log "  MIUI dialog detected, tapping Install..."
                adb_cmd -s "$SERIAL" shell input tap $BTN
                break
            fi
        done
        wait $INSTALL_PID || die "ADBKeyBoard install failed: $(cat /tmp/phonebroker-adb-install.log)"
        rm -f "$APK_TMP"
    else
        echo "[DRY-RUN] ${ADB_EXEC_PREFIX[*]} timeout 120 adb -s $SERIAL install -r $APK_TMP"
    fi
    log "  ADBKeyBoard installed"
fi
adb_cmd -s "$SERIAL" shell ime enable com.android.adbkeyboard/.AdbIME
log "  ADBKeyBoard IME enabled"

# 3. Save default IME to temp file (written to broker.yaml at step 9)
if [ "$DRY_RUN" -ne 1 ]; then
    DEFAULT_IME=$(adb_cmd -s "$SERIAL" shell settings get secure default_input_method 2>/dev/null || echo "")
    if [ -n "$DEFAULT_IME" ] && [ "$DEFAULT_IME" != "null" ]; then
        echo "$DEFAULT_IME" > "$IME_TMP"
        log "  Default IME saved: $DEFAULT_IME"
    else
        log "  Default IME: not available (leaving empty)"
    fi
else
    adb_cmd -s "$SERIAL" shell settings get secure default_input_method
    log "  Default IME: would be saved from phone"
fi

log "Phone prep complete."
log ""

# ═══════════════════════════════════════════════════════════════════════════
# INSTALL STEPS (all idempotent, system-modifying)
# ═══════════════════════════════════════════════════════════════════════════

# ─── 0. Stop existing services ───────────────────────────────────────────

set_step "0-stop"
log "Step 0: stop existing services"
run systemctl stop phonebroker 2>/dev/null || true
run systemctl stop phonebroker-adb 2>/dev/null || true
run systemctl stop phonebroker-sshd 2>/dev/null || true
run systemctl stop phonebroker-nft 2>/dev/null || true

# ─── 1. User + Group ──────────────────────────────────────────────────────

set_step "1-user"
log "Step 1: user + group"

getent group "$PHONEBROKER_USER" &>/dev/null || run groupadd --system "$PHONEBROKER_USER"
if ! getent passwd "$PHONEBROKER_USER" &>/dev/null; then
    run useradd --system -g "$PHONEBROKER_USER" --shell "$PHONEBROKER_SHELL" \
        --home-dir "$DATA_DIR" --no-create-home "$PHONEBROKER_USER"
else
    log "User already exists, skipping"
fi

# Unlock account for SSH key auth (useradd --system sets '!' in shadow;
# sshd without PAM rejects key login for locked accounts)
run usermod -p '*' "$PHONEBROKER_USER"

# Shell = maintenance script (sshd runs command= via <shell> -c;
# the script ignores args, so any SSH session only runs maintenance)
run usermod -s "$PHONEBROKER_SHELL" "$PHONEBROKER_USER"

PHONEBROKER_UID=$(id -u "$PHONEBROKER_USER" 2>/dev/null || echo "999")
log "phonebroker UID=$PHONEBROKER_UID"

# Post-check: shell field must be the maintenance script
if [ "$DRY_RUN" -eq 0 ]; then
    ACTUAL_SHELL=$(getent passwd "$PHONEBROKER_USER" | cut -d: -f7)
    if [ "$ACTUAL_SHELL" != "$PHONEBROKER_SHELL" ]; then
        die "phonebroker shell is '$ACTUAL_SHELL' (expected '$PHONEBROKER_SHELL')"
    fi
    log "  Post-check: shell=$PHONEBROKER_SHELL OK"
fi

# ─── 2. udev ─────────────────────────────────────────────────────────────

set_step "2-udev"
log "Step 2: udev rule"
run bash -c 'cat > /etc/udev/rules.d/99-phonebroker-adb.rules <<'"'"'UDEOF'"'"'
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ENV{ID_USB_INTERFACES}=="*:ff4201:*", MODE="0660", GROUP="phonebroker"
UDEOF'
run bash -c 'rm -f /etc/udev/rules.d/51-adb.rules'
run udevadm control --reload
run udevadm trigger

# ─── 3. ADB key ──────────────────────────────────────────────────────────

set_step "3-adbkey"
log "Step 3: ADB key"
run mkdir -p "$DATA_DIR/.android"
run cp "$OWNER_HOME/.android/adbkey" "$DATA_DIR/.android/adbkey"
run cp "$OWNER_HOME/.android/adbkey.pub" "$DATA_DIR/.android/adbkey.pub"
run chown -R "$PHONEBROKER_USER:$PHONEBROKER_USER" "$DATA_DIR/.android"
run chmod 700 "$DATA_DIR/.android"
run chmod 600 "$DATA_DIR/.android/adbkey"
run chmod 644 "$DATA_DIR/.android/adbkey.pub"

# ─── 4. Data dir ─────────────────────────────────────────────────────────

set_step "4-datadir"
log "Step 4: data directory"
run mkdir -p "$DATA_DIR/screenshots"
run chown -R "$PHONEBROKER_USER:$PHONEBROKER_USER" "$DATA_DIR"
run chmod 700 "$DATA_DIR"

# ─── 5. nftables ─────────────────────────────────────────────────────────

set_step "5-nftables"
log "Step 5: nftables"
run mkdir -p /etc/nftables
run bash -c "cat > /etc/nftables/phonebroker.nft <<NFT
table inet phonebroker {
    chain output {
        type filter hook output priority filter;
        meta skuid $PHONEBROKER_UID tcp dport { 5037, 27183 } accept
        tcp dport { 5037, 27183 } limit rate 6/minute log prefix \"phonebroker-adb-deny: \" flags skuid
        tcp dport { 5037, 27183 } drop
    }
}
NFT"

# ─── 6. systemd units ────────────────────────────────────────────────────

set_step "6-systemd"
log "Step 6: systemd units"
run cp "$REPO_ROOT/systemd/phonebroker-nft.service" /etc/systemd/system/
run cp "$REPO_ROOT/systemd/phonebroker-adb.service" /etc/systemd/system/
run cp "$REPO_ROOT/systemd/phonebroker.service" /etc/systemd/system/
run cp "$REPO_ROOT/systemd/phonebroker-sshd.service" /etc/systemd/system/
run systemctl daemon-reload
run systemctl enable phonebroker-nft.service
run systemctl enable phonebroker-adb.service
run systemctl enable phonebroker.service
run systemctl enable phonebroker-sshd.service

# ─── 6b. sshd_config ─────────────────────────────────────────────────────

set_step "6b-sshd"
log "Step 6b: sshd_config"
run mkdir -p "$ETC_DIR"
if [ -n "$TS_IP" ]; then
    run bash -c "sed 's/^ListenAddress .*/ListenAddress ${TS_IP}/' '$REPO_ROOT/config/sshd_config' > '$ETC_DIR/sshd_config'"
else
    run bash -c "cp '$REPO_ROOT/config/sshd_config' '$ETC_DIR/sshd_config'"
fi
run chown root:"$PHONEBROKER_USER" "$ETC_DIR/sshd_config"
run chmod 640 "$ETC_DIR/sshd_config"

# ─── 7. Code ─────────────────────────────────────────────────────────────

set_step "7-code"
log "Step 7: deploy code"
run mkdir -p "$OPT_DIR"
run rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude '.mypy_cache' --exclude '.ruff_cache' \
    --exclude 'assets' --exclude '.env' \
    "$REPO_ROOT/" "$OPT_DIR/"
if [ "$DRY_RUN" -eq 1 ] || [ ! -d "$OPT_DIR/.venv" ]; then
    run python3 -m venv "$OPT_DIR/.venv"
fi
run "$OPT_DIR/.venv/bin/pip" install -e "$OPT_DIR" --quiet
run chown -R "$PHONEBROKER_USER:$PHONEBROKER_USER" "$OPT_DIR"

# ─── 8. /etc/phonebroker/env (tokens) ───────────────────────────────────

set_step "8-env"
log "Step 8: env + tokens"
run mkdir -p "$ETC_DIR"
if [ ! -f "$ETC_DIR/env" ]; then
    run bash -c "echo '# PhoneBroker service secrets' > '$ETC_DIR/env'"
fi

_gen_token() { python3 -c "import secrets; print(secrets.token_urlsafe(32))"; }
_mask_token() {
    if [ "$DRY_RUN" -eq 1 ]; then echo "<generated>"; else _gen_token; fi
}

if ! grep -q '^PHONEBROKER_TOKEN_OWNER=' "$ETC_DIR/env" 2>/dev/null; then
    run bash -c "echo 'PHONEBROKER_TOKEN_OWNER=$(_mask_token)' >> '$ETC_DIR/env'"
    log "  Generated PHONEBROKER_TOKEN_OWNER"
fi

while IFS= read -r client; do
    [ -z "$client" ] && continue
    VAR="PHONEBROKER_TOKEN_$(echo "$client" | tr 'a-z' 'A-Z')"
    if ! grep -q "^${VAR}=" "$ETC_DIR/env" 2>/dev/null; then
        run bash -c "echo '${VAR}=$(_mask_token)' >> '$ETC_DIR/env'"
        log "  Generated ${VAR}"
    fi
done < <(python3 -c "
import yaml
try:
    with open('$REPO_ROOT/config/broker.yaml') as f:
        cfg = yaml.safe_load(f)
    for c in cfg.get('clients', {}):
        print(c)
except Exception:
    pass
" 2>/dev/null || true)

run chown root:"$PHONEBROKER_USER" "$ETC_DIR/env"
run chmod 640 "$ETC_DIR/env"

# ─── 9. /etc/phonebroker/broker.yaml ────────────────────────────────────

set_step "9-brokeryaml"
log "Step 9: broker.yaml"
run cp "$REPO_ROOT/config/broker.yaml" "$ETC_DIR/broker.yaml"
# Write IME from phone prep
if [ -f "$IME_TMP" ]; then
    DEFAULT_IME=$(cat "$IME_TMP")
    run sed -i "s|system_default: \"\"|system_default: \"${DEFAULT_IME}\"|" "$ETC_DIR/broker.yaml"
    log "  IME written: $DEFAULT_IME"
fi
run chown root:"$PHONEBROKER_USER" "$ETC_DIR/broker.yaml"
run chmod 640 "$ETC_DIR/broker.yaml"

# ─── 10. SSH key ─────────────────────────────────────────────────────────

set_step "10-sshkey"
log "Step 10: SSH key"
run mkdir -p "$DATA_DIR/.ssh"

if [ -f "$OWNER_HOME/.ssh/authorized_keys" ] && grep -q 'phone-admin' "$OWNER_HOME/.ssh/authorized_keys" 2>/dev/null; then
    # Save original (only on first run)
    if [ ! -f "$ETC_DIR/owner_key.orig" ]; then
        ORIGINAL_KEY=$(grep 'phone-admin' "$OWNER_HOME/.ssh/authorized_keys" | head -1)
        run bash -c "echo '$ORIGINAL_KEY' > '$ETC_DIR/owner_key.orig'"
        run chown root:"$PHONEBROKER_USER" "$ETC_DIR/owner_key.orig"
        run chmod 640 "$ETC_DIR/owner_key.orig"
    fi

    if [ "$DRY_RUN" -eq 0 ]; then
        # Build forced-command authorized_keys (single options field only)
        rm -f "$DATA_DIR/.ssh/authorized_keys"
        while IFS= read -r keyline; do
            [ -z "$keyline" ] && continue
            read -r KEY_TYPE KEY_B64 KEY_COMMENT <<< "$(_extract_key_parts "$keyline")"
            {
                printf 'command="/opt/phonebroker/scripts/phonebroker-maintenance",restrict,port-forwarding,permitopen="127.0.0.1:5037",permitopen="127.0.0.1:27183" %s %s' "$KEY_TYPE" "$KEY_B64"
                [ -n "$KEY_COMMENT" ] && printf ' %s' "$KEY_COMMENT"
                printf '\n'
            } >> "$DATA_DIR/.ssh/authorized_keys"
        done < <(grep "phone-admin" "$OWNER_HOME/.ssh/authorized_keys")

        # Remove from user
        grep -v "phone-admin" "$OWNER_HOME/.ssh/authorized_keys" > /tmp/.ak_tmp || true
        cat /tmp/.ak_tmp > "$OWNER_HOME/.ssh/authorized_keys"
        rm -f /tmp/.ak_tmp

        log "  Key transferred with forced command"

        # Post-check: key line must be valid, fingerprint must match owner_key.orig
        ssh-keygen -lf "$DATA_DIR/.ssh/authorized_keys" >/dev/null 2>&1 || {
            die "authorized_keys is not a valid public key file: $(ssh-keygen -lf "$DATA_DIR/.ssh/authorized_keys" 2>&1)"
        }
        if [ -f "$ETC_DIR/owner_key.orig" ]; then
            FP_NEW=$(ssh-keygen -lf "$DATA_DIR/.ssh/authorized_keys" | awk '{print $2}')
            FP_ORIG=$(ssh-keygen -lf "$ETC_DIR/owner_key.orig" | awk '{print $2}')
            if [ "$FP_NEW" != "$FP_ORIG" ]; then
                die "Key fingerprint mismatch: deployed=$FP_NEW original=$FP_ORIG"
            fi
            log "  Post-check: fingerprint matches owner_key.orig OK"
        fi
    else
        log "  [DRY-RUN] Key would be transferred (value not shown)"
    fi
else
    log "  SKIP: phone-admin key not found or already transferred"
fi

run chown -R "$PHONEBROKER_USER:$PHONEBROKER_USER" "$DATA_DIR/.ssh"
run chmod 700 "$DATA_DIR/.ssh"
run chmod 600 "$DATA_DIR/.ssh/authorized_keys" 2>/dev/null || true

# ─── 11. Disable user-level ADB ─────────────────────────────────────────

set_step "11-useradb"
log "Step 11: disable user-level ADB"
USER_UID=$(id -u "$OWNER_USER" 2>/dev/null || echo "")
if [ -n "$USER_UID" ]; then
    run runuser -u "$OWNER_USER" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        systemctl --user disable --now adb.service 2>/dev/null || \
        log "  User ADB service not found (OK)"
fi

# ─── 12. Start services ──────────────────────────────────────────────────

set_step "12-start"
log "Step 12: start services"
run systemctl start phonebroker-nft
run systemctl start phonebroker-sshd
run systemctl start phonebroker-adb
if [ "$DRY_RUN" -eq 0 ]; then
    sleep 2
fi
run systemctl start phonebroker
log "  Services started (sshd on port 2222)"

# Post-check: verify phonebroker account is unlocked for SSH
if [ "$DRY_RUN" -eq 0 ]; then
    SHADOW_FIELD=$(getent shadow "$PHONEBROKER_USER" | cut -d: -f2)
    if [ "$SHADOW_FIELD" != "*" ]; then
        die "phonebroker shadow password field is '$SHADOW_FIELD' (expected '*'). Run: usermod -p '*' phonebroker"
    fi
    log "  Post-check: shadow field='*' OK"
fi

# ─── Done ────────────────────────────────────────────────────────────────

set_step "done"
log "Install complete."
log ""
log "Next steps:"
log "  1. Laptop (PowerShell): scp -P 22 $OWNER_USER@$(hostname):$REPO_ROOT/tools/windows/update-phone.ps1 C:\\Tools\\phone\\; if (\$?) { powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Tools\\phone\\update-phone.ps1 -Serial $SERIAL }"
log "  2. Install platform apps on phone"
log "  3. sudo make platforms"
log "  4. sudo make acceptance"
log ""
log "Log: /tmp/phonebroker-install.log"
