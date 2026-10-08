.PHONY: install uninstall token platforms platform run test gates acceptance clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install -e ".[dev]"

# Run scripts directly when already root (sudo make …) to preserve SUDO_USER
# from the owner's outer sudo; a nested sudo would re-attribute the run.
install:
	@if [ "$$(id -u)" = "0" ]; then scripts/install.sh; else sudo scripts/install.sh; fi

uninstall:
	@if [ "$$(id -u)" = "0" ]; then scripts/uninstall.sh; else sudo scripts/uninstall.sh; fi

token:
	@test -n "$(PROJECT)" || (echo "Usage: make token PROJECT=<name>" && exit 1)
	@if [ "$$(id -u)" = "0" ]; then scripts/make_token.sh "$(PROJECT)"; else sudo scripts/make_token.sh "$(PROJECT)"; fi

platforms:
	@if [ "$$(id -u)" = "0" ]; then scripts/make_platforms.sh; else sudo scripts/make_platforms.sh; fi

platform:
	@test -n "$(ID)" || (echo "Usage: make platform ID=<name> PACKAGE=<package>" && exit 1)
	@test -n "$(PACKAGE)" || (echo "Usage: make platform ID=<name> PACKAGE=<package> (or - to unbind)" && exit 1)
	@if [ "$$(id -u)" = "0" ]; then scripts/make_platform.sh "$(ID)" "$(PACKAGE)"; else sudo scripts/make_platform.sh "$(ID)" "$(PACKAGE)"; fi

run: $(VENV)
	$(PYTHON) -m uvicorn phonebroker.main:app --host 127.0.0.1 --port 8090 --workers 1

test: $(VENV)
	$(VENV)/bin/pytest

gates:
	python3 scripts/check_hardcode.py
	python3 scripts/check_secrets.py
	python3 scripts/check_powershell.py
	python3 scripts/check_adb_usage.py
	python3 scripts/check_adb_shell.py
	$(VENV)/bin/shellcheck -S warning scripts/*.sh scripts/phonebroker-maintenance tests/acceptance/*.sh
	@PWSH=$$(command -v pwsh 2>/dev/null || echo "$$HOME/.local/opt/pwsh/pwsh"); \
	if [ -x "$$PWSH" ]; then $$PWSH -NoProfile -File tests/test_adb_check.ps1; \
	else echo "ERROR: pwsh not found — install to ~/.local/opt/pwsh"; exit 1; fi

acceptance:
	bash tests/acceptance/run_all.sh

clean:
	rm -rf .venv __pycache__ .pytest_cache .mypy_cache .ruff_cache
