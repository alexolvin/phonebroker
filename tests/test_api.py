"""API integration tests (using httpx AsyncClient with FastAPI test client)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from phonebroker import db
from phonebroker.config import reset_config
from phonebroker.main import app


@pytest.fixture
def db_conn():
    with tempfile.TemporaryDirectory() as td:
        conn = db.get_connection(Path(td) / "test.db")
        db.init_db(conn)
        yield conn
        conn.close()


@pytest.fixture
async def client(db_conn):
    app.state.db = db_conn
    from phonebroker.api.auth import init_token_map
    init_token_map()
    transport = ASGITransport(app=app)
    with patch("phonebroker.health.adb.get_phone_state", return_value="device"):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["broker"] == "ok"


@pytest.mark.asyncio
async def test_lease_requires_token(client):
    resp = await client.post("/lease", json={"platform": "vinted", "operation": "test",
                                              "priority": "background", "max_duration_s": 60})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lease_invalid_token(client):
    resp = await client.post(
        "/lease",
        json={"platform": "vinted", "operation": "test",
              "priority": "background", "max_duration_s": 60},
        headers={"Authorization": "Bearer wrong_token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lease_unknown_platform(client):
    resp = await client.post(
        "/lease",
        json={"platform": "nonexistent", "operation": "test",
              "priority": "background", "max_duration_s": 60},
        headers={"Authorization": "Bearer test_token_client_a"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_lease_project_in_body_rejected(client):
    resp = await client.post(
        "/lease",
        json={"platform": "vinted", "operation": "test",
              "priority": "background", "max_duration_s": 60, "project": "hacker"},
        headers={"Authorization": "Bearer test_token_client_a"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_lease_max_duration_validation(client):
    # interactive > 600
    resp = await client.post(
        "/lease",
        json={"platform": "vinted", "operation": "test",
              "priority": "interactive", "max_duration_s": 601},
        headers={"Authorization": "Bearer test_token_client_a"},
    )
    assert resp.status_code == 422

    # background > 300
    resp = await client.post(
        "/lease",
        json={"platform": "vinted", "operation": "test",
              "priority": "background", "max_duration_s": 301},
        headers={"Authorization": "Bearer test_token_client_a"},
    )
    assert resp.status_code == 422
