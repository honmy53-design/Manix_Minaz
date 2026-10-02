import os
from dataclasses import dataclass
from pathlib import Path

from .errors import PanelError


def env_int(key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(key, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{key} must be an integer") from exc
    if not low <= value <= high:
        raise RuntimeError(f"{key} must be between {low} and {high}")
    return value


def memory_limit_mb() -> int | None:
    # cgroup v2 (Railway), then cgroup v1. Do not report the host's RAM as the quota.
    for file in ["/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"]:
        try:
            raw = Path(file).read_text().strip()
            if raw != "max" and 0 < int(raw) < 1 << 60:
                return int(raw) // (1024 * 1024)
        except (OSError, ValueError):
            pass
    return None


def safe_heap_mb() -> int | None:
    limit = memory_limit_mb()
    return max(0, (limit - max(384, limit // 4)) // 128 * 128) if limit else None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    username: str
    password: str
    port: int = 8080
    mc_port: int = 25565
    upload_mb: int = 512
    archive_mb: int = 8192
    session_hours: int = 24
    stop_timeout: int = 45
    railway: bool = False

    @classmethod
    def from_env(cls):
        password = os.getenv("PANEL_PASSWORD", "")
        if len(password) < 12 or password.lower() in {
            "change-me-long-password",
            "replace-with-a-strong-password",
            "your-strong-password-here",
        }:
            raise RuntimeError("Set PANEL_PASSWORD to your own strong password (at least 12 characters).")
        username = os.getenv("PANEL_USERNAME", "admin")
        if not username or len(username) > 64:
            raise RuntimeError("Invalid PANEL_USERNAME")
        root = Path(os.getenv("DATA_DIR", "/data")).expanduser().absolute()
        if str(root) in {"/", "/app", "/etc", "/usr"}:
            raise RuntimeError("DATA_DIR must be a dedicated data directory, e.g. /data")
        return cls(
            root,
            username,
            password,
            env_int("PORT", 8080, 1024, 65535),
            env_int("MC_PORT", 25565, 1024, 65535),
            env_int("MAX_UPLOAD_MB", 512, 1, 8192),
            env_int("MAX_ARCHIVE_MB", 8192, 64, 65536),
            env_int("SESSION_HOURS", 24, 1, 168),
            env_int("STOP_TIMEOUT", 45, 5, 120),
            bool(os.getenv("RAILWAY_PROJECT_ID")),
        )

    @property
    def server_dir(self):
        return self.data_dir / "server"

    @property
    def panel_dir(self):
        return self.data_dir / "panel"

    def prepare(self):
        for name in ["server", "panel", "engines", "backups", "exports", "tmp"]:
            path = self.data_dir / name
            if path.is_symlink():
                raise RuntimeError(f"Refusing symlink data directory: {path}")
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.port == self.mc_port:
            raise RuntimeError("PORT and MC_PORT must be different")
        mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
        if self.railway and (not mount or Path(mount).absolute() != self.data_dir):
            # Failing closed is better than silently losing a world on the next deploy.
            raise RuntimeError("Attach a Railway Volume at /data (or the exact DATA_DIR) before deploying.")

    def defaults(self):
        maximum = safe_heap_mb()
        default_memory = min(1024, maximum) if maximum and maximum >= 512 else 512
        return {
            "server_name": "سرور مانیکس",
            "game_port": self.mc_port,
            "jvm_args": [],
            "memory_mb": env_int("MC_MEMORY_MB", default_memory, 512, 65536),
            "java_override": 0,
            "eula_accepted": os.getenv("EULA_ACCEPTED", "false").lower() == "true",
            "autostart": True,
            "desired_running": False,
            "auto_restart": False,
            "backup_hours": 0,
            "restart_hours": 0,
            "backup_keep": 7,
            "last_auto_backup": 0,
            "game_domain": "",
            "panel_domain": "",
            "proxy_host": os.getenv("RAILWAY_TCP_PROXY_DOMAIN", ""),
            "proxy_port": int(os.getenv("RAILWAY_TCP_PROXY_PORT", "0") or "0"),
            "engine": None,
        }

    def java(self, major: int) -> str:
        if major <= 8:
            major = 8
        elif major <= 17:
            major = 17
        elif major <= 21:
            major = 21
        elif major <= 25:
            major = 25
        else:
            raise PanelError(f"این نسخه Java {major} می‌خواهد؛ تصویر فعلی تا Java 25 دارد.")
        # Environment overrides are operator-controlled, never accepted from the browser.
        override = os.getenv(f"JAVA_{major}_BIN")
        target = Path(override or f"/opt/java/{major}/bin/java")
        if not target.is_file():
            raise PanelError(f"Java {major} پیدا نشد. روی Railway از Dockerfile همین پروژه استفاده کن.")
        return str(target)
