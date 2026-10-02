"""مانیکس / Manix project module."""

import hmac
import time
from collections import defaultdict
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

COOKIE = "manix_session"


class LoginLimiter:
    def __init__(self):
        self.attempts = defaultdict(list)

    def check(self, ip):
        now = time.monotonic()
        self.attempts[ip] = [t for t in self.attempts[ip] if now - t < 900]
        return len(self.attempts[ip]) < 5

    def fail(self, ip):
        if len(self.attempts) > 5000:
            self.attempts.clear()
        self.attempts[ip].append(time.monotonic())

    def success(self, ip):
        self.attempts.pop(ip, None)


def key_scope(path, method):
    read = method in {"GET", "HEAD"}
    if path == "/api/status":
        return "status"
    if path.startswith("/api/console"):
        return "console.read" if read else "console.write"
    if path == "/api/power":
        return "power"
    if path.startswith(("/api/files", "/api/worlds")):
        return "files.read" if read else "files.write"
    if path == "/api/world/export":
        return "backups.write"
    if path.startswith(("/api/backups", "/api/exports")):
        return "backups.read" if read else "backups.write"
    if path.startswith("/api/players"):
        return "players.read" if read else "players.write"
    if path in {"/api/settings", "/api/properties", "/api/startup"}:
        return "settings.read" if read else "settings.write"
    return None  # Account, 2FA, API-key management and scheduling are session-only.


class SecurityMiddleware:
    def __init__(self, app, settings, context):
        self.app, self.settings, self.context = app, settings, context

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        api = request.url.path.startswith("/api/")
        mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}

        async def send_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"same-origin"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'",
                        ),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (b"cache-control", b"no-store" if api else b"no-cache"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        if api:
            origin = request.headers.get("origin")
            if origin:
                source = urlsplit(origin)
                if source.netloc.lower() != request.headers.get("host", "").lower() or source.scheme != request.url.scheme:
                    await JSONResponse({"detail": "درخواست از دامنهٔ دیگری مجاز نیست."}, 403)(scope, receive, send_headers)
                    return
        if api and request.url.path != "/api/login":
            ctx = self.context()
            authorization = request.headers.get("authorization", "")
            if authorization:
                key = ctx.store.api_key(authorization[7:]) if ctx and authorization.startswith("Bearer ") else None
                needed = key_scope(request.url.path, request.method)
                if not key:
                    await JSONResponse({"detail": "API Key نامعتبر یا منقضی است."}, 401)(scope, receive, send_headers)
                    return
                if needed is None or needed not in key["scopes"]:
                    await JSONResponse({"detail": "این API Key دسترسی لازم را ندارد."}, 403)(scope, receive, send_headers)
                    return
                scope.setdefault("state", {})["api_key"] = key
            else:
                session = ctx.store.session(request.cookies.get(COOKIE)) if ctx else None
                if not session:
                    await JSONResponse({"detail": "ابتدا وارد پنل شو."}, 401)(scope, receive, send_headers)
                    return
                scope.setdefault("state", {})["session"] = session
                if mutation and not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), session["csrf"].encode()):
                    await JSONResponse({"detail": "توکن امنیتی نامعتبر است؛ صفحه را تازه کن."}, 403)(scope, receive, send_headers)
                    return
        uploads = {"/api/files/upload", "/api/backups/import", "/api/worlds/import", "/api/packs/upload", "/api/versions/custom"}
        limit = (
            self.settings.upload_mb * 1024 * 1024 + 131072
            if request.url.path in uploads
            else 8192
            if request.url.path == "/api/login"
            else 2 * 1024 * 1024
        )
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            await JSONResponse({"detail": "حجم درخواست از سقف آپلود بیشتر است."}, 413)(scope, receive, send_headers)
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, "حجم درخواست از سقف آپلود بیشتر است.")
            return message

        await self.app(scope, limited_receive, send_headers)
