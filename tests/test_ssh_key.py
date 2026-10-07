"""Unit tests for _extract_key_parts in scripts/install.sh."""

import subprocess
from pathlib import Path

INSTALL_SH = Path(__file__).parent.parent / "scripts" / "install.sh"


def _get_func_source() -> str:
    """Extract the _extract_key_parts function definition from install.sh."""
    content = INSTALL_SH.read_text()
    marker = "_extract_key_parts() {"
    start = content.index(marker)
    depth = 0
    for i, ch in enumerate(content[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return content[start : i + 1]
    raise AssertionError("Could not find closing brace of _extract_key_parts")


FUNC_SRC = _get_func_source()


def _extract(line: str) -> str:
    """Call _extract_key_parts via bash subprocess."""
    code = f'{FUNC_SRC}\n_extract_key_parts {line!r}'
    result = subprocess.run(
        ["bash", "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"rc={result.returncode}: {result.stderr}"
    return result.stdout.rstrip("\n")


def test_no_options():
    """Plain key line without options."""
    line = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey phone-admin"
    assert _extract(line) == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey phone-admin"


def test_restrict_options():
    """Key line with restrict,port-forwarding options prefix."""
    line = 'restrict,port-forwarding,permitopen="127.0.0.1:5037" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey phone-admin'
    assert _extract(line) == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey phone-admin"


def test_existing_command():
    """Key line with an already-present command= field (from previous install)."""
    line = 'command="/opt/phonebroker/scripts/phonebroker-maintenance",restrict ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey phone-admin'
    assert _extract(line) == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey phone-admin"


def test_no_comment():
    """Key line without a comment field."""
    line = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey"
    assert _extract(line) == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey"


def test_ecdsa_key():
    """ECDSA key type."""
    line = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYExampleKey owner@host"
    assert _extract(line) == "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYExampleKey owner@host"
