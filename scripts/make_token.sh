#!/usr/bin/env bash
# Generate a project token — run as root: sudo make token PROJECT=<name>
set -euo pipefail

PROJECT="${1:?Usage: make token PROJECT=<name>}"
ETC_ENV="/etc/phonebroker/env"
BROKER_YAML="/etc/phonebroker/broker.yaml"
VAR_NAME="PHONEBROKER_TOKEN_$(echo "$PROJECT" | tr 'a-z' 'A-Z')"

log() { echo "[token] $*"; }
die() { echo "[token] ERROR: $*" >&2; exit 1; }

[ -f "$ETC_ENV" ] || die "$ETC_ENV not found — run 'sudo make install' first"
[ -f "$BROKER_YAML" ] || die "$BROKER_YAML not found"

# Generate token
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Write to /etc/phonebroker/env
if grep -q "^${VAR_NAME}=" "$ETC_ENV"; then
    sed -i "s|^${VAR_NAME}=.*|${VAR_NAME}=${TOKEN}|" "$ETC_ENV"
else
    # Remove comment line if present, then append
    sed -i "/^# *${VAR_NAME}=/d" "$ETC_ENV"
    echo "${VAR_NAME}=${TOKEN}" >> "$ETC_ENV"
fi

# Write to client .env (preserving owner and permissions)
ENV_FILE=$(python3 -c "
import yaml
with open('$BROKER_YAML') as f:
    cfg = yaml.safe_load(f)
clients = cfg.get('clients', {})
if '$PROJECT' in clients:
    print(clients['$PROJECT'].get('env_file', ''))
else:
    print('')
")

if [ -n "$ENV_FILE" ]; then
    if [ -f "$ENV_FILE" ]; then
        # Preserve owner and permissions
        FILE_OWNER=$(stat -c '%U:%G' "$ENV_FILE")
        FILE_MODE=$(stat -c '%a' "$ENV_FILE")
        if grep -q "^${VAR_NAME}=" "$ENV_FILE"; then
            sed -i "s|^${VAR_NAME}=.*|${VAR_NAME}=${TOKEN}|" "$ENV_FILE"
        else
            echo "${VAR_NAME}=${TOKEN}" >> "$ENV_FILE"
        fi
        chown "$FILE_OWNER" "$ENV_FILE"
        chmod "$FILE_MODE" "$ENV_FILE"
        log "Client .env updated: $ENV_FILE"
    else
        log "WARNING: client env file not found: $ENV_FILE"
    fi
else
    log "No client env_file configured for project '$PROJECT'"
fi

# Restart service
systemctl restart phonebroker

log "Token generated for project '$PROJECT' (value not displayed)."
