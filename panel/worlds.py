"""مانیکس: managed world selection and import without deleting the active world."""

import os
import re
import shutil
import uuid

from .backups import blocking
from .errors import PanelError
from .paths import DEFAULT_PROPERTIES, extract_zip, properties_read, properties_write, safe_path, tree_files

RESERVED = {"mods", "plugins", "logs", "cache", "config", "resourcepacks", "disabled-addons", "libraries", "versions"}


def world_name(name):
    if not re.fullmatch(r"[A-Za-z0-9_\-\u0600-\u06FF ]{1,64}", name) or name in RESERVED or name.startswith(" ") or name.endswith(" "):
        raise PanelError("نام دنیا باید یک نام پوشهٔ ساده و غیررزروشده باشد.")
    return name


class WorldService:
    def __init__(self, ctx):
        self.ctx = ctx

    def active(self):
        return properties_read(self.ctx.settings.server_dir).get("level-name", "world")

    def targets(self, name):
        root = self.ctx.settings.server_dir
        main = safe_path(root, name, allow_root=False)
        if not main.is_dir() or name in RESERVED:
            raise PanelError("پوشهٔ دنیا پیدا نشد.", 404)
        return [
            safe_path(root, candidate) for candidate in [name, name + "_nether", name + "_the_end"] if safe_path(root, candidate).is_dir()
        ]

    def list(self):
        root = self.ctx.settings.server_dir
        active = self.active()
        registry = self.ctx.store.get("world_registry", [])
        names = set(registry + [active])
        for folder in root.iterdir():
            if folder.is_dir() and not folder.is_symlink() and folder.name not in RESERVED and (folder / "level.dat").is_file():
                names.add(folder.name)
        rows = []
        for name in sorted(names):
            try:
                folder = safe_path(root, name, allow_root=False)
                if not folder.is_dir():
                    continue
                if name.endswith(("_nether", "_the_end")) and name != active:
                    continue
                targets = self.targets(name)
                size = sum(p.stat().st_size for target in targets for p in tree_files(target))
                rows.append(
                    {
                        "name": name,
                        "active": name == active,
                        "size": size,
                        "generated": (folder / "level.dat").is_file(),
                        "dimensions": [target.relative_to(root).as_posix() for target in targets],
                        "modified": folder.stat().st_mtime,
                    }
                )
            except (PanelError, OSError):
                continue
        return {"worlds": rows, "active": active}

    def create(self, name):
        name = world_name(name)
        target = safe_path(self.ctx.settings.server_dir, name, allow_root=False)
        if target.exists():
            raise PanelError("این پوشه از قبل وجود دارد.", 409)
        target.mkdir()
        registry = self.ctx.store.get("world_registry", [])
        self.ctx.store.put("world_registry", sorted(set(registry + [name])))
        return {"message": "پوشه ساخته شد؛ آن را فعال و بازی را روشن کن تا Minecraft دنیا را تولید کند."}

    def select(self, name):
        self.targets(name)
        props = DEFAULT_PROPERTIES | properties_read(self.ctx.settings.server_dir)
        props["level-name"] = name
        properties_write(self.ctx.settings.server_dir, props)
        self.ctx.store.audit("world.select", name)
        return {"ok": True}

    async def export(self, name):
        async def make():
            targets = self.targets(name)
            filename = await blocking(self.ctx.backups.export_sync, targets, "world")
            return {"download": "/api/exports/download?name=" + filename}

        return await self.ctx.backups.consistent(make)

    async def delete(self, name):
        if name == self.active():
            raise PanelError("دنیاى فعال را حذف نکن؛ ابتدا یک دنیای دیگر را فعال کن.", 409)
        targets = self.targets(name)
        await self.ctx.backups.snapshot("before-world-delete")
        for target in targets:
            await blocking(shutil.rmtree, target)
        self.ctx.store.put("world_registry", [n for n in self.ctx.store.get("world_registry", []) if n != name])
        return {"message": "دنیا و پوشه‌های ابعاد وابسته حذف شدند؛ بکاپ قبل از حذف موجود است."}

    async def import_zip(self, archive, name):
        name = world_name(name)
        root = self.ctx.settings.server_dir
        target = safe_path(root, name, allow_root=False)
        if target.exists():
            raise PanelError("برای وارد کردن، نامی تازه انتخاب کن؛ جایگزینی دنیا از طریق Restore یا فایل‌منیجر انجام می‌شود.", 409)
        stage = self.ctx.settings.data_dir / "tmp" / ("world-" + uuid.uuid4().hex)
        moved = []
        try:
            await blocking(extract_zip, archive, stage, self.ctx.settings.archive_mb * 1024 * 1024)
            if (stage / "level.dat").is_file():
                source = stage
            else:
                choices = [
                    p
                    for p in stage.iterdir()
                    if p.is_dir() and (p / "level.dat").is_file() and not p.name.endswith(("_nether", "_the_end"))
                ]
                if len(choices) != 1:
                    raise PanelError(
                        "ZIP باید level.dat در ریشه یا دقیقاً یک پوشهٔ دنیای اصلی داشته باشد؛ ZIP چنددنیا را از فایل‌منیجر Extract کن."
                    )
                source = choices[0]
            pairs = [(source, target)]
            if source != stage:
                for suffix in ["_nether", "_the_end"]:
                    dim = stage / (source.name + suffix)
                    if dim.is_dir():
                        destination = safe_path(root, name + suffix)
                        if destination.exists():
                            raise PanelError("پوشهٔ ابعاد مقصد از قبل وجود دارد.", 409)
                        pairs.append((dim, destination))
            for source, destination in pairs:
                os.replace(source, destination)
                moved.append((source, destination))
            registry = self.ctx.store.get("world_registry", [])
            self.ctx.store.put("world_registry", sorted(set(registry + [name])))
            return {"message": "سیو وارد شد. برای بازی، آن را فعال کن؛ تبدیل ساختار ابعاد بین هسته‌ها خودکار نیست."}
        except BaseException:
            for source, destination in reversed(moved):
                if destination.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, source)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
