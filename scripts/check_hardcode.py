#!/usr/bin/env python3
"""check_hardcode: detect forbidden literals in source code.

Rules:
1. Hardcoded URL / e-mail / secret assignment in src/ .py (loopback exempt)
2. Non-loopback IPv4 in URL (src + scripts)
3. Absolute /snap/ or /home/ paths in .py (no exemption)
4. Secret/token literal in every git-tracked file (20+ chars, mixed case+digit)

Exit 0 = pass, 1 = fail.
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

URL_RE = re.compile(r"""(?:https?|ftp)://[^\s"'<>)]+""", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
SECRET_ASSIGN_RE = re.compile(
    r"""(?:api_key|secret_key|auth_token|token|secret|password)\s*=\s*['"][^'"]{8,}['"]""",
    re.I,
)
IP_URL_RE = re.compile(r"://(\d{1,3}(?:\.\d{1,3}){3})")
ABS_PATH_RE = re.compile(r"""["'](/(?:snap|home)/[^"']*)["']""")
SECRET_LITERAL_RE = re.compile(
    r"""(?:token|secret|password|passwd|credential|bearer|api_key|access_key|
         private_key|session)\s*[=:]\s*['"]([A-Za-z0-9+/=_\-]{20,})['"]""",
    re.I | re.X,
)
BEARER_RE = re.compile(r"Bearer\s+([A-Za-z0-9+/=_\-]{20,})")


def _is_loopback_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        if parts.username or parts.password:
            return False
        return parts.hostname in LOOPBACK_HOSTS
    except ValueError:
        return False


def _looks_like_real_secret(val: str) -> bool:
    """Must have mixed upper+lower+digit to be a real secret (not a placeholder)."""
    has_upper = any(c.isupper() for c in val)
    has_lower = any(c.islower() for c in val)
    has_digit = any(c.isdigit() for c in val)
    return has_upper and has_lower and has_digit


def check_file(path: Path, is_src: bool, is_scripts: bool) -> list[str]:
    violations: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations

    for lineno, line in enumerate(content.splitlines(), 1):
        if line.strip().startswith("#"):
            continue

        # Rule 1: URL/email/secret in src/
        if is_src:
            for m in URL_RE.finditer(line):
                if not _is_loopback_url(m.group()):
                    violations.append(f"{path}:{lineno}: hardcoded URL {m.group()[:50]}")
            if EMAIL_RE.search(line):
                violations.append(f"{path}:{lineno}: hardcoded email")
            if SECRET_ASSIGN_RE.search(line):
                violations.append(f"{path}:{lineno}: secret assignment")

        # Rule 2: non-loopback IP in URL (src + scripts)
        if is_src or is_scripts:
            for m in IP_URL_RE.finditer(line):
                ip = m.group(1)
                if not (ip.startswith("127.") or ip == "0.0.0.0"):
                    violations.append(f"{path}:{lineno}: non-loopback IP {ip} in URL")

        # Rule 3: absolute /snap/ or /home/ paths
        for m in ABS_PATH_RE.finditer(line):
            violations.append(f"{path}:{lineno}: absolute path {m.group(1)}")

    return violations


def check_git_tracked_files() -> list[str]:
    """Rule 4: secret literals in every git-tracked file."""
    violations: list[str] = []
    try:
        files = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT
        ).stdout.splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return violations

    for filepath in files:
        full = ROOT / filepath
        if not full.is_file():
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(content.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for m in SECRET_LITERAL_RE.finditer(line):
                val = m.group(1)
                if _looks_like_real_secret(val):
                    violations.append(f"{filepath}:{lineno}: secret literal")
            for m in BEARER_RE.finditer(line):
                val = m.group(1)
                if _looks_like_real_secret(val):
                    violations.append(f"{filepath}:{lineno}: Bearer token literal")

    return violations


def main() -> int:
    all_violations: list[str] = []

    # Scan src/ and scripts/ .py files
    for directory, is_src, is_scripts in [(SRC, True, False), (SCRIPTS, False, True)]:
        if not directory.is_dir():
            continue
        for py_file in sorted(directory.rglob("*.py")):
            if any(part in ("__pycache__", ".venv", ".mypy_cache") for part in py_file.parts):
                continue
            all_violations.extend(check_file(py_file, is_src, is_scripts))

    # Rule 4: all git-tracked files
    all_violations.extend(check_git_tracked_files())

    if all_violations:
        print("HARDCODE CHECK FAILED! Found forbidden literals:", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    py_count = len(list(SRC.rglob("*.py"))) + len(list(SCRIPTS.rglob("*.py")))
    # Count git-tracked files for the message
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT
        ).stdout.splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        tracked = []
    print(f"Hardcode check passed: {py_count} .py + {len(tracked)} git-tracked files scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
