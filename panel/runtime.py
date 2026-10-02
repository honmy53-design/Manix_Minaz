"""مانیکس: shared runtime activation, owner-supplied executable JARs and cleanup."""

import json
import logging
import os
import re
import shutil
import time
import uuid
import zipfile

from .backups import blocking
from .errors import PanelError
from .paths import atomic_write, safe_path, tree_files, validate_zip


async def activate_engine(ctx, engine):
    old = ctx.store.config["engine"]
    engine_dir = ctx.settings.data_dir / "engines" / engine["id"]
    moved, committed = [], False
    try:
        if any(ctx.settings.server_dir.iterdir()):
            await ctx.backups.snapshot("before-version")
        if old and (old["version"] != engine["version"] or old["kind"] != engine["kind"]):
            folders = ["mods", "plugins"]
            if old["version"] == engine["version"] and {old["kind"], engine["kind"]} <= {"paper", "purpur"}:
                folders = ["mods"]
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
            for folder in folders:
                directory = safe_path(ctx.settings.server_dir, folder)
                if directory.is_dir():
                    for jar in directory.glob("*.jar"):
                        if jar.is_symlink() or not jar.is_file():
                            continue
                        dest = safe_path(ctx.settings.server_dir, f"disabled-addons/{stamp}/{folder}/{jar.name}")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(jar, dest)
                        moved.append((jar, dest))
        ctx.store.config["engine"] = engine
        ctx.store.save_config()
        committed = True
        ctx.manager.phase = "stopped"
        ctx.store.audit("engine.install", f"{engine['kind']} {engine['version']}")
        return {"message": "هسته فعال شد. سیو حفظ شد؛ JARهای احتمالاً ناسازگار در disabled-addons مانده‌اند."}
    except BaseException:
        if not committed:
            # A write may have reached SQLite before its caller raises. Never
            # delete a runtime that the durable config already references.
            try:
                persisted = (ctx.store.get("config", {}).get("engine") or {}).get("id")
                committed = persisted == engine["id"]
            except Exception:
                # If the commit cannot be inspected, retaining files is safer
                # than destroying a potentially active runtime.
                committed = True
                logging.exception("Cannot inspect Manix engine commit; preserving runtime")
        if committed:
            ctx.manager.phase = "stopped"
        else:
            ctx.store.config["engine"] = old
            for original, dest in reversed(moved):
                if dest.exists():
                    os.replace(dest, original)
            shutil.rmtree(engine_dir, ignore_errors=True)
        raise


class RuntimeService:
    def __init__(self, ctx):
        self.ctx = ctx

    def list(self):
        rows = []
        active = (self.ctx.store.config.get("engine") or {}).get("id")
        for directory in (self.ctx.settings.data_dir / "engines").iterdir():
            if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", directory.name):
                continue
            try:
                file = safe_path(directory, "engine.json")
                if file.stat().st_size > 1024 * 1024:
                    continue
                engine = json.loads(file.read_text())
                rows.append(
                    {k: engine.get(k) for k in ["id", "kind", "version", "java", "required_java", "build", "installed"]}
                    | {"active": directory.name == active, "size": sum(p.stat().st_size for p in tree_files(directory))}
                )
            except (OSError, ValueError, PanelError):
                continue
        return sorted(rows, key=lambda row: row.get("installed") or 0, reverse=True)

    def delete(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise PanelError("شناسهٔ هسته نامعتبر است.")
        if identifier == (self.ctx.store.config.get("engine") or {}).get("id"):
            raise PanelError("هستهٔ فعال را نمی‌توان حذف کرد.", 409)
        directory = safe_path(self.ctx.settings.data_dir / "engines", identifier, allow_root=False)
        if not directory.is_dir():
            raise PanelError("هسته پیدا نشد.", 404)
        shutil.rmtree(directory)
        self.ctx.store.audit("engine.delete", identifier)
        return {"message": "هستهٔ قدیمی حذف شد؛ Restore بکاپ وابسته به آن ممکن است نصب مجدد همان نسخه را بخواهد."}

    async def import_jar(self, file, kind, version, java, allow_downgrade=False):
        if java not in {8, 17, 21, 25} or kind not in {"spigot", "custom"}:
            raise PanelError("نوع JAR یا Java نامعتبر است.")
        self.ctx.settings.java(java)
        meta = await self.ctx.engines.version_meta(version)
        old = self.ctx.store.config.get("engine")
        if old and self.ctx.backups.worlds() and old.get("release_time", "") > meta.get("releaseTime", "") and not allow_downgrade:
            raise PanelError("خطر Downgrade را صریحاً تأیید کن یا یک دنیای تازه انتخاب کن.")
        await blocking(validate_zip, file, self.ctx.settings.archive_mb * 1024 * 1024)
        with zipfile.ZipFile(file) as archive:
            try:
                if archive.getinfo("META-INF/MANIFEST.MF").file_size > 1024 * 1024:
                    raise ValueError("Manifest too large")
                manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\n ", "")
                match = re.search(r"^Main-Class:\s*([A-Za-z0-9_.$]+)\s*$", manifest, re.M)
                if not match:
                    raise ValueError("No Main-Class")
                entry = match[1].replace(".", "/") + ".class"
                with archive.open(entry) as source:
                    header = source.read(8)
                if len(header) != 8 or header[:4] != b"\xca\xfe\xba\xbe":
                    raise ValueError("Invalid main class")
                required = max(8, int.from_bytes(header[6:8], "big") - 44, int(meta.get("javaVersion", {}).get("majorVersion", 8)))
            except (KeyError, ValueError, zipfile.BadZipFile) as exc:
                raise PanelError("یک JAR سرور اجرایی با Main-Class واقعی آپلود کن؛ JAR نصاب یا پلاگین سرور نیست.") from exc
        if java < required:
            raise PanelError(f"کلاس اصلی یا نسخهٔ Minecraft حداقل Java {required} می‌خواهد.")
        directory = self.ctx.settings.data_dir / "engines" / uuid.uuid4().hex
        directory.mkdir()
        engine = {
            "id": directory.name,
            "kind": kind,
            "version": version,
            "java": java,
            "required_java": required,
            "mode": "jar",
            "entry": "server.jar",
            "build": "manual",
            "installed": time.time(),
            "release_time": meta.get("releaseTime", ""),
            "manual": True,
        }
        try:
            os.replace(file, directory / "server.jar")
            atomic_write(directory / "engine.json", json.dumps(engine).encode())
            return await activate_engine(self.ctx, engine)
        except BaseException:
            # activate_engine rolls back the in-memory pointer before a
            # pre-commit error. A post-commit audit failure must leave the
            # now-active executable intact, even though the Job reports failure.
            if (self.ctx.store.config.get("engine") or {}).get("id") != engine["id"]:
                shutil.rmtree(directory, ignore_errors=True)
            raise
