#!/usr/bin/env python3
"""check_powershell: basic syntax validation for .ps1 files.

Checks:
1. File exists and is non-empty
2. No bash-style input redirection (< [System...]::)
3. Balanced braces
4. UTF-8 encodable (no null bytes)

Exit 0 = pass, 1 = fail.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1_FILES = list(ROOT.rglob("*.ps1"))
IGNORED_DIRS = {".git", ".venv", "__pycache__"}


def check_file(path: Path) -> list[str]:
    violations = []
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [f"{path}: cannot read: {e}"]

    if not content.strip():
        violations.append(f"{path}: empty file")
        return violations

    # No bash-style redirection
    if re.search(r"<\s*\[System\.", content):
        violations.append(f"{path}: bash-style input redirection (< [System...]::)")

    # Balanced braces
    depth = 0
    for i, ch in enumerate(content):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                line = content[:i].count("\n") + 1
                violations.append(f"{path}:{line}: unbalanced }} (depth went negative)")
                break
    if depth > 0:
        violations.append(f"{path}: unbalanced {{ (unclosed, depth={depth})")

    # No null bytes
    if "\x00" in content:
        violations.append(f"{path}: contains null bytes")

    return violations


def main() -> int:
    if not PS1_FILES:
        print("PowerShell check passed: no .ps1 files found.")
        return 0

    all_violations = []
    for f in sorted(PS1_FILES):
        if any(part in IGNORED_DIRS for part in f.parts):
            continue
        all_violations.extend(check_file(f))

    if all_violations:
        print(f"POWERSHELL GATE FAILED! Found {len(all_violations)} violation(s):", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    print(f"PowerShell check passed: {len(PS1_FILES)} .ps1 file(s) validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
