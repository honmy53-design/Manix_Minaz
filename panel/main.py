import asyncio
import hmac
import ipaddress
import json
import os
import re
import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import __version__
from .backups import BackupService, blocking, merge_tree, read_manifest
from .config import Settings
from .engines import AddonService, Downloads, EngineService
from .errors import PanelError
from .manager import ServerManager
from .paths import (
    DEFAULT_PROPERTIES,
    atomic_write,
    extract_zip,
    normalize,
    properties_read,
    properties_write,
    read_json_file,
    safe_path,
    validate_zip,
)
from .security import COOKIE, LoginLimiter, SecurityMiddleware
from .storage import Store, verify_password

STATIC = Path(__file__).parent / "static"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Model):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    otp: str = Field(default="", max_length=80)


class Power(Model):
    action: Literal["start", "stop", "restart", "kill"]


class Command(Model):
    command: str = Field(min_length=1, max_length=1024)


class Install(Model):
    kind: Literal["vanilla", "paper", "purpur", "fabric", "forge", "neoforge"]
    version: str = Field(min_length=1, max_length=48)
    allow_downgrade: bool = False


def domain(value: str):
    value = value.strip().rstrip(".")
    if not value:
        return ""
    try:
        value = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("دامنه نامعتبر است") from exc
    if len(value) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in value.split(".")):
        raise ValueError("فقط نام دامنه بدون https:// یا پورت را وارد کن")
    return value


class ConfigPatch(Model):
    server_name: str | None = Field(default=None, min_length=1, max_length=80)
    game_port: int | None = Field(default=None, ge=1024, le=65535)
    jvm_args: list[str] | None = None
    memory_mb: int | None = Field(default=None, ge=512, le=65536)
    java_override: Literal[0, 8, 17, 21, 25] | None = None
    eula_accepted: bool | None = None
    autostart: bool | None = None
    auto_restart: bool | None = None
    backup_hours: int | None = Field(default=None, ge=0, le=720)
    restart_hours: int | None = Field(default=None, ge=0, le=720)
    backup_keep: int | None = Field(default=None, ge=1, le=50)
    game_domain: str | None = None
    panel_domain: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = Field(default=None, ge=0, le=65535)

    @field_validator("jvm_args")
    @classmethod
    def check_args(cls, value):
        from .startup import validate_jvm_args

        try:
            return validate_jvm_args(value) if value is not None else value
        except PanelError as exc:
            raise ValueError(exc.message) from exc

    @field_validator("game_domain", "panel_domain", "proxy_host")
    @classmethod
    def check_domain(cls, value):
        return domain(value) if value is not None else value


class Properties(Model):
    values: dict[str, str]


class FileText(Model):
    path: str
    content: str = Field(max_length=1024 * 1024)


class FilePath(Model):
    path: str


class Rename(Model):
    source: str
    target: str


class Extract(Model):
    path: str
    target: str = ""


class BackupName(Model):
    name: str


class Project(Model):
    project_id: str = Field(min_length=1, max_length=80)


class Toggle(Model):
    folder: Literal["mods", "plugins"]
    file: str
    enabled: bool


class PlayerAction(Model):
    action: Literal[
        "op",
        "deop",
        "ban",
        "pardon",
        "kick",
        "whitelist_add",
        "whitelist_remove",
        "ban_ip",
        "pardon_ip",
        "whitelist_on",
        "whitelist_off",
        "command",
    ]
    username: str = Field(default="", max_length=64)
    command: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=200)

    @field_validator("reason")
    @classmethod
    def reason_one_line(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("دلیل باید یک خط باشد")
        return value


@dataclass
class Context:
    settings: Settings
    store: Store
    manager: ServerManager
    downloads: Downloads
    engines: EngineService
    backups: BackupService
    addons: AddonService
    limiter: LoginLimiter


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        store = Store(settings.panel_dir, settings.username, settings.password, settings.defaults())
        manager = ServerManager(settings, store)
        downloads = Downloads()
        engines = EngineService(settings, downloads, manager.log)
        backups = BackupService(settings, store, manager)
        addons = AddonService(settings, store, downloads, manager.log)
        manager.engine_service = engines
        manager.backup_callback = lambda: backups.create(automatic=True)
        ctx = Context(settings, store, manager, downloads, engines, backups, addons, LoginLimiter())
        from .extras import setup_services

        setup_services(ctx)
        app.state.ctx = ctx
        backups.recover_restore()
        manager.phase = "stopped" if store.config.get("engine") else "not_installed"
        # Interrupted scratch files are not part of the saved game; recovery runs first.
        for temporary in (settings.data_dir / "tmp").iterdir():
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary, ignore_errors=True)
            else:
                temporary.unlink(missing_ok=True)
        await manager.boot()
        try:
            yield
        finally:
            await manager.close()
            await downloads.close()

    app = FastAPI(title="مانیکس / Manix", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityMiddleware, settings=settings, context=lambda: getattr(app.state, "ctx", None))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(PanelError)
    async def panel_error(_request, exc):
        return JSONResponse({"detail": exc.message}, exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, exc):
        fields = ", ".join(".".join(str(x) for x in e["loc"][1:]) for e in exc.errors()[:5])
        return JSONResponse({"detail": "مقدار ورودی نامعتبر است: " + fields}, 422)

    @app.get("/healthz")
    async def health():
        return {"ok": True, "service": "مانیکس / Manix"}

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.post("/api/login")
    async def login(request: Request, body: Login):
        async with request.app.state.ctx.account_lock:
            ctx = request.app.state.ctx
            ip = request.client.host if request.client else "unknown"
            if not ctx.limiter.check(ip):
                return JSONResponse({"detail": "تعداد تلاش‌ها زیاد است؛ ۱۵ دقیقه بعد امتحان کن."}, 429, headers={"Retry-After": "900"})
            # Always run the password KDF even if the username does not match.
            correct = await asyncio.to_thread(verify_password, body.password, ctx.store.get("password_hash"))
            if not hmac.compare_digest(body.username.encode(), settings.username.encode()) or not correct:
                ctx.limiter.fail(ip)
                ctx.store.audit("auth.failed", ip)
                return JSONResponse({"detail": "نام کاربری یا رمز درست نیست."}, 401)
            if not ctx.account.verify_second_factor(body.otp):
                ctx.limiter.fail(ip)
                ctx.store.audit("auth.2fa_failed", ip)
                return JSONResponse({"detail": "کد ۲FA یا بازیابی نامعتبر/استفاده‌شده است.", "requires_otp": True}, 401)
            ctx.limiter.success(ip)
            token, csrf = ctx.store.new_session(settings.session_hours, ip, request.headers.get("user-agent", ""))
            response = JSONResponse({"username": settings.username, "csrf": csrf, "version": __version__})
            response.set_cookie(
                COOKIE,
                token,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
                max_age=settings.session_hours * 3600,
                path="/",
            )
            ctx.store.audit("auth.login", ip)
            return response

    @app.get("/api/session")
    async def session(request: Request):
        return {"username": settings.username, "csrf": request.state.session["csrf"], "version": __version__}

    @app.post("/api/logout")
    async def logout(request: Request):
        request.app.state.ctx.store.logout(request.cookies.get(COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/status")
    async def status(request: Request):
        ctx = request.app.state.ctx
        data = ctx.manager.status()
        config = ctx.store.config
        host, port = config["proxy_host"], config["proxy_port"]
        data["address"] = config["game_domain"] or (f"{host}:{port}" if host and port else "")
        data["proxy_address"] = f"{host}:{port}" if host and port else ""
        return data

    @app.get("/api/console")
    async def console(request: Request, after: int = Query(0, ge=0)):
        manager = request.app.state.ctx.manager
        reset = after > manager.sequence
        return {"lines": [r for r in manager.lines if reset or r["id"] > after], "cursor": manager.sequence, "reset": reset}

    @app.get("/api/console/download")
    async def console_download():
        return FileResponse(settings.panel_dir / "console.log", media_type="application/octet-stream", filename="console.log")

    @app.post("/api/console")
    async def command(request: Request, body: Command):
        manager = request.app.state.ctx.manager
        manager.check_available()
        # Power operations must use their guarded routes, not bypass the desired-state flag.
        words = body.command.strip().lstrip("/").lower().split()
        if not words:
            raise PanelError("یک دستور غیرخالی وارد کن.")
        verb = words[0]
        if verb in {"stop", "restart", "minecraft:stop", "spigot:restart", "bukkit:restart"}:
            raise PanelError("برای توقف یا ری‌استارت از دکمه‌های پنل استفاده کن.")
        await manager.command(body.command)
        return {"ok": True}

    @app.post("/api/power")
    async def power(request: Request, body: Power):
        manager = request.app.state.ctx.manager
        funcs = {"start": manager.start, "stop": manager.stop, "restart": manager.restart, "kill": manager.kill}
        titles = {"start": "روشن کردن سرور", "stop": "خاموش کردن سرور", "restart": "ری‌استارت سرور", "kill": "توقف اجباری بازی"}
        return await manager.new_job(titles[body.action], funcs[body.action])

    @app.get("/api/versions")
    async def versions(request: Request, kind: str = "paper"):
        return {"versions": await request.app.state.ctx.engines.versions(kind)}

    @app.post("/api/versions/install")
    async def install(request: Request, body: Install):
        ctx = request.app.state.ctx

        async def operation():
            old = ctx.store.config["engine"]
            target_meta = await ctx.engines.version_meta(body.version)
            if old and ctx.backups.worlds():
                previous = old.get("release_time") or (await ctx.engines.version_meta(old["version"])).get("releaseTime", "")
                if previous > target_meta.get("releaseTime", "") and not body.allow_downgrade:
                    raise PanelError(
                        "Downgrade دنیا ممکن است آن را خراب کند. گزینهٔ پذیرش خطر بازگشت به نسخهٔ قدیمی را فعال کن؛ یا یک دنیای تازه بساز."
                    )
            engine = await ctx.engines.install(body.kind, body.version, ctx.store.config["java_override"])
            engine["release_time"] = target_meta.get("releaseTime", "")
            engine_dir = settings.data_dir / "engines" / engine["id"]
            atomic_write(engine_dir / "engine.json", json.dumps(engine).encode())
            from .runtime import activate_engine

            return await activate_engine(ctx, engine)

        return await ctx.manager.new_job(f"نصب {body.kind} / {body.version}", operation, stopped=True)

    @app.get("/api/settings")
    async def get_settings(request: Request):
        return {
            "config": request.app.state.ctx.store.config,
            "upload_mb": settings.upload_mb,
            "archive_mb": settings.archive_mb,
            "mc_port": request.app.state.ctx.store.config.get("game_port", settings.mc_port),
            "railway": settings.railway,
            "public_domain": os.getenv("RAILWAY_PUBLIC_DOMAIN", ""),
        }

    @app.patch("/api/settings")
    async def update_settings(request: Request, body: ConfigPatch):
        ctx = request.app.state.ctx
        patch = body.model_dump(exclude_none=True)
        async with ctx.manager.exclusive():
            if ctx.manager.running and {"memory_mb", "java_override", "game_port", "jvm_args"}.intersection(patch):
                raise PanelError("برای تغییر رم، Java، پورت یا JVM اول بازی را خاموش کن.", 409)
            if patch.get("game_port") == settings.port:
                raise PanelError("پورت بازی نباید برابر پورت HTTP پنل باشد.")
            ctx.store.config.update(patch)
            ctx.store.save_config()
            ctx.store.audit("settings.update", ",".join(patch))
        return {"ok": True}

    @app.get("/api/properties")
    async def get_properties():
        return {"values": DEFAULT_PROPERTIES | properties_read(settings.server_dir)}

    @app.patch("/api/properties")
    async def set_properties(request: Request, body: Properties):
        ctx = request.app.state.ctx
        values = body.values
        if set(values) - set(DEFAULT_PROPERTIES):
            raise PanelError("برای کلیدهای پیشرفته از ویرایشگر server.properties استفاده کن.")
        ranges = {"max-players": (1, 500), "view-distance": (2, 32), "simulation-distance": (2, 32), "spawn-protection": (0, 128)}
        for key, value in values.items():
            if len(value) > 512 or any(ord(c) < 32 for c in value):
                raise PanelError("مقدار تنظیم نامعتبر است.")
            if key in ranges:
                try:
                    number = int(value)
                except ValueError:
                    raise PanelError(f"{key} باید عدد باشد.") from None
                if not ranges[key][0] <= number <= ranges[key][1]:
                    raise PanelError(f"{key} خارج از محدوده است.")
            if key in {
                "online-mode",
                "white-list",
                "enforce-whitelist",
                "pvp",
                "allow-flight",
                "hardcore",
                "allow-nether",
            } and value not in {"true", "false"}:
                raise PanelError("مقدار کلید روشن/خاموش باید true یا false باشد.")
            if key == "difficulty" and value not in {"peaceful", "easy", "normal", "hard"}:
                raise PanelError("درجهٔ سختی نامعتبر است.")
            if key == "gamemode" and value not in {"survival", "creative", "adventure", "spectator"}:
                raise PanelError("حالت بازی نامعتبر است.")
            if key == "level-name":
                safe_path(settings.server_dir, value, allow_root=False)
        async with ctx.manager.exclusive(stopped=True):
            current = DEFAULT_PROPERTIES | properties_read(settings.server_dir)
            current.update(values)
            properties_write(settings.server_dir, current)
            ctx.store.audit("properties.update", ",".join(values))
        return {"ok": True}

    @app.get("/api/files")
    async def files(path: str = ""):
        directory = safe_path(settings.server_dir, path)
        if not directory.is_dir():
            raise PanelError("پوشه پیدا نشد.", 404)
        rows = []
        for file in directory.iterdir():
            if file.name.startswith(".upload-"):
                continue
            info = file.lstat()
            symlink = file.is_symlink()
            rows.append(
                {
                    "name": file.name,
                    "path": file.relative_to(settings.server_dir).as_posix(),
                    "dir": not symlink and file.is_dir(),
                    "symlink": symlink,
                    "size": info.st_size,
                    "modified": info.st_mtime,
                }
            )
        rows.sort(key=lambda row: (not row["dir"], row["name"].lower()))
        return {"path": normalize(path), "files": rows}

    @app.get("/api/files/text")
    async def file_text(path: str):
        file = safe_path(settings.server_dir, path, allow_root=False)
        if not file.is_file():
            raise PanelError("فایل پیدا نشد.", 404)
        if file.stat().st_size > 1024 * 1024:
            raise PanelError("ویرایشگر فقط فایل‌های متنی تا ۱ مگابایت را باز می‌کند.")
        try:
            content = file.read_text("utf-8")
            if "\x00" in content:
                raise ValueError()
        except (UnicodeError, ValueError):
            raise PanelError("فایل متنی UTF-8 نیست؛ آن را دانلود کن.") from None
        return {"path": path, "content": content}

    @app.put("/api/files/text")
    async def save_text(request: Request, body: FileText):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            file = safe_path(settings.server_dir, body.path, allow_root=False)
            if not file.parent.is_dir() or file.is_dir():
                raise PanelError("پوشهٔ مقصد موجود نیست یا مسیر یک پوشه است.")
            content = body.content.encode("utf-8")
            if len(content) > 1024 * 1024 or b"\x00" in content:
                raise PanelError("ویرایشگر فقط متن UTF-8 بدون NUL و حداکثر ۱ MB را ذخیره می‌کند.")
            atomic_write(file, content)
            ctx.store.audit("file.write", body.path)
        return {"ok": True}

    @app.get("/api/files/download")
    async def file_download(path: str):
        file = safe_path(settings.server_dir, path, allow_root=False)
        if not file.is_file():
            raise PanelError("فایل پیدا نشد.", 404)
        return FileResponse(file, media_type="application/octet-stream", filename=file.name)

    @app.post("/api/files/upload")
    async def upload(request: Request, path: str = "", overwrite: bool = False, file: UploadFile = File(...)):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            directory = safe_path(settings.server_dir, path)
            if not directory.is_dir():
                raise PanelError("پوشهٔ مقصد موجود نیست.", 404)
            filename = file.filename or ""
            if not filename or "/" in filename or "\\" in filename:
                raise PanelError("نام فایل آپلودی نامعتبر است.")
            target = safe_path(directory, filename, allow_root=False)
            if target.exists() and (not overwrite or target.is_dir()):
                raise PanelError("این نام از قبل وجود دارد؛ جایگزینی باید تأیید شود.", 409)
            temp = settings.data_dir / "tmp" / ("upload-" + uuid.uuid4().hex)
            size = 0
            try:
                with temp.open("xb") as out:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.upload_mb * 1024 * 1024:
                            raise PanelError("حجم فایل از سقف آپلود بیشتر است.", 413)
                        out.write(chunk)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
                await file.close()
            ctx.store.audit("file.upload", target.relative_to(settings.server_dir))
        return {"ok": True, "size": size}

    @app.post("/api/files/mkdir")
    async def mkdir(request: Request, body: FilePath):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            directory = safe_path(settings.server_dir, body.path, allow_root=False)
            if directory.exists():
                raise PanelError("این مسیر از قبل وجود دارد.", 409)
            directory.mkdir(parents=True)
            ctx.store.audit("file.mkdir", body.path)
        return {"ok": True}

    @app.post("/api/files/rename")
    async def rename(request: Request, body: Rename):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            source = safe_path(settings.server_dir, body.source, allow_root=False)
            target = safe_path(settings.server_dir, body.target, allow_root=False)
            if not source.exists():
                raise PanelError("فایل پیدا نشد.", 404)
            if target.exists() or not target.parent.is_dir() or target.is_relative_to(source):
                raise PanelError("مقصد معتبر نیست، موجود است یا زیرپوشهٔ مبدأ است.")
            os.replace(source, target)
            ctx.store.audit("file.rename", body.source + " → " + body.target)
        return {"ok": True}

    @app.delete("/api/files")
    async def delete_file(request: Request, body: FilePath):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            file = safe_path(settings.server_dir, body.path, allow_root=False)
            if not file.exists():
                raise PanelError("فایل پیدا نشد.", 404)
            if file.is_dir():
                await blocking(shutil.rmtree, file)
            else:
                file.unlink()
            ctx.store.audit("file.delete", body.path)
        return {"ok": True}

    @app.post("/api/files/extract")
    async def extract(request: Request, body: Extract):
        ctx = request.app.state.ctx

        async def operation():
            source = safe_path(settings.server_dir, body.path, allow_root=False)
            if not source.is_file() or source.suffix.lower() != ".zip":
                raise PanelError("یک فایل ZIP انتخاب کن.")
            destination = safe_path(settings.server_dir, body.target)
            if not destination.is_dir():
                raise PanelError("پوشهٔ مقصد موجود نیست.")
            stage = settings.data_dir / "tmp" / ("extract-" + uuid.uuid4().hex)
            try:
                await blocking(extract_zip, source, stage, settings.archive_mb * 1024 * 1024)
                # A pre-extract snapshot makes accidental overwrites recoverable.
                await ctx.backups.snapshot("before-extract")
                await blocking(merge_tree, stage, destination)
                ctx.store.audit("file.extract", body.path + " → " + body.target)
                return {"message": "ZIP باز شد. فایل‌های هم‌نام جایگزین شده‌اند؛ بکاپ قبل از Extract موجود است."}
            finally:
                shutil.rmtree(stage, ignore_errors=True)

        return await ctx.manager.new_job("باز کردن ZIP", operation, stopped=True)

    @app.post("/api/files/archive")
    async def archive(request: Request, body: FilePath):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job("خروجی ZIP پوشه", lambda: ctx.backups.archive_folder(body.path), stopped=True)

    @app.get("/api/backups")
    async def backup_list(request: Request):
        return {"backups": request.app.state.ctx.backups.list()}

    @app.post("/api/backups")
    async def create_backup(request: Request):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job("ساخت بکاپ کامل", ctx.backups.create)

    @app.post("/api/backups/import")
    async def import_backup(request: Request, file: UploadFile = File(...)):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive():
            temp = settings.data_dir / "tmp" / ("upload-" + uuid.uuid4().hex)
            try:
                size = 0
                with temp.open("xb") as out:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.upload_mb * 1024 * 1024:
                            raise PanelError("حجم بکاپ از سقف آپلود بیشتر است.", 413)
                        out.write(chunk)
                await blocking(validate_zip, temp, settings.archive_mb * 1024 * 1024)
                with zipfile.ZipFile(temp) as archive:
                    read_manifest(archive)
                name = ctx.backups.name("import")
                os.replace(temp, ctx.backups.directory / name)
                ctx.store.audit("backup.import", name)
                return {"ok": True, "name": name}
            finally:
                temp.unlink(missing_ok=True)
                await file.close()

    @app.post("/api/world/export")
    async def export_world(request: Request):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job("آماده‌سازی سیو دنیا", ctx.backups.export_world)

    @app.get("/api/backups/download")
    async def download_backup(request: Request, name: str):
        file = request.app.state.ctx.backups.path(name)
        return FileResponse(file, media_type="application/zip", filename=file.name)

    @app.get("/api/exports/download")
    async def download_export(request: Request, name: str):
        file = request.app.state.ctx.backups.export_path(name)
        return FileResponse(file, media_type="application/zip", filename=file.name)

    @app.post("/api/backups/restore")
    async def restore(request: Request, body: BackupName):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job("بازیابی بکاپ", lambda: ctx.backups.restore(body.name), stopped=True)

    @app.delete("/api/backups")
    async def delete_backup(request: Request, body: BackupName):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive():
            ctx.backups.path(body.name).unlink()
            ctx.store.audit("backup.delete", body.name)
        return {"ok": True}

    @app.get("/api/addons")
    async def addons(request: Request):
        ctx = request.app.state.ctx
        try:
            version, loaders, kind, folder = ctx.addons.context()
            context = {"version": version, "loaders": loaders, "kind": kind, "folder": folder}
        except PanelError as exc:
            context = {"message": exc.message}
        return {"addons": ctx.addons.installed(), "context": context}

    @app.get("/api/addons/search")
    async def search_addons(request: Request, q: str = "", offset: int = Query(0, ge=0, le=10000)):
        return await request.app.state.ctx.addons.search(q, offset)

    @app.post("/api/addons/install")
    async def install_addon(request: Request, body: Project):
        ctx = request.app.state.ctx

        async def operation():
            names = await ctx.addons.install(body.project_id)
            return {"message": "نصب شد: " + "، ".join(names) + ". برای فعال شدن سرور را روشن کن."}

        return await ctx.manager.new_job("نصب افزونه و وابستگی‌های لازم", operation, stopped=True)

    @app.post("/api/addons/toggle")
    async def toggle_addon(request: Request, body: Toggle):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            directory = safe_path(settings.server_dir, body.folder)
            source = safe_path(directory, body.file, allow_root=False)
            if "/" in body.file or not source.is_file():
                raise PanelError("فایل افزونه پیدا نشد.", 404)
            if body.enabled:
                if not source.name.endswith(".jar.disabled"):
                    raise PanelError("این افزونه از قبل فعال است.")
                target = source.with_name(source.name[:-9])
            else:
                if not source.name.endswith(".jar"):
                    raise PanelError("این فایل JAR فعال نیست.")
                target = source.with_name(source.name + ".disabled")
            safe_path(directory, target.name, allow_root=False)
            if target.exists():
                raise PanelError("نام مقصد از قبل وجود دارد.", 409)
            os.replace(source, target)
            ctx.store.audit("addon.toggle", body.folder + "/" + body.file)
        return {"ok": True}

    @app.get("/api/players")
    async def players(request: Request):
        manager = request.app.state.ctx.manager
        await manager.query_players()
        observed = manager.players.details(manager.metrics["players"], manager.running)
        return {
            **observed,
            "count": len(observed["online"]) if observed["source"] == "console-list" else manager.metrics["players_online"],
            "whitelist": read_json_file(settings.server_dir, "whitelist.json", []),
            "ops": read_json_file(settings.server_dir, "ops.json", []),
            "banned": read_json_file(settings.server_dir, "banned-players.json", []),
            "banned_ips": read_json_file(settings.server_dir, "banned-ips.json", []),
        }

    @app.post("/api/players/action")
    async def player_action(request: Request, body: PlayerAction):
        ctx = request.app.state.ctx
        ctx.manager.check_available()
        if body.action in {"ban_ip", "pardon_ip"}:
            try:
                address = str(ipaddress.ip_address(body.username))
            except ValueError:
                raise PanelError("آدرس IP معتبر وارد کن.", 422) from None
            command = ("ban-ip" if body.action == "ban_ip" else "pardon-ip") + " " + address
        elif body.action in {"whitelist_on", "whitelist_off"}:
            command = "whitelist " + ("on" if body.action == "whitelist_on" else "off")
        else:
            if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", body.username):
                raise PanelError("نام بازیکن باید ۳ تا ۱۶ کاراکتر انگلیسی، عدد یا _ باشد.", 422)
            prefix = {"whitelist_add": "whitelist add", "whitelist_remove": "whitelist remove"}.get(body.action, body.action)
            command = prefix + " " + body.username
            if body.action == "command":
                from .schedules import validate_command

                command = validate_command(body.command.replace("{player}", body.username))
        if body.action in {"ban", "kick", "ban_ip"} and body.reason:
            command += " " + body.reason
        await ctx.manager.command(command)
        return {"ok": True}

    @app.get("/api/audit")
    async def audit(request: Request):
        return {"events": request.app.state.ctx.store.audit_rows()}

    from .extras import register_routes

    register_routes(app, settings)
    return app
