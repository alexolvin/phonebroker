"""Check that _adb() is never called with "shell" outside _adb_shell().

All adb shell invocations must go through _adb_shell() so the command
white-list is enforced. A direct _adb(serial, "shell", ...) call bypasses
the white-list — FAIL.

Self-test (probe in a temporary clone): the check is run against a temp
copy of src/phonebroker/adb.py with an injected violation; the gate fails
hard if the violation is not detected or the pristine file is flagged.
"""

import ast
import sys
import tempfile
from pathlib import Path


def find_violations(source: str) -> list[tuple[int, str]]:
    """Return [(line, snippet)] of _adb(..., "shell", ...) calls outside _adb_shell."""
    tree = ast.parse(source)

    # Lines belonging to the _adb_shell function definition (the only
    # place where _adb(..., "shell", ...) is allowed)
    adb_shell_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_adb_shell":
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    adb_shell_lines.add(sub.lineno)

    violations = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_adb"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "shell"
            and node.lineno not in adb_shell_lines
        ):
            violations.append(
                (node.lineno, source.splitlines()[node.lineno - 1].strip())
            )
    return violations


def self_test(adb_path: Path) -> bool:
    """Probe in a temporary clone of adb.py.

    1. Pristine copy must not be flagged.
    2. A clone with an injected direct _adb(..., "shell", ...) call
       outside _adb_shell must be detected.
    """
    src = adb_path.read_text(encoding="utf-8")
    if find_violations(src):
        print("FAIL: self-test — pristine adb.py flagged", file=sys.stderr)
        return False

    anchor = "def get_phone_state"
    injected = src.replace(
        anchor,
        'def _probe_bypass(serial):\n'
        '    return _adb(serial, "shell", "cat /etc/passwd")\n'
        "\n\n\n" + anchor,
        1,
    )
    if injected == src:
        print("FAIL: self-test — could not inject probe (anchor missing)",
              file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "adb.py"
        clone.write_text(injected, encoding="utf-8")
        if not find_violations(clone.read_text(encoding="utf-8")):
            print("FAIL: self-test — injected violation not detected",
                  file=sys.stderr)
            return False
    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    adb_path = repo_root / "src" / "phonebroker" / "adb.py"

    if not self_test(adb_path):
        return 1

    all_violations: list[tuple[str, int, str]] = []
    for path in sorted((repo_root / "src" / "phonebroker").glob("*.py")):
        for lineno, line in find_violations(path.read_text(encoding="utf-8")):
            all_violations.append((str(path.relative_to(repo_root)), lineno, line))

    if all_violations:
        print('FAIL: _adb(..., "shell", ...) outside _adb_shell:')
        for rel, lineno, line in all_violations:
            print(f"  {rel}:{lineno}: {line}")
        print("\n  All adb shell calls must go through _adb_shell() "
              "(white-list check).")
        return 1

    print("ADB shell check passed: all shell calls via _adb_shell.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
