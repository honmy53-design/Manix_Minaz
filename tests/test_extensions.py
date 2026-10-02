import hashlib
import io
import json
import time
import zipfile
from datetime import datetime, timezone

import pytest

from conftest import wait_job
from panel.auth import totp
from panel.backups import LEGACY_FORMAT, LEGACY_MANIFEST
from panel.errors import PanelError
from panel.players import PlayerTracker
from panel.schedules import next_run
from panel.startup import validate_jvm_args
from test_files import zip_bytes
from test_process import configure_fake


def test_force_kill_is_a_real_process_termination(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    started = auth.post("/api/power", json={"action": "start"}).json()
    assert wait_job(auth, started["id"])["state"] == "done"
    auth.patch("/api/settings", json={"auto_restart": True})
    killed = auth.post("/api/power", json={"action": "kill"}).json()
    assert wait_job(auth, killed["id"])["state"] == "done"
    status = auth.get("/api/status").json()
    assert not status["running"] and status["last_exit"] == -9
    assert not auth.app.state.ctx.store.config["desired_running"]


def test_port_startup_args_and_live_guard(auth, settings, monkeypatch):
    configure_fake(auth, settings, monkeypatch)
    assert auth.patch("/api/settings", json={"game_port": settings.port}).status_code == 400
    assert (
        auth.patch("/api/settings", json={"game_port": 25600, "jvm_args": ["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=100"]}).status_code == 200
    )
    command = auth.get("/api/startup").json()
    assert "-XX:+UseG1GC" in command["args"]
    assert not command["editable_shell"]
    job = auth.post("/api/power", json={"action": "start"}).json()
    wait_job(auth, job["id"])
    assert auth.get("/api/status").json()["mc_port"] == 25600
    assert "server-port=25600" in (settings.server_dir / "server.properties").read_text()
    assert auth.patch("/api/settings", json={"game_port": 25700}).status_code == 409
    assert auth.patch("/api/settings", json={"jvm_args": []}).status_code == 409


@pytest.mark.parametrize(
    "value",
    [
        ["-javaagent:/tmp/evil.jar"],
        ["-Dlog4j.configurationFile=http://evil"],
        ["-Xmx900M"],
        ["-XX:+UseG1GC", "-XX:+UseZGC"],
        ["-XX:MaxGCPauseMillis=9000"],
        ["-XX:+UseG1GC;id"],
    ],
)
def test_jvm_flags_deny_unsafe_or_conflicting_values(value):
    with pytest.raises(PanelError):
        validate_jvm_args(value)


def test_batch_copy_move_search_and_safe_delete(auth, settings):
    for folder in ["source", "target"]:
        auth.post("/api/files/mkdir", json={"path": folder})
    auth.put("/api/files/text", json={"path": "source/test.txt", "content": "original"})
    copied = auth.post("/api/files/batch", json={"action": "copy", "paths": ["source"], "destination": "target"}).json()
    assert wait_job(auth, copied["id"])["state"] == "done"
    assert (settings.server_dir / "target/source/test.txt").read_text() == "original"
    auth.put("/api/files/text", json={"path": "hello.txt", "content": "hi"})
    moved = auth.post("/api/files/batch", json={"action": "move", "paths": ["hello.txt"], "destination": "target"}).json()
    assert wait_job(auth, moved["id"])["state"] == "done"
    assert not (settings.server_dir / "hello.txt").exists()
    found = auth.get("/api/files/search", params={"path": "", "q": "test", "recursive": True}).json()
    assert {r["path"] for r in found["files"]} == {"source/test.txt", "target/source/test.txt"}
    deleted = auth.post("/api/files/batch", json={"action": "delete", "paths": ["target", "target/source/test.txt"]}).json()
    assert wait_job(auth, deleted["id"])["state"] == "done"
    assert not (settings.server_dir / "target").exists()
    assert any("before-batch-delete" in b["name"] for b in auth.get("/api/backups").json()["backups"])


def test_batch_preflight_no_partial_move_or_self_copy(auth, settings):
    auth.post("/api/files/mkdir", json={"path": "a"})
    auth.post("/api/files/mkdir", json={"path": "a/sub"})
    auth.post("/api/files/mkdir", json={"path": "dest"})
    auth.put("/api/files/text", json={"path": "x", "content": "keep"})
    auth.put("/api/files/text", json={"path": "dest/x", "content": "existing"})
    job = auth.post("/api/files/batch", json={"action": "move", "paths": ["a", "x"], "destination": "dest"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    assert (settings.server_dir / "a").is_dir() and (settings.server_dir / "x").is_file()
    job = auth.post("/api/files/batch", json={"action": "copy", "paths": ["a"], "destination": "a/sub"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"


def test_batch_rejects_symlink_and_traversal(auth, settings, tmp_path):
    outside = tmp_path / "secret"
    outside.write_text("outside")
    auth.post("/api/files/mkdir", json={"path": "folder"})
    auth.post("/api/files/mkdir", json={"path": "destination"})
    (settings.server_dir / "folder/link").symlink_to(outside)
    job = auth.post("/api/files/batch", json={"action": "copy", "paths": ["folder"], "destination": "destination"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    job = auth.post("/api/files/batch", json={"action": "delete", "paths": ["../panel/panel.sqlite3"]}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    assert outside.read_text() == "outside"


def test_world_import_select_export_delete(auth, settings):
    assert auth.post("/api/worlds/create", json={"name": "fresh"}).status_code == 200
    archive = zip_bytes({"old/level.dat": b"fake-nbt", "old/region/region.mca": b"save", "old_nether/level.dat": b"nether"})
    job = auth.post("/api/worlds/import", data={"name": "imported"}, files={"file": ("world.zip", archive)}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert (settings.server_dir / "imported_nether/level.dat").is_file()
    assert auth.post("/api/worlds/select", json={"name": "imported"}).status_code == 200
    assert auth.get("/api/worlds").json()["active"] == "imported"
    job = auth.request("DELETE", "/api/worlds", json={"name": "imported"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    job = auth.post("/api/worlds/export", json={"name": "imported"}).json()
    exported = wait_job(auth, job["id"])
    with zipfile.ZipFile(io.BytesIO(auth.get(exported["download"]).content)) as z:
        assert z.read("imported/region/region.mca") == b"save"
    assert auth.post("/api/worlds/select", json={"name": "fresh"}).status_code == 200
    job = auth.request("DELETE", "/api/worlds", json={"name": "imported"}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert not (settings.server_dir / "imported_nether").exists()


def test_world_zip_traversal_and_ambiguous_import_denied(auth, settings):
    for body in [{"../escape": b"bad", "level.dat": b"x"}, {"a/level.dat": b"x", "b/level.dat": b"y"}]:
        job = auth.post("/api/worlds/import", data={"name": "bad"}, files={"file": ("save.zip", zip_bytes(body))}).json()
        assert wait_job(auth, job["id"])["state"] == "failed"
        assert not (settings.server_dir / "bad").exists()
    assert auth.post("/api/worlds/create", json={"name": "mods"}).status_code == 400
    assert auth.post("/api/worlds/create", json={"name": "../escaped"}).status_code == 400


def test_pack_validates_activates_public_url_and_is_backed_up(auth):
    archive = zip_bytes(
        {"pack.mcmeta": json.dumps({"pack": {"pack_format": 34, "description": "Manix"}}), "assets/example/test.txt": b"asset"}
    )
    record = auth.post("/api/packs/upload", files={"file": ("manix.zip", archive)}).json()
    assert record["sha1"] == hashlib.sha1(archive).hexdigest()
    response = auth.post(
        "/api/packs/activate", json={"id": record["id"], "base_url": "https://panel.example.com", "required": True, "prompt": "پک مانیکس"}
    )
    assert response.status_code == 200
    props = auth.get("/api/properties").json()["values"]
    assert props["require-resource-pack"] == "true" and props["resource-pack-sha1"] == record["sha1"]
    assert auth.delete("/api/packs/" + record["id"]).status_code == 409
    backup = wait_job(auth, auth.post("/api/backups").json()["id"])
    with zipfile.ZipFile(io.BytesIO(auth.get(backup["download"]).content)) as zipped:
        assert zipped.read("server/resourcepacks/" + record["id"] + ".zip") == archive
    auth.cookies.clear()
    assert auth.get("/packs/" + record["id"] + ".zip").content == archive
    assert auth.get("/packs/bad.zip").status_code == 404
    assert auth.get("/api/packs").status_code == 401


def test_invalid_packs_and_non_https_base_url(auth):
    assert auth.post("/api/packs/upload", files={"file": ("bad.zip", zip_bytes({"bad/pack.mcmeta": "{}"}))}).status_code == 400
    r = auth.post("/api/packs/upload", files={"file": ("ok.zip", zip_bytes({"pack.mcmeta": '{"pack":{"pack_format":34}}'}))}).json()
    assert auth.post("/api/packs/activate", json={"id": r["id"], "base_url": "http://localhost:8080"}).status_code == 400
    assert auth.post("/api/packs/activate", json={"id": r["id"], "base_url": "https://host.example/path"}).status_code == 400
    assert auth.post("/api/packs/activate", json={"id": ""}).status_code == 200
    assert auth.delete("/api/packs/" + r["id"]).status_code == 200


def task_body(**extra):
    return {"name": "تست مانیکس", "action": "backup", "mode": "daily", "timezone": "Asia/Tehran", "time": "03:30", "enabled": True} | extra


def test_daily_weekly_dst_and_timezone_math():
    now = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc).timestamp()
    value = next_run(task_body(), now)
    assert datetime.fromtimestamp(value, timezone.utc).isoformat() == "2026-10-03T00:00:00+00:00"
    value = next_run(task_body(mode="weekly", weekday=4), now)
    assert datetime.fromtimestamp(value, timezone.utc).isoformat() == "2026-10-09T00:00:00+00:00"
    # Los Angeles 02:30 does not exist on the 2026 spring-forward day.
    base = datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc).timestamp()
    value = next_run(task_body(timezone="America/Los_Angeles", time="02:30"), base)
    assert datetime.fromtimestamp(value, timezone.utc).isoformat() == "2026-03-09T09:30:00+00:00"
    with pytest.raises(PanelError):
        next_run(task_body(timezone="not-a-zone"), now)


def test_schedules_real_job_claim_no_replay_and_missed_skip(auth):
    r = auth.post("/api/schedules", json=task_body())
    assert r.status_code == 200
    task = r.json()
    ctx = auth.app.state.ctx
    due = time.time()
    tasks = ctx.store.get("schedules", {})
    tasks[task["id"]]["next_run"] = due - 1
    ctx.store.put("schedules", tasks)
    auth.portal.call(ctx.schedules.tick, due)
    job_id = ctx.store.get("schedules")[task["id"]]["last_job"]
    assert wait_job(auth, job_id)["state"] == "done"
    auth.portal.call(ctx.schedules.tick, due)
    assert ctx.store.get("schedules")[task["id"]]["last_job"] == job_id
    assert ctx.store.get("schedules")[task["id"]]["last_result"] == "done"
    missed = ctx.store.get("schedules")
    missed[task["id"]]["mode"] = "once"
    missed[task["id"]]["next_run"] = due - 1000
    ctx.store.put("schedules", missed)
    auth.portal.call(ctx.schedules.tick, due)
    result = ctx.store.get("schedules")[task["id"]]
    assert not result["enabled"] and result["last_result"] == "missed"


def test_schedule_toggle_commands_once_and_edit(auth):
    created = auth.post("/api/schedules", json=task_body(enabled=False)).json()
    ident = created["id"]
    assert created["next_run"] is None
    assert auth.patch("/api/schedules/" + ident, json={"enabled": True}).status_code == 200
    assert auth.put("/api/schedules/" + ident, json=task_body(name="updated", mode="weekly", weekday=0)).status_code == 200
    assert auth.post("/api/schedules", json=task_body(action="command", command="say hi\nstop")).status_code == 400
    assert auth.post("/api/schedules", json=task_body(action="command", command="stop")).status_code == 400
    assert auth.post("/api/schedules", json=task_body(mode="once", at="2020-01-01T00:00")).status_code == 400
    assert auth.delete("/api/schedules/" + ident).status_code == 200
    assert auth.get("/api/schedules").json()["tasks"] == []


def test_player_observation_and_ip_actions(auth, settings, monkeypatch):
    tracker = PlayerTracker(auth.app.state.ctx.store)
    tracker.parse("[12:20:00] [Server thread/INFO]: Sample[/10.0.0.2:1234] logged in with entity id 1")
    tracker.parse("[12:20:01] [Server thread/INFO]: Sample joined the game")
    assert tracker.history["Sample"]["joined_at"] is not None
    assert tracker.parse("[12:20:02] [Server thread/INFO]: There are 1 of a max of 20 players online: Sample")
    assert tracker.details([], True)["online"] == ["Sample"]
    tracker.parse("[12:20:03] [Server thread/INFO]: Sample left the game")
    assert not tracker.history["Sample"]["online"]
    configure_fake(auth, settings, monkeypatch)
    started = auth.post("/api/power", json={"action": "start"}).json()
    wait_job(auth, started["id"])
    assert auth.post("/api/players/action", json={"action": "ban_ip", "username": "1.2.3.4"}).status_code == 200
    assert auth.post("/api/players/action", json={"action": "pardon_ip", "username": "bad"}).status_code == 422
    assert auth.post("/api/players/action", json={"action": "whitelist_on"}).status_code == 200
    assert (
        auth.post(
            "/api/players/action", json={"action": "command", "username": "Sample", "command": "give {player} minecraft:diamond 1"}
        ).status_code
        == 200
    )
    assert auth.post("/api/players/action", json={"action": "command", "username": "Sample", "command": "stop"}).status_code == 400


def test_legacy_backup_restore_compatibility(auth, settings):
    archive = zip_bytes({LEGACY_MANIFEST: json.dumps({"format": LEGACY_FORMAT, "engine": None}), "server/legacy.txt": b"old-compatible"})
    imported = auth.post("/api/backups/import", files={"file": ("legacy.zip", archive)}).json()
    assert "name" in imported
    job = auth.post("/api/backups/restore", json={"name": imported["name"]}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert (settings.server_dir / "legacy.txt").read_bytes() == b"old-compatible"


def test_real_node_and_network_metrics_have_honest_scope(auth):
    m = auth.get("/api/status").json()
    assert m["node"]["status"] in {"ready", "initializing"}
    assert m["node"]["memory_source"] in {"cgroup", "estimated-panel-and-game"}
    assert m["node"]["uptime"] >= 0
    assert m["metrics"].get("network_rx_bytes", 0) >= 0


def test_totp_rfc6238_six_digit_vector():
    # RFC 6238 Appendix B SHA1 secret, truncate the 8-digit code to six digits.
    assert totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59 // 30) == "287082"
