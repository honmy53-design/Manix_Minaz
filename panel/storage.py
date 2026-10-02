"""مانیکس / Manix project module."""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, expected = encoded.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


class Store:
    def __init__(self, directory: Path, username: str, password: str, defaults: dict):
        self.path = directory / "panel.sqlite3"
        if self.path.is_symlink():
            raise RuntimeError("Refusing symlink Manix database")
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, action TEXT, detail TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, token TEXT UNIQUE NOT NULL, name TEXT NOT NULL, scopes TEXT NOT NULL, created REAL, expires REAL, last_used REAL);
            """)
        with self.connect() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
            for key, kind in [("created", "REAL"), ("ip", "TEXT"), ("agent", "TEXT")]:
                if key not in columns:
                    db.execute(f"ALTER TABLE sessions ADD COLUMN {key} {kind}")
        # Environment is the bootstrap/recovery credential. A UI password change
        # persists until the OPERATOR actually changes the environment password.
        baseline = self.get("bootstrap_password_hash", self.get("password_hash", ""))
        changed = self.get("username") != username or not verify_password(password, baseline)
        if changed:
            self.put("username", username)
            self.put("password_hash", password_hash(password))
            self.logout_all()
            with self.connect() as db:
                db.execute("DELETE FROM api_keys")
        if changed or not self.get("bootstrap_password_hash"):
            self.put("bootstrap_password_hash", password_hash(password))
        saved = self.get("config", {})
        self.config = defaults | saved
        self.save_config()
        # Jobs are not silently retried after a container restart.
        for job in self.jobs():
            if job["state"] in {"queued", "running"}:
                job.update(state="failed", message="عملیات با ری‌دیپلوی/خاموش شدن سرویس قطع شد.", finished=time.time())
                self.save_job(job)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=15000")
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save_config(self):
        self.put("config", self.config)

    def session(self, token):
        if not token or len(token) > 128:
            return None
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT csrf,expires FROM sessions WHERE token=?", (hashed,)).fetchone()
        return {"csrf": row[0], "id": hashed} if row and row[1] > time.time() else None

    def new_session(self, hours, ip="", agent=""):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute(
                "INSERT INTO sessions(token,csrf,expires,created,ip,agent) VALUES(?,?,?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + hours * 3600, time.time(), ip[:128], agent[:300]),
            )
        return token, csrf

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256((token or "").encode()).hexdigest(),))

    def audit(self, action, detail=""):
        with self.connect() as db:
            db.execute("INSERT INTO audit(time,action,detail) VALUES(?,?,?)", (time.time(), action, str(detail)[:2000]))
            db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 5000)")

    def audit_rows(self, prefix=None, limit=100):
        with self.connect() as db:
            if prefix:
                rows = db.execute(
                    "SELECT time,action,detail FROM audit WHERE action LIKE ? ORDER BY id DESC LIMIT ?", (prefix + "%", limit)
                ).fetchall()
            else:
                rows = db.execute("SELECT time,action,detail FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(time=r[0], action=r[1], detail=r[2]) for r in rows]

    def save_job(self, job):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (job["id"], json.dumps(job, ensure_ascii=False)))
            db.execute("DELETE FROM jobs WHERE id NOT IN (SELECT id FROM jobs ORDER BY json_extract(data,'$.created') DESC LIMIT 30)")

    def jobs(self):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM jobs ORDER BY json_extract(data,'$.created') DESC LIMIT 30").fetchall()
        return [json.loads(r[0]) for r in rows]

    def logout_all(self, except_id=None):
        with self.connect() as db:
            if except_id:
                db.execute("DELETE FROM sessions WHERE token != ?", (except_id,))
            else:
                db.execute("DELETE FROM sessions")

    def devices(self, current_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT token,created,expires,ip,agent FROM sessions WHERE expires > ? ORDER BY created DESC", (time.time(),)
            ).fetchall()
        return [{"id": r[0], "created": r[1], "expires": r[2], "ip": r[3], "agent": r[4], "current": r[0] == current_id} for r in rows]

    def add_api_key(self, identifier, token_hash, name, scopes, days):
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
            if count >= 20:
                from .errors import PanelError

                raise PanelError("حداکثر ۲۰ API Key مجاز است؛ کلید قدیمی را حذف کن.")
            db.execute(
                "INSERT INTO api_keys VALUES(?,?,?,?,?,?,?)",
                (identifier, token_hash, name, json.dumps(scopes), time.time(), time.time() + days * 86400, 0),
            )

    def api_key(self, token):
        if not token.startswith("manix_") or len(token) > 150:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT id,name,scopes,expires,last_used FROM api_keys WHERE token=?", (digest,)).fetchone()
            if not row or row[3] < time.time():
                return None
            if time.time() - row[4] > 30:
                db.execute("UPDATE api_keys SET last_used=? WHERE id=?", (time.time(), row[0]))
        return {"id": row[0], "name": row[1], "scopes": json.loads(row[2])}

    def api_keys(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,name,scopes,created,expires,last_used FROM api_keys ORDER BY created DESC").fetchall()
        return [{"id": r[0], "name": r[1], "scopes": json.loads(r[2]), "created": r[3], "expires": r[4], "last_used": r[5]} for r in rows]

    def delete_api_key(self, identifier):
        with self.connect() as db:
            db.execute("DELETE FROM api_keys WHERE id=?", (identifier,))
