import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .errors import PanelError


def normalize(relative: str) -> str:
    if len(relative) > 2048 or "\\" in relative or "\x00" in relative:
        raise PanelError("مسیر فایل نامعتبر است.")
    if not relative or relative == ".":
        return ""
    if relative.startswith("/") or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise PanelError("مسیر باید نسبی باشد و نباید .. داشته باشد.")
    if ":" in relative or any(ord(c) < 32 for c in relative):
        raise PanelError("مسیر فایل نامعتبر است.")
    return str(PurePosixPath(relative))


def safe_path(root: Path, relative: str, *, allow_root=True) -> Path:
    rel = normalize(relative)
    if not rel and not allow_root:
        raise PanelError("این عملیات روی پوشهٔ اصلی مجاز نیست.")
    target = root / rel
    # Reject symlinks even when they point inside the permitted tree.
    cur = root
    if cur.is_symlink():
        raise PanelError("دسترسی به لینک نمادین مجاز نیست.")
    for component in PurePosixPath(rel).parts:
        cur /= component
        if cur.is_symlink():
            raise PanelError("دسترسی به لینک نمادین مجاز نیست.")
    if not target.resolve().is_relative_to(root.resolve()):
        raise PanelError("دسترسی خارج از پوشهٔ سرور مجاز نیست.")
    return target


def atomic_write(path: Path, content: bytes):
    temporary = path.with_name(f".{path.name}.{os.urandom(5).hex()}.part")
    try:
        with temporary.open("xb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json_file(root: Path, name: str, default):
    try:
        file = safe_path(root, name)
        if file.stat().st_size > 2 * 1024 * 1024:
            return default
        return json.loads(file.read_text("utf-8"))
    except (OSError, ValueError, PanelError):
        return default


def tree_files(root: Path):
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
        for name in sorted(files):
            file = Path(current) / name
            if file.is_file() and not file.is_symlink():
                yield file


def validate_zip(archive: Path, max_bytes: int):
    try:
        with zipfile.ZipFile(archive) as zipf:
            entries = zipf.infolist()
            if len(entries) > 50000:
                raise PanelError("تعداد فایل‌های ZIP بیش از حد مجاز است.")
            total, names = 0, set()
            for entry in entries:
                name = normalize(entry.filename.rstrip("/"))
                if not name or name in names:
                    raise PanelError("ZIP دارای نام خالی یا مسیر تکراری است.")
                names.add(name)
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise PanelError("ZIP رمزدار یا دارای symlink پشتیبانی نمی‌شود.")
                mode = entry.external_attr >> 16
                if mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise PanelError("ZIP فقط می‌تواند فایل و پوشهٔ معمولی داشته باشد.")
                total += entry.file_size
                if total > max_bytes:
                    raise PanelError("حجم بازشدهٔ ZIP از سقف مجاز بیشتر است.", 413)
            return total
    except (zipfile.BadZipFile, OSError) as exc:
        raise PanelError("فایل ZIP سالم نیست.") from exc


def extract_zip(archive: Path, dest: Path, max_bytes: int):
    total = validate_zip(archive, max_bytes)
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(dest).free < total + 128 * 1024 * 1024:
        raise PanelError("فضای کافی برای باز کردن ZIP وجود ندارد.")
    with zipfile.ZipFile(archive) as zipf:
        for info in zipf.infolist():
            target = safe_path(dest, info.filename.rstrip("/"), allow_root=False)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Count actual bytes as well as the untrusted central-directory sizes.
                count = 0
                with zipf.open(info) as src, target.open("xb") as out:
                    while chunk := src.read(1024 * 1024):
                        count += len(chunk)
                        if count > info.file_size or count > max_bytes:
                            raise PanelError("حجم واقعی ZIP نامعتبر است.")
                        out.write(chunk)
    return total


def java_unescape(value: str) -> str:
    def replace(match):
        part = match.group(1)
        if part.startswith("u"):
            return chr(int(part[1:], 16))
        return {"n": "\n", "r": "\r", "t": "\t"}.get(part, part)

    result = re.sub(r"\\(u[0-9a-fA-F]{4}|.)", replace, value)
    try:
        result = result.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        pass
    return result


def properties_read(root: Path):
    try:
        file = safe_path(root, "server.properties")
        if file.stat().st_size > 1024 * 1024:
            raise PanelError("server.properties بیش از حد بزرگ است.")
        text = file.read_text("utf-8", errors="replace")
    except FileNotFoundError:
        return {}
    result = {}
    # Handle standard Java property continuations, comments and escaped separators.
    lines, pending = [], ""
    for line in text.splitlines():
        combined = pending + (line.lstrip() if pending else line)
        if (len(combined) - len(combined.rstrip("\\"))) % 2:
            pending = combined[:-1]
        else:
            lines.append(combined)
            pending = ""
    if pending:
        lines.append(pending)
    for line in lines:
        line = line.lstrip()
        if not line or line[0] in "#!":
            continue
        split = re.search(r"(?<!\\)[=:]|(?<!\\)\s", line)
        if split:
            key = line[: split.start()]
            value = line[split.end() :].lstrip()
            if value.startswith(("=", ":")):
                value = value[1:].lstrip()
        else:
            key, value = line, ""
        result[java_unescape(key)] = java_unescape(value)
    return result


def java_escape(value: str, is_key=False):
    result = []
    for index, c in enumerate(value):
        if c in "\\\n\r\t":
            result.append({"\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}[c])
        elif c in "=:#!" or c == " " and (is_key or index == 0):
            result.append("\\" + c)
        elif ord(c) > 126 or ord(c) < 32:
            raw = c.encode("utf-16-be")
            result.extend("\\u" + raw[i : i + 2].hex() for i in range(0, len(raw), 2))
        else:
            result.append(c)
    return "".join(result)


DEFAULT_PROPERTIES = {
    "motd": "Welcome to Manix | مانیکس",
    "gamemode": "survival",
    "difficulty": "normal",
    "max-players": "20",
    "view-distance": "8",
    "simulation-distance": "6",
    "online-mode": "true",
    "white-list": "false",
    "enforce-whitelist": "false",
    "pvp": "true",
    "allow-flight": "false",
    "spawn-protection": "16",
    "level-name": "world",
    "hardcore": "false",
    "allow-nether": "true",
}


def properties_write(root: Path, values: dict):
    file = safe_path(root, "server.properties")
    text = (
        "# Managed by Manix; advanced keys are preserved.\n"
        + "\n".join(f"{java_escape(str(k), True)}={java_escape(str(v))}" for k, v in sorted(values.items()))
        + "\n"
    )
    atomic_write(file, text.encode("ascii"))


def ensure_properties(root: Path, port: int):
    values = DEFAULT_PROPERTIES | properties_read(root)
    normalize(values.get("level-name", "world"))
    if not values.get("level-name"):
        raise PanelError("نام پوشهٔ دنیا نباید خالی باشد.")
    values.update({"server-ip": "", "server-port": str(port), "enable-rcon": "false", "enable-query": "false"})
    properties_write(root, values)
    return values
