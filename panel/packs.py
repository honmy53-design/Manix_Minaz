"""مانیکس: ZIP resource packs with capability-scoped anonymous client downloads."""

import hashlib
import json
import os
import re
import time
import uuid
import zipfile
from urllib.parse import urlsplit

from .backups import blocking
from .errors import PanelError
from .paths import DEFAULT_PROPERTIES, atomic_write, properties_read, properties_write, read_json_file, safe_path, validate_zip


class PackService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.directory = ctx.settings.server_dir / "resourcepacks"
        if self.directory.is_symlink():
            raise RuntimeError("Refusing symlink resourcepacks directory")
        self.directory.mkdir(exist_ok=True, mode=0o700)

    def records(self):
        value = read_json_file(self.directory, ".manix-index.json", {})
        if not isinstance(value, dict):
            raise PanelError("متادیتای Resource Pack نامعتبر است؛ فایل .manix-index.json را بررسی کن.")
        return {key: record for key, record in value.items() if re.fullmatch(r"[a-f0-9]{32}", key) and isinstance(record, dict)}

    def save_records(self, records):
        atomic_write(safe_path(self.directory, ".manix-index.json"), json.dumps(records, ensure_ascii=False).encode())

    def active(self):
        value = properties_read(self.ctx.settings.server_dir).get("resource-pack-id", "").replace("-", "")
        return value if re.fullmatch(r"[a-f0-9]{32}", value) else ""

    def path(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise PanelError("شناسهٔ Resource Pack نامعتبر است.", 404)
        file = safe_path(self.directory, identifier + ".zip", allow_root=False)
        if not file.is_file():
            raise PanelError("Resource Pack پیدا نشد.", 404)
        return file

    @staticmethod
    def inspect(file, maximum):
        validate_zip(file, maximum)
        with zipfile.ZipFile(file) as archive:
            try:
                entry = archive.getinfo("pack.mcmeta")
                if entry.file_size > 1024 * 1024:
                    raise PanelError("pack.mcmeta بیش از حد بزرگ است.")
                metadata = json.loads(archive.read("pack.mcmeta"))
                pack = metadata.get("pack", {})
                formats = [pack.get(name) for name in ["pack_format", "min_format", "max_format"]]

                def valid_format(value):
                    if isinstance(value, bool):
                        return False
                    if isinstance(value, int):
                        return 0 <= value <= 1_000_000
                    return (
                        isinstance(value, list)
                        and len(value) == 2
                        and all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 1_000_000 for n in value)
                    )

                if not isinstance(pack, dict) or not any(valid_format(value) for value in formats):
                    raise ValueError("Missing or invalid pack format")
            except (KeyError, ValueError, TypeError, AttributeError, zipfile.BadZipFile) as exc:
                raise PanelError("ZIP باید pack.mcmeta معتبر در ریشه داشته باشد؛ Minecraft نسخهٔ مناسب پک را هم بررسی می‌کند.") from exc
        digest = hashlib.sha1()
        with file.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest(), next((v for v in formats if v is not None), None)

    def list(self):
        records = self.records()
        active = self.active()
        return {
            "packs": [
                record | {"active": identifier == active}
                for identifier, record in records.items()
                if (self.directory / (identifier + ".zip")).is_file()
            ],
            "active": active,
            "properties": {
                k: v
                for k, v in properties_read(self.ctx.settings.server_dir).items()
                if k.startswith("resource-pack") or k == "require-resource-pack"
            },
        }

    async def upload(self, file, filename):
        digest, pack_format = await blocking(self.inspect, file, self.ctx.settings.archive_mb * 1024 * 1024)
        identifier = uuid.uuid4().hex
        target = self.directory / (identifier + ".zip")
        safe_path(self.ctx.settings.server_dir, "resourcepacks")
        if self.directory.exists() and not self.directory.is_dir():
            raise PanelError("resourcepacks باید پوشه باشد.")
        self.directory.mkdir(exist_ok=True, mode=0o700)
        records = self.records()
        if len(records) >= 50:
            raise PanelError("حداکثر ۵۰ Resource Pack مجاز است.")
        record = {
            "id": identifier,
            "name": filename[:150],
            "sha1": digest,
            "size": file.stat().st_size,
            "format": pack_format,
            "created": time.time(),
        }
        os.replace(file, target)
        try:
            records[identifier] = record
            self.save_records(records)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        self.ctx.store.audit("pack.upload", filename)
        return record

    def activate(self, identifier, base_url, required=False, prompt=""):
        records = self.records()
        if identifier:
            if identifier not in records:
                raise PanelError("Resource Pack پیدا نشد.", 404)
            self.path(identifier)
            parsed = urlsplit(base_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise PanelError("آدرس پایهٔ دانلود باید HTTPS عمومی و فقط دامنه/پورت باشد؛ مثل https://panel.example.com.")
            url = base_url.rstrip("/") + "/packs/" + identifier + ".zip"
        else:
            url = ""
        props = DEFAULT_PROPERTIES | properties_read(self.ctx.settings.server_dir)
        props.update(
            {
                "resource-pack": url,
                "resource-pack-sha1": records[identifier]["sha1"] if identifier else "",
                "require-resource-pack": str(bool(required and identifier)).lower(),
                "resource-pack-prompt": json.dumps({"text": prompt}, ensure_ascii=False) if prompt and identifier else "",
            }
        )
        if identifier:
            props["resource-pack-id"] = str(uuid.UUID(identifier))
        else:
            props.pop("resource-pack-id", None)
        properties_write(self.ctx.settings.server_dir, props)
        self.ctx.store.audit("pack.activate", identifier or "disabled")
        return {"ok": True, "url": url, "sha1": records[identifier]["sha1"] if identifier else ""}

    def delete(self, identifier):
        if self.active() == identifier:
            raise PanelError("اول Resource Pack فعال را غیرفعال یا عوض کن.", 409)
        self.path(identifier).unlink()
        records = self.records()
        records.pop(identifier, None)
        self.save_records(records)
        self.ctx.store.audit("pack.delete", identifier)
