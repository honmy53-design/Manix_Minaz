"""مانیکس / Manix project module."""

import time

import pytest
from fastapi.testclient import TestClient

from panel.config import Settings
from panel.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "data", "admin", "test-only-long-password", stop_timeout=5)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def auth(client):
    response = client.post("/api/login", json={"username": "admin", "password": "test-only-long-password"})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def wait_job(client, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = next(j for j in client.get("/api/status").json()["jobs"] if j["id"] == job_id)
        if job["state"] in {"done", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job timed out")
