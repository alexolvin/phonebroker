# Contributing to PhoneBroker

Thanks for your interest. This project runs on a single host with one physical
phone, so changes are best validated against a real installation.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Workflow

1. Fork and create a topic branch from `main`.
2. Make your change.
3. Run the gates — all must pass:

   ```bash
   make test    # unit tests
   make gates   # hardcode / secrets / powershell / adb-usage checks + shellcheck
   ```

4. If you touched installation or host integration, validate with
   `sudo scripts/install.sh --dry-run` on a throwaway Debian/Ubuntu VM.
5. Open a pull request.

## Conventions

- Shell scripts go through `adb_cmd` from `scripts/adb_cmd.sh` — never call
  `adb` directly (enforced by `make gates`).
- No hardcoded serials, paths, hostnames, or tokens in code, scripts, or tests.
  Use `config/broker.yaml` or `/etc/phonebroker/broker.yaml`.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, …).
- Keep `README.md` (English) and `README.ru.md` (Russian) in sync; section
  order must stay identical.

## Russian

См. [README.ru.md](README.ru.md). Правила те же; документация ведётся на
английском (каноническая версия) и русском (полный эквивалент).
