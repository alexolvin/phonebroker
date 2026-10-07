"""SecretRef resolver for PhoneBroker.

Resolution order (first hit wins):
  1. the process environment (systemd EnvironmentFile in production,
     explicit export in development and tests);
  2. the project-root ``.env`` file (test values only).

The ``.env`` file is loaded ONLY here — it is the single .env-loading site in
the codebase. The process environment always takes precedence over ``.env``,
so a systemd EnvironmentFile in prod overrides ``.env``.
"""

import os
from pathlib import Path

from phonebroker.exceptions import SecretResolutionError

# This file: <root>/src/phonebroker/secrets.py → root is 3 levels up
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

_SECRET_REF_PREFIXES = ("SecretRef:", "env:")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_secret(secret_ref: str) -> str:
    """Resolve a SecretRef to its actual value.

    Lookup order (first hit wins): the process environment, then the
    project-root ``.env`` file.

    Example formats:
        'PHONEBROKER_TOKEN_CLIENT_A' -> os.environ['PHONEBROKER_TOKEN_CLIENT_A']
        'SecretRef:PHONEBROKER_TOKEN_CLIENT_A' -> same
        'env:PHONEBROKER_TOKEN_CLIENT_A' -> same
    """
    clean_ref = secret_ref.strip()
    for prefix in _SECRET_REF_PREFIXES:
        if clean_ref.startswith(prefix):
            clean_ref = clean_ref[len(prefix):]
            break

    if not clean_ref:
        return ""

    val = os.environ.get(clean_ref)
    if val is not None:
        return val

    val = _parse_env_file(_ENV_FILE).get(clean_ref)
    if val is None:
        raise SecretResolutionError(
            f"Failed to resolve secret reference '{secret_ref}': variable '{clean_ref}' "
            "is not set in the process environment or in .env."
        )
    return val
