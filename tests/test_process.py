"""مانیکس / Manix project module."""

import json

from conftest import wait_job


def configure_fake(auth, settings, monkeypatch):
    fake = settings.data_dir / "fake-java"
    fake.write_text(
        '#!/usr/bin/env python3\nimport sys\nprint("Done (0.1s)!",flush=True)\nfor line in sys.stdin:\n line=line.strip()\n print("received: "+line,flush=True)\n if line=="stop": break\n'
    )
    fake.chmod(0o700)
    monkeypatch.setenv("JAVA_21_BIN", str(fake))
    ident = "a" * 32
    root = settings.data_dir / "engines" / ident
    root.mkdir()
    (root / "server.jar").write_bytes(b"fake")
    engine = {
        "id": ident,
        "kind": "paper",
        "version": "1.21.1",
        "required_java": 21,
        "java": 21,
        "build": "test",
        "mode": "jar",
        "entry": "server.jar",
    }
    (root / "engine.json").write_text(json.dumps(engine))
    ctx = auth.app.state.ctx
    ctx.store.config.update(engine=engine, eula_accepted=True, memory_mb=512)
    ctx.store.save_config()
    ctx.manager.phase = "stopped"


def test_start_console_stop(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    job = auth.post("/api/power", json={"action": "start"}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert auth.get("/api/status").json()["running"]
    assert auth.post("/api/console", json={"command": "say hello"}).status_code == 200
    assert auth.post("/api/console", json={"command": "say hello\nstop"}).status_code == 400
    assert auth.post("/api/console", json={"command": "stop"}).status_code == 400
    assert auth.put("/api/files/text", json={"path": "x", "content": "x"}).status_code == 409
    assert auth.patch("/api/settings", json={"memory_mb": 768}).status_code == 409
    job = auth.post("/api/power", json={"action": "stop"}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert not auth.get("/api/status").json()["running"]
    assert not auth.app.state.ctx.store.config["desired_running"]


def test_consistent_backup_restarts_running_game(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    job = auth.post("/api/power", json={"action": "start"}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    job = auth.post("/api/backups").json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert auth.get("/api/status").json()["running"]


def test_eula_required_and_not_auto_accepted(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    auth.patch("/api/settings", json={"eula_accepted": False})
    job = auth.post("/api/power", json={"action": "start"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    assert not auth.get("/api/status").json()["running"]


def test_player_input_validation(auth):
    assert auth.post("/api/players/action", json={"action": "op", "username": "Player\nstop"}).status_code == 422


def test_failed_job_metadata_does_not_lock_panel(auth, monkeypatch):
    def fail(job):
        raise OSError("simulated full disk")

    monkeypatch.setattr(auth.app.state.ctx.store, "save_job", fail)
    assert auth.post("/api/backups").status_code == 507
    assert not auth.app.state.ctx.manager.lock.locked()


def test_job_final_persistence_error_releases_guard(auth, monkeypatch):
    store = auth.app.state.ctx.store
    original = store.save_job
    count = 0

    def fail_later(job):
        nonlocal count
        count += 1
        if count > 1:
            raise OSError("simulated metadata write failure")
        original(job)

    monkeypatch.setattr(store, "save_job", fail_later)
    job = auth.post("/api/backups").json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    assert not auth.app.state.ctx.manager.lock.locked()
