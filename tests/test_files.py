"""مانیکس / Manix project module."""

import io
import stat
import zipfile

import pytest

from panel.errors import PanelError
from panel.paths import DEFAULT_PROPERTIES, extract_zip, properties_read, properties_write, validate_zip
from conftest import wait_job


@pytest.mark.parametrize("path", ["../panel/panel.sqlite3", "/etc/passwd", "a/../../x", "a\\..\\x", "C:/Windows", "a//b", "a/./b"])
def test_traversal(auth, path):
    assert auth.get("/api/files", params={"path": path}).status_code == 400


def test_symlink_protection(auth, settings, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("not in game root")
    (settings.server_dir / "link").symlink_to(secret)
    assert auth.get("/api/files/text?path=link").status_code == 400
    assert auth.get("/api/files/download?path=link").status_code == 400
    assert auth.request("DELETE", "/api/files", json={"path": "link"}).status_code == 400
    assert secret.read_text() == "not in game root"


def test_file_lifecycle(auth):
    assert auth.post("/api/files/mkdir", json={"path": "mods"}).status_code == 200
    assert auth.post("/api/files/upload?path=mods", files={"file": ("hello.jar", b"my file")}).status_code == 200
    assert auth.get("/api/files/download?path=mods/hello.jar").content == b"my file"
    assert auth.post("/api/files/rename", json={"source": "mods/hello.jar", "target": "mods/other.jar"}).status_code == 200
    assert auth.request("DELETE", "/api/files", json={"path": "mods/other.jar"}).status_code == 200
    assert auth.get("/api/files?path=mods").json()["files"] == []


def test_edit_unicode_and_upload_overwrite(auth):
    assert auth.put("/api/files/text", json={"path": "config.txt", "content": "سلام سرور"}).status_code == 200
    assert auth.get("/api/files/text?path=config.txt").json()["content"] == "سلام سرور"
    assert auth.put("/api/files/text", json={"path": "invalid.txt", "content": "a\x00b"}).status_code == 400
    assert auth.put("/api/files/text", json={"path": "big-utf8.txt", "content": "ض" * (512 * 1024 + 1)}).status_code in {400, 413}
    assert auth.post("/api/files/upload", files={"file": ("config.txt", b"replace")}).status_code == 409
    assert auth.post("/api/files/upload?overwrite=true", files={"file": ("config.txt", b"replace")}).status_code == 200


def test_protected_root(auth):
    assert auth.request("DELETE", "/api/files", json={"path": ""}).status_code == 400
    assert auth.post("/api/files/rename", json={"source": "", "target": "something"}).status_code == 400


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return stream.getvalue()


def test_extract_and_world_export(auth, settings):
    data = zip_bytes({"world/level.dat": b"fake-world", "world/region/r.0.0.mca": b"save"})
    assert auth.post("/api/files/upload", files={"file": ("save.zip", data)}).status_code == 200
    result = auth.post("/api/files/extract", json={"path": "save.zip", "target": ""})
    assert wait_job(auth, result.json()["id"])["state"] == "done"
    assert (settings.server_dir / "world/level.dat").read_bytes() == b"fake-world"
    result = auth.post("/api/world/export")
    job = wait_job(auth, result.json()["id"])
    assert job["state"] == "done"
    with zipfile.ZipFile(io.BytesIO(auth.get(job["download"]).content)) as archive:
        assert archive.read("world/region/r.0.0.mca") == b"save"
        assert ".manix-backup.json" not in archive.namelist()


def test_malicious_zip_rejected(auth, settings):
    data = zip_bytes({"../escaped.txt": b"no", "world/level.dat": b"x"})
    auth.post("/api/files/upload", files={"file": ("bad.zip", data)})
    job = auth.post("/api/files/extract", json={"path": "bad.zip"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
    assert not (settings.data_dir / "escaped.txt").exists()
    assert not (settings.server_dir / "world").exists()


def test_zip_symlink_and_bomb_limits(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(entry, "/etc/passwd")
    with pytest.raises(PanelError):
        validate_zip(archive, 1024 * 1024)
    archive.write_bytes(zip_bytes({"big.txt": b"0" * 10000}))
    with pytest.raises(PanelError):
        extract_zip(archive, tmp_path / "extract", 100)


def test_properties_roundtrip_unicode(settings):
    settings.prepare()
    values = DEFAULT_PROPERTIES | {"motd": "سلام 😄 = Hello", "custom-key": "value: test\\here"}
    properties_write(settings.server_dir, values)
    assert properties_read(settings.server_dir) == values


def test_properties_rejects_unsafe_level(auth):
    assert auth.patch("/api/properties", json={"values": {"level-name": "../panel"}}).status_code == 400
    assert auth.patch("/api/properties", json={"values": {"max-players": "-1"}}).status_code == 400


def test_archive_api_folder(auth):
    auth.post("/api/files/mkdir", json={"path": "world"})
    auth.put("/api/files/text", json={"path": "world/test.txt", "content": "saved"})
    job = auth.post("/api/files/archive", json={"path": "world"}).json()
    job = wait_job(auth, job["id"])
    assert job["state"] == "done"
