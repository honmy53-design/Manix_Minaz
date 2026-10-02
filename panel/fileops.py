"""مانیکس: safe multi-file copy/move/delete built on the existing guarded file root."""

import os
import shutil
import uuid
from pathlib import Path

from .backups import blocking
from .errors import PanelError
from .paths import safe_path, tree_files


def collapse(root, paths):
    result = []
    for value in sorted(set(paths), key=lambda p: (len(Path(p).parts), p)):
        source = safe_path(root, value, allow_root=False)
        if not source.exists():
            raise PanelError("یکی از فایل‌ها پیدا نشد: " + value, 404)
        if not any(source.is_relative_to(parent) for parent in result):
            result.append(source)
    return result


def no_links(source):
    if source.is_symlink():
        raise PanelError("کپی symlink مجاز نیست.")
    if source.is_dir():
        for current, dirs, files in os.walk(source, followlinks=False):
            if any((Path(current) / name).is_symlink() for name in dirs + files):
                raise PanelError("پوشهٔ انتخاب‌شده symlink دارد؛ کپی خودکار انجام نمی‌شود.")


class FileOperations:
    def __init__(self, ctx):
        self.ctx = ctx

    def search(self, path, query, recursive=False):
        root = self.ctx.settings.server_dir
        directory = safe_path(root, path)
        if not directory.is_dir():
            raise PanelError("پوشه پیدا نشد.", 404)
        candidates = directory.rglob("*") if recursive else directory.iterdir()
        query = query.casefold()
        rows, scanned = [], 0
        for file in candidates:
            scanned += 1
            if scanned > 20000:
                break
            try:
                relative = file.relative_to(root).as_posix()
                safe_path(root, relative)
                if query not in file.name.casefold() or file.is_symlink():
                    continue
                info = file.stat()
                rows.append(
                    {
                        "name": file.name,
                        "path": relative,
                        "dir": file.is_dir(),
                        "symlink": False,
                        "size": info.st_size,
                        "modified": info.st_mtime,
                    }
                )
                if len(rows) >= 1000:
                    break
            except (OSError, PanelError):
                continue
        rows.sort(key=lambda row: (not row["dir"], row["path"].casefold()))
        return {"files": rows, "path": path, "limited": scanned > 20000 or len(rows) >= 1000}

    async def batch(self, action, paths, destination=""):
        ctx = self.ctx
        root = ctx.settings.server_dir
        sources = collapse(root, paths)
        stage = ctx.settings.data_dir / "tmp" / ("batch-" + uuid.uuid4().hex)
        stage.mkdir()
        moved, committed = [], False
        try:
            if action in {"copy", "move"}:
                directory = safe_path(root, destination)
                if not directory.is_dir():
                    raise PanelError("پوشهٔ مقصد از قبل باید وجود داشته باشد.")
                targets, names = [], set()
                for source in sources:
                    target = safe_path(directory, source.name, allow_root=False)
                    if target.exists() or target.is_relative_to(source) or source.name in names:
                        raise PanelError("مقصد تکراری، موجود، یا داخل پوشهٔ مبدأ است؛ فایل‌ها جابه‌جا نشدند.", 409)
                    names.add(source.name)
                    targets.append(target)
                if action == "copy":
                    for source in sources:
                        no_links(source)
                    total = sum(
                        sum(p.stat().st_size for p in tree_files(source)) if source.is_dir() else source.stat().st_size
                        for source in sources
                    )
                    if total > ctx.settings.archive_mb * 1024 * 1024 or shutil.disk_usage(stage).free < total + 128 * 1024 * 1024:
                        raise PanelError("فضای کپی کافی نیست یا حجم از سقف پردازش بیشتر است.")
                    for source in sources:
                        if source.is_dir():
                            await blocking(shutil.copytree, source, stage / source.name)
                        else:
                            await blocking(shutil.copy2, source, stage / source.name)
                    written = []
                    try:
                        for source, target in zip(sources, targets):
                            os.replace(stage / source.name, target)
                            written.append(target)
                    except BaseException:
                        for target in written:
                            shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
                        raise
                else:
                    try:
                        for source, target in zip(sources, targets):
                            os.replace(source, target)
                            moved.append((source, target))
                    except BaseException:
                        for source, target in reversed(moved):
                            os.replace(target, source)
                        raise
                committed = True
            elif action == "delete":
                await ctx.backups.snapshot("before-batch-delete")
                try:
                    for index, source in enumerate(sources):
                        target = stage / str(index)
                        os.replace(source, target)
                        moved.append((source, target))
                except BaseException:
                    for source, target in reversed(moved):
                        os.replace(target, source)
                    raise
                committed = True
            else:
                raise PanelError("عملیات گروهی نامعتبر است.")
            ctx.store.audit("file.batch." + action, ", ".join(paths)[:1000])
            return {"message": f"عملیات گروهی روی {len(sources)} مورد انجام شد."}
        finally:
            if not committed:
                for source, target in reversed(moved):
                    if target.exists() and not source.exists():
                        os.replace(target, source)
            await blocking(shutil.rmtree, stage, True)
