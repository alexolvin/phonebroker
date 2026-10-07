#!/usr/bin/env python3
"""check_secrets: detect forbidden secret patterns in source files.

Scans src/, scripts/, tests/, config/ for:
1. DBMS connection strings (except sqlite:)
2. @127.0.0.1 / @localhost
3. password=, api_key=, secret_key=, secret=, token=<8+chars>
4. Quoted hex literal >= 24 chars
Lines with 'SecretRef:' are exempt.

Exit 0 = pass, 1 = fail.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ["src", "scripts", "tests", "config"]
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".venv", ".ruff_cache"}
IGNORED_FILES = {"check_secrets.py", "test_check_secrets.py"}

DBMS_RE = re.compile(
    r"(?:postgres(?:ql)?|mysql|mariadb|mongodb|redis|oracle|mssql)://", re.I
)
AT_HOST_RE = re.compile(r"@(?:127\.0\.0\.1|localhost)\b")
PASSWORD_RE = re.compile(r"""password\s*=\s*['"][^'"]+['"]""", re.I)
API_KEY_RE = re.compile(r"""(?:api_key|secret_key)\s*=\s*['"][^'"]+['"]""", re.I)
SECRET_RE = re.compile(r"""secret\s*=\s*['"][^'"]+['"]""", re.I)
TOKEN_RE = re.compile(r"""token\s*=\s*['"]([^'$].{7,})['"]""", re.I)
HEX_RE = re.compile(r"""['"]([0-9a-fA-F]{24,})['"]""")
HEX_EXEMPT_RE = re.compile(r"""(?:sha256|sha1|sha512|hash|fingerprint|checksum)\s*[:=]""", re.I)


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations

    for lineno, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "SecretRef:" in line:
            continue

        if DBMS_RE.search(line) and "sqlite:" not in line:
            violations.append(f"{path}:{lineno}: DBMS connection string")
        if AT_HOST_RE.search(line):
            violations.append(f"{path}:{lineno}: @127.0.0.1/@localhost")
        if PASSWORD_RE.search(line):
            violations.append(f"{path}:{lineno}: password=")
        if API_KEY_RE.search(line):
            violations.append(f"{path}:{lineno}: api_key/secret_key=")
        if SECRET_RE.search(line):
            violations.append(f"{path}:{lineno}: secret=")
        m = TOKEN_RE.search(line)
        if m and m.group(1) not in ("", "{}"):
            violations.append(f"{path}:{lineno}: token=<value>")
        if HEX_RE.search(line) and not HEX_EXEMPT_RE.search(line):
            violations.append(f"{path}:{lineno}: hex literal >= 24")

    return violations


def main() -> int:
    all_violations: list[str] = []

    for dir_name in TARGET_DIRS:
        dir_path = ROOT / dir_name
        if not dir_path.is_dir():
            continue
        for f in sorted(dir_path.rglob("*")):
            if not f.is_file():
                continue
            if any(part in IGNORED_DIRS for part in f.parts):
                continue
            if f.name in IGNORED_FILES:
                continue
            all_violations.extend(check_file(f))

    if all_violations:
        print(f"SECRETS GATE FAILED! Found {len(all_violations)} violation(s):", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    print("Secrets check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
