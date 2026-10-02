"""مانیکس / Manix: single-owner account protection, TOTP and scoped API keys."""

import base64
import json
import hashlib
import hmac
import os
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from .errors import PanelError
from .storage import password_hash, verify_password

API_SCOPES = {
    "status",
    "console.read",
    "console.write",
    "power",
    "files.read",
    "files.write",
    "backups.read",
    "backups.write",
    "players.read",
    "players.write",
    "settings.read",
    "settings.write",
}


def totp(secret, counter):
    key = base64.b32decode(secret + "=" * ((-len(secret)) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1000000:06d}"


def totp_counter(secret, code, now=None):
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    counter = int((time.time() if now is None else now) // 30)
    for delta in (0, -1, 1):
        if counter + delta >= 0 and hmac.compare_digest(totp(secret, counter + delta), code):
            return counter + delta
    return None


def recovery_digest(code):
    cleaned = re.sub(r"[ -]", "", code).upper()
    return hashlib.sha256(cleaned.encode()).hexdigest()


class AccountService:
    def __init__(self, store):
        self.store = store

    def reauthenticate(self, password):
        if not verify_password(password, self.store.get("password_hash", "")):
            raise PanelError("رمز فعلی درست نیست.", 403)

    def verify_second_factor(self, code):
        # A single SQLite transaction prevents concurrent reuse of the same code.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM kv WHERE key='two_factor'").fetchone()
            state = json.loads(row[0]) if row else {}
            if not state.get("secret"):
                return True
            counter = totp_counter(state["secret"], code)
            valid = counter is not None and counter > state.get("last_counter", -1)
            if valid:
                state["last_counter"] = counter
            else:
                digest = recovery_digest(code)
                recovery = state.get("recovery", [])
                matching = next((value for value in recovery if hmac.compare_digest(value, digest)), None)
                if not matching:
                    return False
                state["recovery"] = [value for value in recovery if value != matching]
            db.execute("UPDATE kv SET value=? WHERE key='two_factor'", (json.dumps(state),))
            return True

    def profile(self):
        factor = self.store.get("two_factor", {})
        return {
            "username": self.store.get("username"),
            "display_name": self.store.get("display_name", "مدیر مانیکس"),
            "email": self.store.get("contact_email", ""),
            "two_factor": bool(factor.get("secret")),
            "recovery_remaining": len(factor.get("recovery", [])),
            "login_history": self.store.audit_rows("auth.", 30),
        }

    def change_password(self, current, new):
        self.reauthenticate(current)
        if not 12 <= len(new) <= 256:
            raise PanelError("رمز جدید باید بین ۱۲ و ۲۵۶ کاراکتر باشد.")
        encoded = password_hash(new)
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES('password_hash',?)", (json.dumps(encoded),))
            db.execute("INSERT OR REPLACE INTO kv VALUES('two_factor_pending','{}')")
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM api_keys")
        self.store.audit("auth.password_changed", "All sessions and API keys revoked")

    def begin_two_factor(self, password, session_id):
        self.reauthenticate(password)
        if self.store.get("two_factor", {}).get("secret"):
            raise PanelError("۲FA از قبل فعال است؛ ابتدا آن را با رمز و کد معتبر غیرفعال کن.", 409)
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        self.store.put("two_factor_pending", {"secret": secret, "expires": time.time() + 600, "session": session_id})
        label = quote("مانیکس:" + self.store.get("username", "admin"), safe="")
        uri = f"otpauth://totp/{label}?" + urlencode({"secret": secret, "issuer": "مانیکس", "algorithm": "SHA1", "digits": 6, "period": 30})
        return {"secret": secret, "uri": uri, "expires_in": 600}

    def enable_two_factor(self, code, session_id):
        pending = self.store.get("two_factor_pending", {})
        if pending.get("expires", 0) < time.time() or pending.get("session") != session_id:
            raise PanelError("درخواست فعال‌سازی منقضی یا مربوط به نشست دیگری است؛ دوباره شروع کن.")
        counter = totp_counter(pending["secret"], code)
        if counter is None:
            raise PanelError("کد تأیید درست نیست. ساعت گوشی و سرویس باید هماهنگ باشند.")
        values = [secrets.token_hex(10).upper() for _ in range(8)]
        recovery = ["-".join(value[i : i + 5] for i in range(0, 20, 5)) for value in values]
        self.store.put(
            "two_factor", {"secret": pending["secret"], "last_counter": counter, "recovery": [recovery_digest(c) for c in recovery]}
        )
        self.store.put("two_factor_pending", {})
        self.store.logout_all(except_id=session_id)
        self.store.audit("auth.2fa_enabled", "Keep recovery codes offline")
        return {"recovery_codes": recovery}

    def disable_two_factor(self, password, code, session_id):
        self.reauthenticate(password)
        if not self.verify_second_factor(code):
            raise PanelError("کد ۲FA یا کد بازیابی نامعتبر/استفاده‌شده است.", 403)
        self.store.put("two_factor", {})
        self.store.put("two_factor_pending", {})
        self.store.logout_all(except_id=session_id)
        self.store.audit("auth.2fa_disabled", "")

    def reset_from_environment(self):
        if os.getenv("MANIX_RESET_2FA", "false").lower() == "true":
            self.store.put("two_factor", {})
            self.store.put("two_factor_pending", {})
            self.store.logout_all()
            self.store.audit("auth.2fa_env_reset", "Remove MANIX_RESET_2FA after recovery")

    def create_api_key(self, name, scopes, days):
        if not scopes or not set(scopes) <= API_SCOPES:
            raise PanelError("حداقل یک دسترسی معتبر برای API Key انتخاب کن.")
        token = "manix_" + secrets.token_urlsafe(36)
        identifier = secrets.token_hex(12)
        self.store.add_api_key(identifier, hashlib.sha256(token.encode()).hexdigest(), name, sorted(set(scopes)), days)
        self.store.audit("auth.api_key_created", name)
        return {"id": identifier, "token": token, "name": name}
