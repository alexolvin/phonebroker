"""Bearer token authentication — maps token to project name."""

import os

from fastapi import HTTPException, Request

# Token → project mapping (resolved at startup from environment)
_TOKEN_MAP: dict[str, str] = {}


def init_token_map() -> None:
    """Initialize the token map from environment variables.

    Dynamically discovers all PHONEBROKER_TOKEN_* env vars:
    - PHONEBROKER_TOKEN_OWNER → "owner"
    - PHONEBROKER_TOKEN_<NAME> → project name "<name>" (lowercased)
    """
    global _TOKEN_MAP
    _TOKEN_MAP = {}
    for var, value in os.environ.items():
        if not var.startswith("PHONEBROKER_TOKEN_"):
            continue
        if not value:
            continue
        name = var[len("PHONEBROKER_TOKEN_"):]
        if name == "OWNER":
            _TOKEN_MAP[value] = "owner"
        else:
            _TOKEN_MAP[value] = name.lower()


def require_project(request: Request) -> str:
    """Extract and validate project from Bearer token. Raises 401/422."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    project = _TOKEN_MAP.get(token)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    if project == "owner":
        raise HTTPException(status_code=403, detail="Owner token on project endpoint")
    return project


def require_owner(request: Request) -> None:
    """Validate owner token. Raises 401 if not owner."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    if _TOKEN_MAP.get(token) != "owner":
        raise HTTPException(status_code=401, detail="Invalid owner token")
