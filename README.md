# PhoneBroker

**Languages:** English | [Русский](README.ru.md)

<p align="left">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg">
</p>

Single-phone ADB broker service. Mediates exclusive access to one Android phone
for client projects via a lease/queue API with per-project tokens, per-platform
rate limits, and a whitelisted set of ADB operations.

## Features

- **Exclusive leases** — one active lease at a time; other requests queue with
  priority (`interactive` | `background`) and a starvation guard.
- **Per-project Bearer tokens** — each client project gets its own token
  (`PHONEBROKER_TOKEN_*`); the owner token is rejected on project endpoints.
- **Per-platform limits** — minimum interval between leases and a daily cap,
  configurable per platform and per priority.
- **Whitelisted ADB operations only** — no raw `adb shell` through the API:
  launch, tap, tap_selector, swipe, text, keyevent, screenshot, ui_dump, wait_for.
- **Maintenance mode** — the owner can pause all client traffic
  (`/maintenance/*`) and drive the phone directly.
- **Hardened host integration** — dedicated `phonebroker` system user,
  nftables rules that restrict ADB ports to that user, a forced-command SSH
  daemon on port 2222 for owner access, systemd units, udev rule.
- **Platform package sync** — `make platforms` matches installed phone
  packages to configured platforms by keyword and keeps the binding up to date.

## Requirements

- Linux host (Debian/Ubuntu tested) with `systemd`, `nftables`, `openssh-server`
- Python 3.12+
- ADB (`adb` on PATH) and one Android phone connected via USB with ADB enabled
- `sudo` for installation
- Optional: Tailscale on the host — the installer pins the private sshd to the
  Tailscale IP when available; otherwise it listens on `0.0.0.0`
- Optional (owner convenience): a Windows laptop with PowerShell 5.1+,
  `scrcpy`, and `adb` for screen access

## Quick start

```bash
git clone https://github.com/alexolvin/phonebroker.git
cd phonebroker

# 1. Create config/broker.local.yaml (gitignored) with the phone's ADB serial
#    (see `adb devices`):
#      adb:
#        serial: "YOUR_ADB_SERIAL"

# 2. Install (system user, udev, nftables, systemd, ADB key, tokens, ADBKeyBoard):
sudo make install
# Log: /tmp/phonebroker-install.log

# 3. On the laptop (PowerShell) — SSH config + phone.ps1 + verification:
#    the installer prints the exact scp + powershell commands

# 4. Install the platform apps on the phone, then bind packages:
sudo make platforms
# Log: /tmp/phonebroker-platforms.log

# 5. Run acceptance tests T1–T12:
sudo make acceptance
# Log: /tmp/phonebroker-acceptance.log
```

The service listens on `127.0.0.1:8090`.

## Configuration

The repository ships `config/broker.yaml` with public defaults. Local values
that must not be published (real ADB serial, client projects, owner SSH key
comment) live in **`config/broker.local.yaml`**, which is gitignored.
`make install` merges the two into `/etc/phonebroker/broker.yaml`, the single
runtime source:

```yaml
# config/broker.local.yaml (gitignored — example)
adb:
  serial: "YOUR_ADB_SERIAL"
ssh:
  key_comment: "your-key-comment"   # comment of the owner key in authorized_keys
clients:
  client_a:
    env_file: "/path/to/client/project/.env"
```

| Key | Purpose | Default |
|---|---|---|
| `port` | API port | `8090` |
| `adb.serial` | ADB serial of the phone — **set in `config/broker.local.yaml`** | `YOUR_ADB_SERIAL` |
| `heartbeat_timeout_s` | Lease is requeued when the client stops heartbeating | `60` |
| `check_interval_s` | Queue re-check interval | `2` |
| `starvation_threshold` | Queued lease is promoted after N checks | `5` |
| `platforms.<id>.package` | Package name bound to the platform | `""` |
| `platforms.<id>.keywords` | Keywords for automatic package matching | `[]` |
| `platforms.<id>.limits` | Per-platform limit overrides | `{}` |
| `defaults.background` / `defaults.interactive` | `min_interval_s`, `max_daily_leases` | see file |
| `clients.<name>` | One entry per client project (local config); a token is generated for each | `{}` |
| `data_dir` | SQLite + screenshots | `/var/lib/phonebroker` |

**Tokens.** `make install` generates `PHONEBROKER_TOKEN_OWNER` and one
`PHONEBROKER_TOKEN_<NAME>` per client into `/etc/phonebroker/env`
(root:phonebroker, 640). Rotate a single token with:

```bash
sudo make token PROJECT=client_a
```

## Usage

All project endpoints require `Authorization: Bearer <token>`.

```bash
# Acquire a lease (201 active, 202 waiting)
curl -X POST http://127.0.0.1:8090/lease \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"platform":"vinted","operation":"listing","priority":"background","max_duration_s":600}'

# Keep the lease alive
curl -X POST http://127.0.0.1:8090/lease/<id>/heartbeat -H "Authorization: Bearer $TOKEN"

# Run a whitelisted operation
curl -X POST http://127.0.0.1:8090/lease/<id>/ops/launch -H "Authorization: Bearer $TOKEN"

# Complete the lease
curl -X DELETE http://127.0.0.1:8090/lease/<id> -H "Authorization: Bearer $TOKEN"
```

**Endpoints (18):**

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service + phone state |
| POST | `/lease` | Request a lease (201/202) |
| GET | `/lease/{id}` | Lease status |
| DELETE | `/lease/{id}` | Complete an active lease |
| POST | `/lease/{id}/heartbeat` | Heartbeat |
| GET | `/leases` | Project's leases |
| GET | `/lease/{id}/history` | Operation journal |
| POST | `/maintenance/start` | Enter maintenance (owner) |
| POST | `/maintenance/renew` | Renew maintenance (owner) |
| POST | `/maintenance/end` | End maintenance (owner) |
| POST | `/lease/{id}/ops/launch` | Launch the platform package |
| POST | `/lease/{id}/ops/tap` | Tap at `x`,`y` |
| POST | `/lease/{id}/ops/tap_selector` | Tap a UI selector |
| POST | `/lease/{id}/ops/swipe` | Swipe `x1,y1 → x2,y2` |
| POST | `/lease/{id}/ops/text` | Type text (Unicode) |
| POST | `/lease/{id}/ops/keyevent` | Send a key event |
| POST | `/lease/{id}/ops/screenshot` | Screenshot (base64) |
| POST | `/lease/{id}/ops/ui_dump` | UI hierarchy dump |
| POST | `/lease/{id}/ops/wait_for` | Wait for a selector |

**Management:**

```bash
sudo make token PROJECT=client_a   # rotate a token
sudo make platform ID=olx_pl PACKAGE=pl.tablica   # bind a package
sudo make platform ID=olx_pl PACKAGE=-            # unbind
sudo make uninstall                # full rollback
```

## Operations

### Owner access («Телефон» shortcut)

The owner works with the phone directly through maintenance mode, from the
Windows laptop:

1. **One-time setup.** `make install` prints an scp command that copies
   `tools/windows/update-phone.ps1` to `C:\Tools\phone\` on the laptop.
   Then run it once in PowerShell:
   ```powershell
   .\update-phone.ps1 -Serial <adb-serial>
   ```
   It updates the SSH config (`Host phone`: `User phonebroker`, `Port 2222`),
   regenerates `C:\Tools\phone\phone.ps1`, and runs T11 verification.
   Create a desktop shortcut (e.g. «Телефон») that runs
   `C:\Tools\phone\phone.ps1`.
2. **Daily use.** Double-click the shortcut: an SSH session (forced command)
   starts maintenance mode and an ADB tunnel (5038 → 5037), and scrcpy opens
   the phone screen. Closing the scrcpy window ends maintenance — the phone
   is reset and platform packages are re-synced (a sync summary window is
   shown if anything changed).

### Adding a platform

- **Automatic.** Every time maintenance ends, the installed phone packages
  are matched to configured platforms by keyword and the bindings are updated.
- **Manual.**
  ```bash
  sudo make platforms                             # scan + bind all
  sudo make platform ID=olx_pl PACKAGE=pl.tablica # bind one
  sudo make platform ID=olx_pl PACKAGE=-          # unbind
  ```

### Adding a client project

1. Add an entry to `config/broker.local.yaml`:
   ```yaml
   clients:
     client_b:
       env_file: "/path/to/client_b/.env"
   ```
2. Re-run `sudo make install` (the local config is re-merged into
   `/etc/phonebroker/broker.yaml`).
3. Generate the token:
   ```bash
   sudo make token PROJECT=client_b
   ```
   `PHONEBROKER_TOKEN_CLIENT_B` is written to `/etc/phonebroker/env` and to
   the client's `.env`; the service is restarted.

### Updating

```bash
sudo make install   # idempotent — re-merges config, updates units and scripts
```

On the laptop, re-run `update-phone.ps1 -Serial <adb-serial>` to refresh the
SSH config and `phone.ps1`.

### Rollback

```bash
sudo make uninstall
```

Stops and removes the systemd units and the nftables table, restores udev
(`GROUP=plugdev`) and user-level ADB, returns the original SSH key, and
removes `/etc/phonebroker`, `/opt/phonebroker`, `/var/lib/phonebroker`, and
the `phonebroker` user. Log: `/tmp/phonebroker-uninstall.log`.

## Project structure

```text
config/           broker.yaml defaults, sshd_config, token ref map
scripts/          install/uninstall, platform binding, checks, pre-commit hook
src/phonebroker/  FastAPI app: api/, lease, queue, adb, maintenance, packages
systemd/          phonebroker, phonebroker-adb, phonebroker-sshd, phonebroker-nft
tests/            unit tests + acceptance suite T1–T12
tools/windows/    owner laptop setup (PowerShell)
```

## Testing

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

make test        # unit tests
make gates       # hardcode / secrets / powershell / adb-usage checks + shellcheck
make acceptance  # T1–T12 against the installed system (requires the phone)
```

## Security

No secrets are stored in the repository; tokens live in
`/etc/phonebroker/env` (root:phonebroker, 640) and are resolved at runtime.
The real ADB serial, client projects, and owner key reference live in the
gitignored `config/broker.local.yaml`.
ADB ports (5037, 27183) are restricted by nftables to the `phonebroker` user.
Report vulnerabilities via [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
