"""مانیکس / Manix project module."""

import io
import zipfile

import pytest

from panel.engines import checked_url, neo_prefix, supported_release
from panel.errors import PanelError
from conftest import wait_job


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.modrinth.com/a.jar",
        "https://127.0.0.1/x",
        "https://169.254.169.254/x",
        "https://evil.example/x",
        "https://cdn.modrinth.com:123/x",
        "https://user:pass@cdn.modrinth.com/a",
    ],
)
def test_ssrf_allowlist(url):
    with pytest.raises(PanelError):
        checked_url(url)


def test_versions_and_neo_mapping():
    assert supported_release("1.8.9") and supported_release("26.3")
    assert not supported_release("1.7.10")
    assert neo_prefix("1.21.1") == "21.1."
    assert neo_prefix("1.21") == "21.0."
    assert neo_prefix("26.3") == "26.3.0."


def test_toggle_addon(auth, settings):
    auth.post("/api/files/mkdir", json={"path": "mods"})
    auth.post("/api/files/upload?path=mods", files={"file": ("my-mod.jar", b"jar")})
    assert auth.post("/api/addons/toggle", json={"folder": "mods", "file": "my-mod.jar", "enabled": False}).status_code == 200
    assert (settings.server_dir / "mods/my-mod.jar.disabled").exists()
    assert auth.post("/api/addons/toggle", json={"folder": "mods", "file": "my-mod.jar.disabled", "enabled": True}).status_code == 200
    assert (settings.server_dir / "mods/my-mod.jar").exists()


def test_modrinth_install_dependencies(auth, settings, monkeypatch):
    ctx = auth.app.state.ctx
    ctx.store.config["engine"] = {"kind": "fabric", "version": "1.21.1"}
    projects = {
        "main": {"id": "main", "title": "Main mod", "server_side": "required"},
        "dep": {"id": "dep", "title": "Dependency", "server_side": "optional"},
    }

    def version(pid):
        return {
            "id": "v" + pid,
            "project_id": pid,
            "version_number": "1.0",
            "version_type": "release",
            "date_published": "2026-01-01",
            "game_versions": ["1.21.1"],
            "loaders": ["fabric"],
            "files": [
                {"filename": pid + ".jar", "url": "https://cdn.modrinth.com/" + pid + ".jar", "primary": True, "hashes": {"sha1": "abc"}}
            ],
            "dependencies": [{"project_id": "dep", "version_id": None, "dependency_type": "required"}] if pid == "main" else [],
        }

    async def data(url, ttl=300):
        for pid in projects:
            if f"/project/{pid}/version?" in url:
                return [version(pid)]
            if url.endswith("/project/" + pid):
                return projects[pid]
        raise AssertionError(url)

    async def jar(url, target, checksum=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0")
        target.write_bytes(stream.getvalue())

    monkeypatch.setattr(ctx.downloads, "data", data)
    monkeypatch.setattr(ctx.downloads, "jar", jar)
    job = auth.post("/api/addons/install", json={"project_id": "main"}).json()
    assert wait_job(auth, job["id"])["state"] == "done"
    assert (settings.server_dir / "mods/main.jar").exists()
    assert (settings.server_dir / "mods/dep.jar").exists()


def test_client_only_mod_rejected(auth, monkeypatch):
    ctx = auth.app.state.ctx
    ctx.store.config["engine"] = {"kind": "fabric", "version": "1.21.1"}

    async def data(url, ttl=300):
        return {"id": "client", "title": "Client mod", "server_side": "unsupported"}

    monkeypatch.setattr(ctx.downloads, "data", data)
    job = auth.post("/api/addons/install", json={"project_id": "client"}).json()
    assert wait_job(auth, job["id"])["state"] == "failed"
