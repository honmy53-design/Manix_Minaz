import asyncio
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from .errors import PanelError
from .paths import atomic_write, extract_zip, properties_read, safe_path, tree_files, validate_zip

FORMAT = "manix.backup.v1"
MANIFEST_FILE = ".manix-backup.json"


# Read-only compatibility identifier; new files and branding always use Manix.
LEGACY_MANIFEST = bytes.fromhex("2e6d696e65646f636b2d6261636b75702e6a736f6e").decode()
LEGACY_FORMAT = bytes.fromhex("6d696e65646f636b2e6261636b75702e7631").decode()


def read_manifest(archive):
    names = [name for name in [MANIFEST_FILE, LEGACY_MANIFEST] if name in archive.namelist()]
    if len(names) != 1:
        raise PanelError("این ZIP بکاپ سازگار مانیکس نیست؛ سیو معمولی را از مدیریت دنیا وارد کن.")
    name = names[0]
    try:
        if archive.getinfo(name).file_size > 1024 * 1024:
            raise PanelError("متادیتای بکاپ بیش از حد بزرگ است.")
        manifest = json.loads(archive.read(name))
    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise PanelError("متادیتای بکاپ معتبر نیست.") from exc
    if not isinstance(manifest, dict) or manifest.get("format") not in {FORMAT, LEGACY_FORMAT}:
        raise PanelError("فرمت بکاپ پشتیبانی نمی‌شود.")
    if manifest.get("engine") is not None and not isinstance(manifest["engine"], dict):
        raise PanelError("متادیتای هستهٔ بکاپ نامعتبر است.")
    if any(i.filename != name and not i.filename.startswith("server/") for i in archive.infolist()):
        raise PanelError("ساختار بکاپ نامعتبر است.")
    return manifest


async def blocking(function, *args):
    # Cancellation must not delete a staging directory while its worker is still writing.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def merge_tree(stage: Path, destination: Path):
    files = list(tree_files(stage))
    directories = [p for p in stage.rglob("*") if p.is_dir() and not p.is_symlink()]
    for path in directories + files:
        target = safe_path(destination, path.relative_to(stage).as_posix(), allow_root=False)
        if target.exists() and target.is_dir() != path.is_dir():
            raise PanelError("فایل‌های ZIP با پوشه‌های فعلی تداخل دارند.")
    rollback = stage.parent / ("rollback-" + uuid.uuid4().hex)
    rollback.mkdir()
    moved, written, created = [], [], []
    try:
        for directory in sorted(directories, key=lambda p: len(p.parts)):
            target = destination / directory.relative_to(stage)
            if not target.exists():
                target.mkdir(parents=True)
                created.append(target)
        for file in files:
            rel = file.relative_to(stage)
            target = safe_path(destination, rel.as_posix(), allow_root=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                saved = rollback / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, saved)
                moved.append(rel)
            os.replace(file, target)
            written.append(rel)
    except BaseException:
        for rel in written:
            (destination / rel).unlink(missing_ok=True)
        for rel in moved:
            os.replace(rollback / rel, destination / rel)
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(rollback, ignore_errors=True)


class BackupService:
    def __init__(self, settings, store, manager):
        self.settings, self.store, self.manager = settings, store, manager
        self.directory = settings.data_dir / "backups"
        self.exports = settings.data_dir / "exports"

    def name(self, prefix):
        return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}.zip"

    def path(self, name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}\.zip", name):
            raise PanelError("نام بکاپ نامعتبر است.")
        file = safe_path(self.directory, name, allow_root=False)
        if not file.is_file():
            raise PanelError("بکاپ پیدا نشد.", 404)
        return file

    def export_path(self, name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}\.zip", name):
            raise PanelError("نام خروجی نامعتبر است.")
        file = safe_path(self.exports, name, allow_root=False)
        if not file.is_file():
            raise PanelError("خروجی پیدا نشد؛ ممکن است فایل موقت پاک شده باشد.", 404)
        return file

    def list(self):
        results = []
        for file in sorted(self.directory.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            if file.is_symlink():
                continue
            results.append(
                {
                    "name": file.name,
                    "size": file.stat().st_size,
                    "created": file.stat().st_mtime,
                    "automatic": file.name.startswith("auto-"),
                }
            )
        return results

    def snapshot_sync(self, filename):
        root = self.settings.server_dir
        files = list(tree_files(root))
        estimated = sum(f.stat().st_size for f in files)
        if shutil.disk_usage(self.directory).free < estimated + 128 * 1024 * 1024:
            raise PanelError("فضای کافی برای ساخت بکاپ وجود ندارد؛ فایل اضافی پاک کن یا Volume را بزرگ‌تر کن.")
        target = self.directory / filename
        partial = target.with_suffix(".part")
        manifest = {
            "format": FORMAT,
            "created": time.time(),
            "engine": self.store.config.get("engine"),
            "server_name": self.store.config["server_name"],
        }
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
                archive.writestr(MANIFEST_FILE, json.dumps(manifest, ensure_ascii=False))
                archive.write(root, "server/")
                for file in files:
                    archive.write(file, "server/" + file.relative_to(root).as_posix())
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        return filename

    async def snapshot(self, prefix="manual"):
        return await blocking(self.snapshot_sync, self.name(prefix))

    async def consistent(self, action):
        was_running = self.manager.running
        if was_running:
            await self.manager.stop(internal=True)
        try:
            return await action()
        finally:
            if was_running and not self.manager.closing:
                try:
                    await self.manager.start(internal=True)
                except PanelError as exc:
                    self.manager.log("راه‌اندازی پس از بکاپ/خروجی ناموفق بود: " + exc.message, "panel")

    async def create(self, automatic=False):
        async def make():
            name = await self.snapshot("auto" if automatic else "manual")
            self.manager.log("بکاپ ذخیره شد: " + name, "panel")
            if automatic:
                self.store.config["last_auto_backup"] = time.time()
                self.store.save_config()
                keep = self.store.config["backup_keep"]
                auto_files = [x for x in self.list() if x["automatic"]]
                for record in auto_files[keep:]:
                    self.path(record["name"]).unlink()
            return {
                "message": "بکاپ ذخیره شد. برای امنیت بیشتر یک نسخه را روی کامپیوترت دانلود کن.",
                "download": "/api/backups/download?name=" + name,
            }

        return await self.consistent(make)

    def worlds(self):
        root = self.settings.server_dir
        level = properties_read(root).get("level-name", "world")
        result = []
        for name in [level, level + "_nether", level + "_the_end"]:
            folder = safe_path(root, name, allow_root=False)
            if folder.is_dir():
                result.append(folder)
        for folder in root.iterdir():
            if folder.is_dir() and not folder.is_symlink() and (folder / "level.dat").is_file() and folder not in result:
                result.append(folder)
        return result

    def export_sync(self, targets, prefix):
        name = self.name(prefix)
        target = self.exports / name
        partial = target.with_suffix(".part")
        files = [(root, f) for root in targets for f in tree_files(root)]
        size = sum(f.stat().st_size for _, f in files)
        if shutil.disk_usage(self.exports).free < size + 128 * 1024 * 1024:
            raise PanelError("فضای کافی برای خروجی ZIP وجود ندارد.")
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
                for root in targets:
                    archive.write(root, root.relative_to(self.settings.server_dir).as_posix() + "/")
                for _, file in files:
                    archive.write(file, file.relative_to(self.settings.server_dir).as_posix())
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        self.clean_exports(keep=name)
        return name

    def clean_exports(self, keep=None):
        for file in self.exports.glob("*.zip"):
            if file.name != keep and file.stat().st_mtime < time.time() - 86400:
                file.unlink(missing_ok=True)

    async def export_world(self):
        async def make():
            targets = self.worlds()
            if not targets:
                raise PanelError("هنوز دنیایی ساخته نشده. سرور را یک بار روشن کن یا سیو را آپلود کن.")
            name = await blocking(self.export_sync, targets, "world")
            return {"message": "سیو دنیا آمادهٔ دانلود است (بدون فایل مودها و پلاگین‌ها).", "download": "/api/exports/download?name=" + name}

        return await self.consistent(make)

    async def archive_folder(self, relative):
        folder = safe_path(self.settings.server_dir, relative, allow_root=False)
        if not folder.is_dir():
            raise PanelError("پوشه پیدا نشد.", 404)
        name = await blocking(self.export_sync, [folder], "folder")
        return {"download": "/api/exports/download?name=" + name}

    def restore_engine(self, manifest):
        wanted = manifest.get("engine")
        current = self.store.config.get("engine")
        if wanted and re.fullmatch(r"[a-f0-9]{32}", str(wanted.get("id", ""))):
            base = safe_path(self.settings.data_dir / "engines", wanted["id"])
            metadata = base / "engine.json"
            if metadata.is_file():
                saved = json.loads(metadata.read_text())
                if saved.get("version") == wanted.get("version") and saved.get("kind") == wanted.get("kind"):
                    return saved
        if wanted and current and current["kind"] == wanted.get("kind") and current["version"] == wanted.get("version"):
            return current
        if not wanted:
            return current
        raise PanelError(f"اول نسخهٔ {wanted.get('kind')} / {wanted.get('version')} را نصب کن؛ موتور این بکاپ روی Volume فعلی نیست.")

    async def restore(self, name):
        archive = self.path(name)
        stage = self.settings.data_dir / "tmp" / ("restore-" + uuid.uuid4().hex)
        try:
            validate_zip(archive, self.settings.archive_mb * 1024 * 1024)
            with zipfile.ZipFile(archive) as zipf:
                manifest = read_manifest(zipf)
            engine = self.restore_engine(manifest)
            await blocking(extract_zip, archive, stage, self.settings.archive_mb * 1024 * 1024)
            restored = stage / "server"
            if not restored.is_dir():
                raise PanelError("بکاپ پوشهٔ server ندارد.")
            safety = await self.snapshot("safety")
            old = self.settings.data_dir / "tmp" / ("restore-old-" + uuid.uuid4().hex)
            journal = self.settings.panel_dir / "restore-journal.json"
            plan = {"old": old.name, "stage": stage.name, "old_engine": self.store.config["engine"], "new_engine": engine}
            atomic_write(journal, json.dumps(plan).encode())
            try:
                os.replace(self.settings.server_dir, old)
                os.replace(restored, self.settings.server_dir)
                self.store.config["engine"] = engine
                self.store.save_config()
                journal.unlink()
            except BaseException:
                if old.exists():
                    if self.settings.server_dir.exists():
                        shutil.rmtree(self.settings.server_dir)
                    os.replace(old, self.settings.server_dir)
                    self.store.config["engine"] = plan["old_engine"]
                    self.store.save_config()
                journal.unlink(missing_ok=True)
                raise
            shutil.rmtree(old, ignore_errors=True)
            self.store.audit("backup.restore", name)
            return {"message": f"بکاپ بازیابی شد؛ نسخهٔ پیش از بازیابی هم در {safety} نگه داشته شد. سرور خاموش است."}
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def recover_restore(self):
        journal = self.settings.panel_dir / "restore-journal.json"
        if not journal.is_file():
            return
        plan = json.loads(journal.read_text())
        if not re.fullmatch(r"restore-old-[a-f0-9]{32}", plan.get("old", "")) or not re.fullmatch(
            r"restore-[a-f0-9]{32}", plan.get("stage", "")
        ):
            raise RuntimeError("Invalid restore recovery journal; inspect the volume manually.")
        old = self.settings.data_dir / "tmp" / plan["old"]
        staged = self.settings.data_dir / "tmp" / plan["stage"] / "server"
        if old.exists():
            if staged.exists():
                shutil.rmtree(self.settings.server_dir, ignore_errors=True)
                os.replace(old, self.settings.server_dir)
                self.store.config["engine"] = plan["old_engine"]
                self.manager.log("بازیابی قطع‌شده لغو شد؛ فایل‌های پیش از بازیابی برگشتند.", "panel")
            else:
                self.store.config["engine"] = plan["new_engine"]
                shutil.rmtree(old, ignore_errors=True)
                self.manager.log("بازیابی قطع‌شده تکمیل شد.", "panel")
            self.store.save_config()
        journal.unlink(missing_ok=True)
