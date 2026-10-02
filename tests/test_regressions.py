"""مانیکس / Manix project module."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import wait_job
from panel.auth import AccountService, recovery_digest
from panel.storage import Store, password_hash
from test_extensions import task_body
from test_files import zip_bytes
from test_process import configure_fake


def test_legacy_database_schema_migrates_without_losing_credentials(settings):
    settings.prepare()
    path = settings.panel_dir / "panel.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE sessions(token TEXT PRIMARY KEY,csrf TEXT,expires REAL);"
        )
        db.executemany(
            "INSERT INTO kv VALUES(?,?)",
            [("username", json.dumps("admin")), ("password_hash", json.dumps(password_hash(settings.password)))],
        )
    store = Store(settings.panel_dir, settings.username, settings.password, settings.defaults())
    token, csrf = store.new_session(24, "127.0.0.1", "Manix migration test")
    assert store.session(token)["csrf"] == csrf
    assert store.devices(store.session(token)["id"])[0]["ip"] == "127.0.0.1"
    assert path.stat().st_mode & 0o777 == 0o600


def test_concurrent_recovery_code_only_one_request_wins(auth):
    store = auth.app.state.ctx.store
    store.put(
        "two_factor",
        {"secret": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "recovery": [recovery_digest("a-safe-recovery-code")], "last_counter": -1},
    )
    account = AccountService(store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(account.verify_second_factor, ["a-safe-recovery-code", "a-safe-recovery-code"]))
    assert sorted(result) == [False, True]


def test_login_history_not_lost_behind_other_recent_events(auth):
    store = auth.app.state.ctx.store
    for i in range(120):
        store.audit("job.test", str(i))
    assert any(row["action"] == "auth.login" for row in auth.get("/api/account").json()["login_history"])


def test_pack_upload_after_restoring_pre_pack_backup(auth, settings):
    archive = zip_bytes({".manix-backup.json": '{"format":"manix.backup.v1","engine":null}', "server/old.txt": b"old"})
    imported = auth.post("/api/backups/import", files={"file": ("old.zip", archive)}).json()
    job = auth.post("/api/backups/restore", json={"name": imported["name"]}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert not (settings.server_dir / "resourcepacks").exists()
    response = auth.post("/api/packs/upload", files={"file": ("pack.zip", zip_bytes({"pack.mcmeta": '{"pack":{"pack_format":34}}'}))})
    assert response.status_code == 200
    assert auth.get("/api/packs").json()["packs"][0]["id"] == response.json()["id"]


def test_pack_registry_survives_full_restore(auth):
    body = zip_bytes({"pack.mcmeta": '{"pack":{"pack_format":34}}'})
    record = auth.post("/api/packs/upload", files={"file": ("pack.zip", body)}).json()
    auth.post("/api/packs/activate", json={"id": record["id"], "base_url": "https://manix.example"})
    backup = wait_job(auth, auth.post("/api/backups").json()["id"])
    auth.post("/api/packs/activate", json={"id": ""})
    auth.delete("/api/packs/" + record["id"])
    filename = backup["download"].split("name=", 1)[1]
    restored = wait_job(auth, auth.post("/api/backups/restore", json={"name": filename}).json()["id"])
    assert restored["state"] == "done"
    assert auth.get("/api/packs").json()["active"] == record["id"]
    assert auth.get("/packs/" + record["id"] + ".zip").content == body


def test_bulk_move_io_failure_rolls_back_earlier_paths(auth, settings, monkeypatch):
    import panel.fileops as files

    auth.post("/api/files/mkdir", json={"path": "dest"})
    for name in ["a", "b"]:
        auth.put("/api/files/text", json={"path": name, "content": name})
    original = files.os.replace

    def fail_second(source, target):
        if str(source) == str(settings.server_dir / "b") and str(target) == str(settings.server_dir / "dest/b"):
            raise OSError("simulated second move failure")
        return original(source, target)

    monkeypatch.setattr(files.os, "replace", fail_second)
    job = wait_job(auth, auth.post("/api/files/batch", json={"action": "move", "paths": ["a", "b"], "destination": "dest"}).json()["id"])
    assert job["state"] == "failed"
    assert (settings.server_dir / "a").read_text() == "a" and (settings.server_dir / "b").read_text() == "b"
    assert not list((settings.server_dir / "dest").iterdir())
    assert not auth.app.state.ctx.manager.lock.locked()


def test_world_registry_write_failure_rolls_back_import(auth, settings, monkeypatch):
    store = auth.app.state.ctx.store
    original = store.put

    def fail(key, value):
        if key == "world_registry":
            raise OSError("simulated registry write failure")
        return original(key, value)

    monkeypatch.setattr(store, "put", fail)
    job = auth.post(
        "/api/worlds/import", data={"name": "new-world"}, files={"file": ("world.zip", zip_bytes({"level.dat": b"fake"}))}
    ).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    assert not (settings.server_dir / "new-world").exists()


def test_custom_executable_spigot_jar_and_runtime_cleanup(auth, settings, monkeypatch):
    ctx = auth.app.state.ctx
    monkeypatch.setenv("JAVA_21_BIN", "/usr/bin/true")

    async def meta(version):
        return {"releaseTime": "2024-08-08T00:00:00Z", "javaVersion": {"majorVersion": 21}}

    monkeypatch.setattr(ctx.engines, "version_meta", meta)
    jar = zip_bytes(
        {"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nMain-Class: test.Main\n", "test/Main.class": b"\xca\xfe\xba\xbe\x00\x00\x00\x41"}
    )
    r = auth.post("/api/versions/custom", data={"kind": "spigot", "version": "1.21.1", "java": "21"}, files={"file": ("spigot.jar", jar)})
    assert r.status_code == 200
    assert wait_job(auth, r.json()["id"])["state"] == "done"
    current = ctx.store.config["engine"]
    assert current["kind"] == "spigot" and current["manual"]
    assert ctx.addons.context()[1] == ["spigot", "bukkit"]
    assert auth.delete("/api/versions/installed/" + current["id"]).status_code == 409
    older = settings.data_dir / "engines" / ("b" * 32)
    older.mkdir()
    (older / "engine.json").write_text(json.dumps(current | {"id": older.name}))
    (older / "server.jar").write_bytes(jar)
    assert len(auth.get("/api/versions/installed").json()["engines"]) == 2
    assert auth.delete("/api/versions/installed/" + older.name).status_code == 200
    assert not older.exists()


def test_installer_not_accepted_as_custom_server(auth, monkeypatch):
    monkeypatch.setenv("JAVA_21_BIN", "/usr/bin/true")

    async def meta(version):
        return {"javaVersion": {"majorVersion": 21}}

    monkeypatch.setattr(auth.app.state.ctx.engines, "version_meta", meta)
    r = auth.post(
        "/api/versions/custom",
        data={"kind": "spigot", "version": "1.21.1", "java": "21"},
        files={"file": ("installer.jar", zip_bytes({"no-main.txt": "not an executable server"}))},
    )
    assert wait_job(auth, r.json()["id"])["state"] == "failed"
    assert auth.app.state.ctx.store.config["engine"] is None


def test_calendar_job_failure_is_visible_and_once_not_replayed(auth, monkeypatch):
    ctx = auth.app.state.ctx
    task = auth.post("/api/schedules", json=task_body()).json()
    tasks = ctx.store.get("schedules")
    tasks[task["id"]].update(mode="once", next_run=time.time() - 1)
    ctx.store.put("schedules", tasks)
    original = ctx.store.save_job
    count = 0

    def fail_running(job):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated job-running persistence failure")
        return original(job)

    monkeypatch.setattr(ctx.store, "save_job", fail_running)
    auth.portal.call(ctx.schedules.tick)
    job_id = ctx.store.get("schedules")[task["id"]]["last_job"]
    assert wait_job(auth, job_id)["state"] == "failed"
    response = auth.get("/api/schedules").json()["tasks"][0]
    assert response["last_result"] == "failed" and not response["enabled"]


def test_calendar_uses_power_and_console_handlers(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    ctx = auth.app.state.ctx
    for action in ["start", "command", "restart", "stop"]:

        async def operation():
            return await ctx.schedules.operation({"action": action, "command": "say calendar"})

        job = auth.portal.call(ctx.manager.new_job, "calendar test " + action, operation)
        assert wait_job(auth, job["id"])["state"] == "done"
    assert not ctx.manager.running and not ctx.store.config["desired_running"]


def test_live_players_reads_full_console_list(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    fake = settings.data_dir / "fake-java"
    fake.write_text(
        '#!/usr/bin/env python3\nimport sys\nprint("Done (0.1s)!",flush=True)\nprint("[Server thread/INFO]: Sample joined the game",flush=True)\nfor line in sys.stdin:\n if line.strip()=="list": print("[Server thread/INFO]: There are 1 of a max of 20 players online: Sample",flush=True)\n if line.strip()=="stop": break\n'
    )
    wait_job(auth, auth.post("/api/power", json={"action": "start"}).json()["id"])
    result = auth.get("/api/players").json()
    assert result["source"] == "console-list" and result["online"] == ["Sample"]
    assert result["online_info"][0]["joined_at"] is not None


@pytest.mark.parametrize("metadata", [{"pack": {"pack_format": -1}}, {"pack": {"pack_format": True}}, {"pack": {"min_format": "wrong"}}])
def test_invalid_pack_format_metadata_denied(auth, metadata):
    r = auth.post("/api/packs/upload", files={"file": ("pack.zip", zip_bytes({"pack.mcmeta": json.dumps(metadata)}))})
    assert r.status_code == 400


def test_new_pack_format_tuple_supported(auth):
    r = auth.post(
        "/api/packs/upload", files={"file": ("pack.zip", zip_bytes({"pack.mcmeta": '{"pack":{"min_format":[65,0],"max_format":[65,9]}}'}))}
    )
    assert r.status_code == 200 and r.json()["format"] == [65, 0]


def test_backup_manifest_wrong_shape_denied(auth):
    for value in ["[]", '"not an object"', '{"format":"manix.backup.v1","engine":"invalid"}']:
        assert (
            auth.post(
                "/api/backups/import", files={"file": ("wrong.zip", zip_bytes({".manix-backup.json": value, "server/test.txt": "file"}))}
            ).status_code
            == 400
        )


@pytest.mark.parametrize("failure", ["config-before", "config-after", "audit"])
def test_custom_runtime_commit_boundary_never_deletes_active_jar(auth, settings, monkeypatch, failure):
    configure_fake(auth, settings, monkeypatch)
    ctx = auth.app.state.ctx
    old = ctx.store.config["engine"].copy()
    monkeypatch.setenv("JAVA_21_BIN", "/usr/bin/true")
    for folder in ["mods", "plugins"]:
        directory = settings.server_dir / folder
        directory.mkdir(exist_ok=True)
        (directory / "old.jar").write_bytes(b"old addon")

    async def meta(version):
        return {"releaseTime": "2024-08-08T00:00:00Z", "javaVersion": {"majorVersion": 21}}

    monkeypatch.setattr(ctx.engines, "version_meta", meta)
    original_save, original_audit = ctx.store.save_config, ctx.store.audit

    def save():
        if (ctx.store.config.get("engine") or {}).get("id") != old["id"] and failure.startswith("config-"):
            if failure == "config-after":
                original_save()
            raise OSError("simulated activation config failure " + failure)
        return original_save()

    def audit(action, detail=""):
        if action == "engine.install" and failure == "audit":
            raise OSError("simulated post-commit audit failure")
        return original_audit(action, detail)

    monkeypatch.setattr(ctx.store, "save_config", save)
    monkeypatch.setattr(ctx.store, "audit", audit)
    jar = zip_bytes(
        {"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nMain-Class: test.Main\n", "test/Main.class": b"\xca\xfe\xba\xbe\x00\x00\x00\x41"}
    )
    response = auth.post(
        "/api/versions/custom", data={"kind": "spigot", "version": "1.21.1", "java": "21"}, files={"file": ("spigot.jar", jar)}
    )
    assert response.status_code == 200
    assert wait_job(auth, response.json()["id"])["state"] == "failed"
    assert not ctx.manager.lock.locked()
    current = ctx.store.config["engine"]
    assert ctx.store.get("config")["engine"] == current
    engines = list((settings.data_dir / "engines").iterdir())
    if failure == "config-before":
        assert current == old and len(engines) == 1
        for folder in ["mods", "plugins"]:
            assert (settings.server_dir / folder / "old.jar").read_bytes() == b"old addon"
    else:
        assert current["id"] != old["id"] and current["kind"] == "spigot"
        assert len(engines) == 2 and ctx.manager.phase == "stopped"
        directory = settings.data_dir / "engines" / current["id"]
        assert (directory / "server.jar").read_bytes() == jar
        assert json.loads((directory / "engine.json").read_text()) == current
        assert len(list((settings.server_dir / "disabled-addons").rglob("old.jar"))) == 2
        assert not (settings.server_dir / "plugins/old.jar").exists()
        assert any(row["active"] and row["id"] == current["id"] for row in auth.get("/api/versions/installed").json()["engines"])
