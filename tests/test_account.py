import hashlib
import time
from urllib.parse import unquote, urlsplit, parse_qs
from dataclasses import replace

from fastapi.testclient import TestClient

from panel.auth import totp
from panel.main import create_app

PASSWORD = "test-only-long-password"


def test_profile_is_real_contact_only(auth):
    r = auth.patch("/api/account", json={"display_name": "مالک مانیکس", "email": "owner@example.com"})
    assert r.status_code == 200
    assert auth.get("/api/account").json()["display_name"] == "مالک مانیکس"
    assert auth.patch("/api/account", json={"display_name": "x", "email": "bad"}).status_code == 400
    profile = auth.get("/api/account").json()
    assert profile["devices"][0]["current"]
    assert profile["devices"][0]["ip"]
    assert any(row["action"] == "auth.login" for row in profile["login_history"])


def test_password_change_persists_and_environment_recovers(settings):
    with TestClient(create_app(settings)) as c:
        csrf = c.post("/api/login", json={"username": "admin", "password": PASSWORD}).json()["csrf"]
        c.headers["X-CSRF-Token"] = csrf
        key = c.post("/api/account/keys", json={"password": PASSWORD, "name": "test", "scopes": ["status"]}).json()["token"]
        assert c.post("/api/account/password", json={"password": PASSWORD, "new_password": "new-browser-safe-password"}).status_code == 200
        assert c.get("/api/status").status_code == 401
        assert c.get("/api/status", headers={"Authorization": "Bearer " + key}).status_code == 401
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/login", json={"username": "admin", "password": "new-browser-safe-password"}).status_code == 200
    with TestClient(create_app(replace(settings, password="new-operator-environment-password"))) as c:
        assert c.post("/api/login", json={"username": "admin", "password": "new-browser-safe-password"}).status_code == 401
        assert c.post("/api/login", json={"username": "admin", "password": "new-operator-environment-password"}).status_code == 200


def test_logout_all_revokes_other_device(auth):
    first = dict(auth.cookies)
    second = auth.post("/api/login", json={"username": "admin", "password": PASSWORD}).json()
    auth.headers["X-CSRF-Token"] = second["csrf"]
    assert len(auth.get("/api/account").json()["devices"]) == 2
    assert auth.post("/api/account/logout-all").status_code == 200
    auth.cookies.update(first)
    assert auth.get("/api/status").status_code == 401


def test_totp_and_recovery_are_single_use(auth):
    result = auth.post("/api/account/2fa/setup", json={"password": PASSWORD})
    assert result.status_code == 200
    uri = urlsplit(result.json()["uri"])
    assert unquote(uri.path).lstrip("/").split(":")[0] == parse_qs(uri.query)["issuer"][0] == "مانیکس"
    secret = result.json()["secret"]
    code = totp(secret, int(time.time() // 30))
    confirmed = auth.post("/api/account/2fa/confirm", json={"code": code})
    assert confirmed.status_code == 200
    recovery = confirmed.json()["recovery_codes"]
    assert len(recovery) == 8
    assert "secret" not in auth.get("/api/account").json()
    auth.post("/api/logout")
    assert auth.post("/api/login", json={"username": "admin", "password": PASSWORD}).json()["requires_otp"]
    assert auth.post("/api/login", json={"username": "admin", "password": PASSWORD, "otp": code}).status_code == 401
    accepted = auth.post("/api/login", json={"username": "admin", "password": PASSWORD, "otp": recovery[0]})
    assert accepted.status_code == 200
    auth.headers["X-CSRF-Token"] = accepted.json()["csrf"]
    assert auth.get("/api/account").json()["recovery_remaining"] == 7
    auth.post("/api/logout")
    assert auth.post("/api/login", json={"username": "admin", "password": PASSWORD, "otp": recovery[0]}).status_code == 401
    accepted = auth.post("/api/login", json={"username": "admin", "password": PASSWORD, "otp": recovery[1]})
    auth.headers["X-CSRF-Token"] = accepted.json()["csrf"]
    assert auth.post("/api/account/2fa/disable", json={"password": PASSWORD, "code": recovery[2]}).status_code == 200
    assert not auth.get("/api/account").json()["two_factor"]


def test_totp_setup_bound_to_original_device(auth):
    auth.post("/api/account/2fa/setup", json={"password": PASSWORD})
    new_session = auth.post("/api/login", json={"username": "admin", "password": PASSWORD}).json()
    auth.headers["X-CSRF-Token"] = new_session["csrf"]
    assert auth.post("/api/account/2fa/confirm", json={"code": "123456"}).status_code == 400


def test_scoped_bearer_does_not_fall_back_to_owner_cookie(auth):
    created = auth.post("/api/account/keys", json={"password": PASSWORD, "name": "metrics only", "scopes": ["status"], "days": 7})
    assert created.status_code == 200
    key = created.json()
    headers = {"Authorization": "Bearer " + key["token"]}
    assert auth.get("/api/status", headers=headers).status_code == 200
    assert auth.get("/api/status", headers=headers | {"Origin": "https://evil.example"}).status_code == 403
    assert auth.get("/api/account", headers=headers).status_code == 403
    assert auth.get("/api/files", headers=headers).status_code == 403
    assert auth.post("/api/power", json={"action": "stop"}, headers=headers).status_code == 403
    assert auth.get("/api/status", headers={"Authorization": "Bearer manix_invalid"}).status_code == 401
    listing = auth.get("/api/account").json()["api_keys"]
    assert "token" not in listing[0]
    with auth.app.state.ctx.store.connect() as db:
        stored = db.execute("SELECT token FROM api_keys WHERE id=?", (key["id"],)).fetchone()[0]
        assert stored == hashlib.sha256(key["token"].encode()).hexdigest()
    assert auth.delete("/api/account/keys/" + key["id"]).status_code == 200
    assert auth.get("/api/status", headers=headers).status_code == 401


def test_write_key_uses_scopes_not_cookie_csrf(auth):
    token = auth.post("/api/account/keys", json={"password": PASSWORD, "name": "config", "scopes": ["settings.write"]}).json()["token"]
    auth.headers.pop("X-CSRF-Token")
    headers = {"Authorization": "Bearer " + token}
    assert auth.patch("/api/settings", json={"server_name": "API مانیکس"}, headers=headers).status_code == 200
    assert auth.post("/api/account/logout-all", headers=headers).status_code == 403
    headers["Origin"] = "https://evil.example"
    assert auth.patch("/api/settings", json={"server_name": "x"}, headers=headers).status_code == 403


def test_bad_reauthentication_is_limited(auth):
    for _ in range(5):
        assert auth.post("/api/account/2fa/setup", json={"password": "bad"}).status_code == 403
    assert auth.post("/api/account/2fa/setup", json={"password": PASSWORD}).status_code == 429
