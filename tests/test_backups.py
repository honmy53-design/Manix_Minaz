"""مانیکس / Manix project module."""

import io
import zipfile

from conftest import wait_job


def test_backup_restore_and_no_panel_secrets(auth, settings):
    auth.post("/api/files/mkdir", json={"path": "world"})
    auth.put("/api/files/text", json={"path": "world/level.dat", "content": "first save"})
    job = auth.post("/api/backups").json()
    complete = wait_job(auth, job["id"])
    assert complete["state"] == "done"
    archive = auth.get(complete["download"]).content
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.read("server/world/level.dat") == b"first save"
        assert not any("panel.sqlite3" in name for name in z.namelist())
        assert b"test-only-long-password" not in z.read(".manix-backup.json")
    auth.put("/api/files/text", json={"path": "world/level.dat", "content": "changed save"})
    name = auth.get("/api/backups").json()["backups"][0]["name"]
    restore = auth.post("/api/backups/restore", json={"name": name}).json()
    assert wait_job(auth, restore["id"])["state"] == "done"
    assert (settings.server_dir / "world/level.dat").read_text() == "first save"
    assert any(x["name"].startswith("safety-") for x in auth.get("/api/backups").json()["backups"])


def test_backup_filename_protection(auth):
    assert auth.get("/api/backups/download?name=../../panel/panel.sqlite3").status_code == 400
    assert auth.get("/api/exports/download?name=../x.zip").status_code == 400


def test_backup_import(auth):
    job = auth.post("/api/backups").json()
    complete = wait_job(auth, job["id"])
    content = auth.get(complete["download"]).content
    result = auth.post("/api/backups/import", files={"file": ("backup.zip", content)})
    assert result.status_code == 200
    assert result.json()["name"].startswith("import-")
    assert auth.post("/api/backups/import", files={"file": ("bad.zip", b"not a zip")}).status_code == 400
