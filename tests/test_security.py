"""مانیکس / Manix project module."""

from dataclasses import replace

from fastapi.testclient import TestClient

from panel.main import create_app
from panel.storage import password_hash, verify_password


def test_login_required(client):
    assert client.get("/healthz").json()["ok"]
    assert client.get("/").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/files/download?path=server.properties").status_code == 401


def test_password_kdf():
    encoded = password_hash("a safe secret password")
    assert "a safe" not in encoded
    assert verify_password("a safe secret password", encoded)
    assert not verify_password("wrong", encoded)


def test_csrf_and_origin(auth):
    token = auth.headers.pop("X-CSRF-Token")
    assert auth.patch("/api/settings", json={"server_name": "x"}).status_code == 403
    auth.headers["X-CSRF-Token"] = token
    assert auth.patch("/api/settings", json={"server_name": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert auth.patch("/api/settings", json={"server_name": "نام جدید"}).status_code == 200


def test_login_cross_origin(client):
    assert (
        client.post(
            "/api/login", json={"username": "admin", "password": "test-only-long-password"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_login_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code == 429


def test_secure_cookie(settings):
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        r = client.post("/api/login", json={"username": "admin", "password": "test-only-long-password"})
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert client.get("/api/status").status_code == 200


def test_password_rotation_invalidates_sessions(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/login", json={"username": "admin", "password": "test-only-long-password"}).status_code == 200
        cookies = dict(client.cookies)
    with TestClient(create_app(replace(settings, password="different-long-password"))) as client:
        client.cookies.update(cookies)
        assert client.get("/api/status").status_code == 401


def test_logout(auth):
    assert auth.post("/api/logout").status_code == 200
    assert auth.get("/api/session").status_code == 401


def test_domain_validation(auth):
    assert auth.patch("/api/settings", json={"game_domain": "https://evil.example/path"}).status_code == 422
    assert (
        auth.patch(
            "/api/settings", json={"game_domain": "play.example.com", "proxy_host": "a.proxy.rlwy.net", "proxy_port": 14567}
        ).status_code
        == 200
    )
    assert auth.get("/api/status").json()["address"] == "play.example.com"


def test_no_arbitrary_shell_endpoint(auth):
    assert auth.post("/api/shell", json={"command": "id"}).status_code == 404
    assert auth.patch("/api/settings", json={"startup_command": "rm -rf /"}).status_code == 422


def test_unicode_bad_username_is_not_internal_error(client):
    assert client.post("/api/login", json={"username": "کاربر", "password": "wrong"}).status_code == 401


def test_blank_console_command_is_validation_error(auth):
    assert auth.post("/api/console", json={"command": "   "}).status_code == 400
