"""مانیکس: route wiring for real single-service extensions; no provisioning mock APIs."""

import asyncio
import re
import time
import uuid
from typing import Literal

from fastapi import File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import API_SCOPES, AccountService
from .backups import blocking
from .errors import PanelError
from .fileops import FileOperations
from .packs import PackService
from .runtime import RuntimeService
from .schedules import ScheduleService
from .security import COOKIE
from .startup import preview
from .worlds import WorldService


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Password(Model):
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(Password):
    new_password: str = Field(min_length=12, max_length=256)


class Profile(Model):
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(default="", max_length=254)


class Code(Model):
    code: str = Field(min_length=1, max_length=80)


class FactorDisable(Password, Code):
    pass


class Key(Password):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=20)
    days: int = Field(default=90, ge=1, le=365)


class FileBatch(Model):
    action: Literal["copy", "move", "delete"]
    paths: list[str] = Field(min_length=1, max_length=200)
    destination: str = ""


class WorldName(Model):
    name: str = Field(min_length=1, max_length=64)


class Pack(Model):
    id: str = Field(default="", max_length=32)
    base_url: str = Field(default="", max_length=300)
    required: bool = False
    prompt: str = Field(default="", max_length=200)


class Task(Model):
    name: str = Field(min_length=1, max_length=80)
    action: Literal["start", "stop", "restart", "backup", "command"]
    mode: Literal["once", "daily", "weekly"]
    timezone: str = Field(default="Asia/Tehran", max_length=80)
    at: str = Field(default="", max_length=100)
    time: str = Field(default="03:00", max_length=5)
    weekday: int = Field(default=4, ge=0, le=6)
    command: str = Field(default="", max_length=1024)
    enabled: bool = True


class Enabled(Model):
    enabled: bool


def setup_services(ctx):
    ctx.account_lock = asyncio.Lock()
    ctx.account = AccountService(ctx.store)
    ctx.account.reset_from_environment()
    ctx.files = FileOperations(ctx)
    ctx.worlds = WorldService(ctx)
    ctx.packs = PackService(ctx)
    ctx.runtime = RuntimeService(ctx)
    ctx.schedules = ScheduleService(ctx)
    ctx.manager.schedule_callback = ctx.schedules.tick


async def reauthenticate(request, password):
    ctx = request.app.state.ctx
    ip = request.client.host if request.client else "unknown"
    if not ctx.limiter.check(ip):
        raise PanelError("تعداد تلاش‌ها زیاد است؛ ۱۵ دقیقه بعد امتحان کن.", 429)
    try:
        await asyncio.to_thread(ctx.account.reauthenticate, password)
    except PanelError:
        ctx.limiter.fail(ip)
        ctx.store.audit("auth.reauth_failed", ip)
        raise


async def receive_upload(settings, file):
    temp = settings.data_dir / "tmp" / ("upload-" + uuid.uuid4().hex)
    size = 0
    try:
        with temp.open("xb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.upload_mb * 1024 * 1024:
                    raise PanelError("حجم آپلود از سقف مجاز بیشتر است.", 413)
                target.write(chunk)
        if not size:
            raise PanelError("فایل خالی است.")
        return temp
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def register_routes(app, settings):
    @app.get("/api/account")
    async def account(request: Request):
        ctx = request.app.state.ctx
        return ctx.account.profile() | {
            "devices": ctx.store.devices(request.state.session["id"]),
            "scopes": sorted(API_SCOPES),
            "api_keys": ctx.store.api_keys(),
        }

    @app.patch("/api/account")
    async def profile(request: Request, body: Profile):
        if body.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email):
            raise PanelError("ایمیل معتبر وارد کن؛ این ایمیل تأیید یا برای بازیابی ارسال نمی‌شود.")
        ctx = request.app.state.ctx
        ctx.store.put("display_name", body.display_name.strip())
        ctx.store.put("contact_email", body.email.strip())
        ctx.store.audit("account.profile", body.display_name)
        return {"ok": True}

    @app.post("/api/account/password")
    async def password(request: Request, body: PasswordChange):
        async with request.app.state.ctx.account_lock:
            await reauthenticate(request, body.password)
            ctx = request.app.state.ctx
            await asyncio.to_thread(ctx.account.change_password, body.password, body.new_password)
            response = JSONResponse({"ok": True, "message": "رمز عوض شد؛ همهٔ نشست‌ها بسته شدند. دوباره وارد شو."})
            response.delete_cookie(COOKIE, path="/")
            return response

    @app.post("/api/account/logout-all")
    async def logout_all(request: Request):
        ctx = request.app.state.ctx
        ctx.store.logout_all()
        ctx.store.audit("auth.logout_all")
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.delete("/api/account/devices/{identifier}")
    async def delete_device(request: Request, identifier: str):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise PanelError("شناسهٔ نشست نامعتبر است.")
        with request.app.state.ctx.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (identifier,))
        return {"ok": True}

    @app.post("/api/account/2fa/setup")
    async def factor_setup(request: Request, body: Password):
        async with request.app.state.ctx.account_lock:
            await reauthenticate(request, body.password)
            return await asyncio.to_thread(request.app.state.ctx.account.begin_two_factor, body.password, request.state.session["id"])

    @app.post("/api/account/2fa/confirm")
    async def factor_confirm(request: Request, body: Code):
        async with request.app.state.ctx.account_lock:
            ctx = request.app.state.ctx
            ip = request.client.host if request.client else "unknown"
            if not ctx.limiter.check(ip):
                raise PanelError("تعداد تلاش‌ها زیاد است؛ بعداً دوباره امتحان کن.", 429)
            try:
                data = ctx.account.enable_two_factor(body.code, request.state.session["id"])
                ctx.limiter.success(ip)
                return data
            except PanelError:
                ctx.limiter.fail(ip)
                raise

    @app.post("/api/account/2fa/disable")
    async def factor_disable(request: Request, body: FactorDisable):
        async with request.app.state.ctx.account_lock:
            await reauthenticate(request, body.password)
            ctx = request.app.state.ctx
            try:
                await asyncio.to_thread(ctx.account.disable_two_factor, body.password, body.code, request.state.session["id"])
            except PanelError:
                ctx.limiter.fail(request.client.host if request.client else "unknown")
                raise
            return {"ok": True}

    @app.post("/api/account/keys")
    async def create_key(request: Request, body: Key):
        async with request.app.state.ctx.account_lock:
            await reauthenticate(request, body.password)
            return request.app.state.ctx.account.create_api_key(body.name, body.scopes, body.days)

    @app.delete("/api/account/keys/{identifier}")
    async def delete_key(request: Request, identifier: str):
        request.app.state.ctx.store.delete_api_key(identifier)
        request.app.state.ctx.store.audit("auth.api_key_deleted", identifier)
        return {"ok": True}

    @app.get("/api/startup")
    async def startup(request: Request):
        ctx = request.app.state.ctx
        return preview(settings, ctx.store, ctx.engines)

    @app.get("/api/files/search")
    async def search(request: Request, path: str = "", q: str = Query(min_length=1, max_length=100), recursive: bool = False):
        return await blocking(request.app.state.ctx.files.search, path, q, recursive)

    @app.post("/api/files/batch")
    async def batch(request: Request, body: FileBatch):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job(
            "عملیات گروهی فایل: " + body.action, lambda: ctx.files.batch(body.action, body.paths, body.destination), stopped=True
        )

    @app.get("/api/worlds")
    async def worlds(request: Request):
        return await blocking(request.app.state.ctx.worlds.list)

    @app.post("/api/worlds/create")
    async def world_create(request: Request, body: WorldName):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            result = ctx.worlds.create(body.name)
            ctx.store.audit("world.create", body.name)
            return result

    @app.post("/api/worlds/select")
    async def world_select(request: Request, body: WorldName):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            return ctx.worlds.select(body.name)

    @app.post("/api/worlds/export")
    async def world_export(request: Request, body: WorldName):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job("خروجی دنیای " + body.name, lambda: ctx.worlds.export(body.name))

    @app.delete("/api/worlds")
    async def world_delete(request: Request, body: WorldName):
        ctx = request.app.state.ctx
        return await ctx.manager.new_job("حذف دنیای " + body.name, lambda: ctx.worlds.delete(body.name), stopped=True)

    @app.post("/api/worlds/import")
    async def world_import(request: Request, name: str = Form(min_length=1, max_length=64), file: UploadFile = File(...)):
        ctx = request.app.state.ctx
        ctx.manager.check_available(stopped=True)
        temp = await receive_upload(settings, file)

        async def operation():
            try:
                return await ctx.worlds.import_zip(temp, name)
            finally:
                temp.unlink(missing_ok=True)

        try:
            return await ctx.manager.new_job("وارد کردن سیو دنیا", operation, stopped=True)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

    @app.get("/api/packs")
    async def packs(request: Request):
        return request.app.state.ctx.packs.list()

    @app.post("/api/packs/upload")
    async def pack_upload(request: Request, file: UploadFile = File(...)):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            name = file.filename or "pack.zip"
            temp = await receive_upload(settings, file)
            try:
                return await ctx.packs.upload(temp, name)
            finally:
                temp.unlink(missing_ok=True)

    @app.post("/api/packs/activate")
    async def pack_activate(request: Request, body: Pack):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            return ctx.packs.activate(body.id, body.base_url, body.required, body.prompt)

    @app.delete("/api/packs/{identifier}")
    async def pack_delete(request: Request, identifier: str):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            ctx.packs.delete(identifier)
        return {"ok": True}

    @app.get("/packs/{identifier}.zip")
    async def public_pack(request: Request, identifier: str):
        file = request.app.state.ctx.packs.path(identifier)
        return FileResponse(
            file, media_type="application/zip", filename="manix-resource-pack.zip", headers={"Cache-Control": "public, max-age=3600"}
        )

    @app.get("/api/schedules")
    async def schedules(request: Request):
        return {"tasks": request.app.state.ctx.schedules.list(), "now": time.time(), "missed_grace_seconds": 600}

    @app.post("/api/schedules")
    async def task_create(request: Request, body: Task):
        return request.app.state.ctx.schedules.save(body.model_dump())

    @app.put("/api/schedules/{identifier}")
    async def task_update(request: Request, identifier: str, body: Task):
        return request.app.state.ctx.schedules.save(body.model_dump(), identifier)

    @app.patch("/api/schedules/{identifier}")
    async def task_toggle(request: Request, identifier: str, body: Enabled):
        request.app.state.ctx.schedules.toggle(identifier, body.enabled)
        return {"ok": True}

    @app.delete("/api/schedules/{identifier}")
    async def task_delete(request: Request, identifier: str):
        request.app.state.ctx.schedules.delete(identifier)
        return {"ok": True}

    @app.get("/api/versions/installed")
    async def installed(request: Request):
        return {"engines": await blocking(request.app.state.ctx.runtime.list)}

    @app.delete("/api/versions/installed/{identifier}")
    async def engine_delete(request: Request, identifier: str):
        ctx = request.app.state.ctx
        async with ctx.manager.exclusive(stopped=True):
            return await blocking(ctx.runtime.delete, identifier)

    @app.post("/api/versions/custom")
    async def custom_jar(
        request: Request,
        kind: str = Form("spigot"),
        version: str = Form(...),
        java: int = Form(21),
        allow_downgrade: bool = Form(False),
        file: UploadFile = File(...),
    ):
        ctx = request.app.state.ctx
        ctx.manager.check_available(stopped=True)
        temp = await receive_upload(settings, file)

        async def operation():
            try:
                return await ctx.runtime.import_jar(temp, kind, version, java, allow_downgrade)
            finally:
                temp.unlink(missing_ok=True)

        try:
            return await ctx.manager.new_job("نصب JAR اجرایی مورداعتماد", operation, stopped=True)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
