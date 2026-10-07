"""Check for direct adb calls bypassing adb_cmd in shell scripts.

Scans scripts/*.sh (excluding adb_cmd.sh), scripts/phonebroker-maintenance,
and tests/acceptance/*.sh for standalone `adb` word usage.

A violation is any line where `adb` appears as a command word (not part of
`adb_cmd`, not `phonebroker-adb`, not in a comment).
"""

import re
import sys
from pathlib import Path

# Pattern: 'adb' as a standalone word, not preceded by word-char or hyphen
# (excludes phonebroker-adb), not followed by word-char (excludes adb_cmd, adbkey)
ADB_WORD = re.compile(r"(?<![a-zA-Z0-9_-])adb(?![a-zA-Z0-9_])")

# Files to scan (relative to repo root)
SCAN_DIRS = ["scripts", "tests/acceptance"]
EXCLUDE_FILES = {"adb_cmd.sh"}


def is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#")


def is_false_positive(line: str) -> bool:
    """Check if the adb match is a false positive."""
    stripped = line.strip()

    # adb.service is a systemd unit, not an adb command
    if "adb.service" in line:
        return True

    # Quoted 'adb' / "adb" — config key string, not a command invocation
    if "'adb'" in line or '"adb"' in line:
        return True

    # adb.<attr> — config attribute path (e.g. adb.serial), not a command
    if re.search(r"(?<![a-zA-Z0-9_-])adb\.", line):
        return True

    # Lines that use ADB_EXEC_PREFIX (background install special case)
    if "ADB_EXEC_PREFIX" in line:
        return True

    # Lines where adb appears only inside a quoted string in a print/log context
    # (printf, echo, log) — the string is a label, not a command invocation
    if any(stripped.startswith(p) for p in ("printf ", "echo ", "log ")):
        # Check if 'adb' only appears within quotes
        unquoted = re.sub(r'"[^"]*"', '', line)
        unquoted = re.sub(r"'[^']*'", '', unquoted)
        if not ADB_WORD.search(unquoted):
            return True

    return False


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line) violations."""
    violations = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if is_comment(line):
                continue
            # Skip lines that are part of adb_cmd definition/call
            if "adb_cmd" in line or "adb_exec_prefix" in line:
                continue
            if ADB_WORD.search(line):
                if is_false_positive(line):
                    continue
                violations.append((lineno, line.rstrip()))
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    all_violations: list[tuple[str, int, str]] = []

    for scan_dir in SCAN_DIRS:
        dir_path = repo_root / scan_dir
        if not dir_path.is_dir():
            continue
        for path in sorted(dir_path.glob("*.sh")):
            if path.name in EXCLUDE_FILES:
                continue
            for lineno, line in check_file(path):
                rel = path.relative_to(repo_root)
                all_violations.append((str(rel), lineno, line))

    # Also check phonebroker-maintenance (no .sh extension)
    maint = repo_root / "scripts" / "phonebroker-maintenance"
    if maint.is_file():
        for lineno, line in check_file(maint):
            all_violations.append(("scripts/phonebroker-maintenance", lineno, line))

    if all_violations:
        print("FAIL: direct adb calls found (must use adb_cmd):")
        for rel, lineno, line in all_violations:
            print(f"  {rel}:{lineno}: {line.strip()}")
        print(f"\n  {len(all_violations)} violation(s). "
              "Source scripts/adb_cmd.sh and use adb_cmd instead.")
        return 1

    print("ADB usage check passed: no direct adb calls (all via adb_cmd).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
