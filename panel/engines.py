"""مانیکس / Manix project module."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from .config import memory_limit_mb
from .errors import PanelError
from .paths import atomic_write, safe_path

KINDS = {"vanilla", "paper", "purpur", "fabric", "forge", "neoforge"}
HOSTS = {
    "piston-meta.mojang.com",
    "piston-data.mojang.com",
    "launcher.mojang.com",
    "launchermeta.mojang.com",
    "meta.fabricmc.net",
    "maven.fabricmc.net",
    "fill.papermc.io",
    "fill-data.papermc.io",
    "api.papermc.io",
    "api.purpurmc.org",
    "maven.minecraftforge.net",
    "files.minecraftforge.net",
    "maven.neoforged.net",
    "api.modrinth.com",
    "cdn.modrinth.com",
    "libraries.minecraft.net",
}
MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
NEO_METADATA = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
USER_AGENT = "Manix/1.1.0 (self-hosted Minecraft administration; operator-configured downloads)"


def checked_url(url: str):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise PanelError("مقصد دانلود خارج از فهرست منابع مجاز است.")
    return url


def valid_id(value: str):
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,80}", value):
        raise PanelError("شناسه یا نسخه نامعتبر است.")
    return value


def supported_release(version: str):
    try:
        parts = [int(p) for p in version.split(".")]
        return parts[0] > 1 or parts[0] == 1 and len(parts) > 1 and parts[1] >= 8
    except ValueError:
        return False


def neo_prefix(mc: str):
    parts = mc.split(".")
    if parts[0] == "1":
        return f"{parts[1]}.{parts[2] if len(parts) > 2 else '0'}."
    return mc + (".0." if len(parts) == 2 else ".")


class Downloads:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=20),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=8),
        )
        self.cache = {}

    async def close(self):
        await self.client.aclose()

    async def fetch(self, url: str, target: Path | None = None, *, maximum=12 * 1024 * 1024, checksum=None):
        checked_url(url)
        temporary = target.with_suffix(target.suffix + ".part") if target else None
        try:
            for _ in range(6):
                async with self.client.stream("GET", checked_url(url)) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code != 200:
                        raise PanelError(
                            f"منبع دانلود ({urlsplit(url).hostname}) خطای HTTP {response.status_code} داد. بعداً دوباره امتحان کن.", 502
                        )
                    declared = int(response.headers.get("content-length", "0") or "0")
                    if declared > maximum:
                        raise PanelError("حجم دانلود از سقف مجاز بیشتر است.", 413)
                    algo, expected = checksum if checksum else ("sha256", None)
                    hasher = hashlib.new(algo)
                    length, chunks = 0, []
                    out = temporary.open("xb") if temporary else None
                    try:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            length += len(chunk)
                            if length > maximum:
                                raise PanelError("حجم دانلود از سقف مجاز بیشتر است.", 413)
                            hasher.update(chunk)
                            if out:
                                out.write(chunk)
                            else:
                                chunks.append(chunk)
                    finally:
                        if out:
                            out.close()
                    if expected and hasher.hexdigest().lower() != expected.lower():
                        raise PanelError("هش فایل دانلودشده با منبع رسمی مطابقت ندارد؛ نصب انجام نشد.", 502)
                    if target:
                        os.replace(temporary, target)
                        return {"size": length, "sha256": hasher.hexdigest() if algo == "sha256" else None}
                    return b"".join(chunks)
            raise PanelError("تعداد redirect دانلود بیش از حد مجاز است.", 502)
        except (httpx.HTTPError, ValueError) as exc:
            raise PanelError("ارتباط با منبع دانلود برقرار نشد. اینترنت سرویس و دسترسی منبع را بررسی کن.", 502) from exc
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    async def data(self, url: str, ttl=300):
        cached = self.cache.get(url)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
        try:
            result = json.loads(await self.fetch(url))
        except (ValueError, TypeError) as exc:
            raise PanelError("پاسخ منبع دانلود JSON معتبر نیست.", 502) from exc
        if len(self.cache) > 300:
            self.cache.clear()
        self.cache[url] = (time.monotonic(), result)
        return result

    async def jar(self, url, target, checksum=None):
        await self.fetch(url, target, maximum=512 * 1024 * 1024, checksum=checksum)
        if not zipfile.is_zipfile(target):
            target.unlink(missing_ok=True)
            raise PanelError("منبع دانلود JAR معتبری برنگرداند.", 502)


class EngineService:
    def __init__(self, settings, downloads, log):
        self.settings, self.http, self.log = settings, downloads, log

    async def releases(self):
        data = await self.http.data(MANIFEST)
        return [v for v in data["versions"] if v["type"] == "release" and supported_release(v["id"])]

    async def version_meta(self, version):
        valid_id(version)
        entry = next((v for v in await self.releases() if v["id"] == version), None)
        if not entry:
            raise PanelError("این نسخهٔ پایدار در فهرست رسمی Minecraft وجود ندارد.")
        meta = await self.http.data(entry["url"])
        if "server" not in meta.get("downloads", {}):
            raise PanelError("برای این نسخه فایل سرور رسمی موجود نیست.")
        return meta

    async def neo_versions(self):
        cached = self.http.cache.get(NEO_METADATA)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        try:
            tree = ET.fromstring(await self.http.fetch(NEO_METADATA))
            versions = [x.text for x in tree.findall("./versioning/versions/version") if x.text and "-" not in x.text]
        except ET.ParseError as exc:
            raise PanelError("فهرست NeoForge قابل خواندن نیست.", 502) from exc
        self.http.cache[NEO_METADATA] = (time.monotonic(), versions)
        return versions

    async def versions(self, kind: str):
        if kind not in KINDS:
            raise PanelError("نوع سرور پشتیبانی نمی‌شود.")
        releases = await self.releases()
        if kind == "vanilla":
            allowed = {r["id"] for r in releases}
        elif kind == "paper":
            obj = await self.http.data("https://fill.papermc.io/v3/projects/paper")
            allowed = {v for group in obj["versions"].values() for v in group}
        elif kind == "purpur":
            obj = await self.http.data("https://api.purpurmc.org/v2/purpur")
            allowed = set(obj["versions"])
        elif kind == "fabric":
            obj = await self.http.data("https://meta.fabricmc.net/v2/versions/game")
            allowed = {v["version"] for v in obj if v.get("stable")}
        elif kind == "forge":
            obj = await self.http.data(FORGE_PROMOS)
            allowed = {key.rsplit("-", 1)[0] for key in obj["promos"]}
        else:
            builds = await self.neo_versions()
            allowed = {r["id"] for r in releases if any(v.startswith(neo_prefix(r["id"])) for v in builds)}
        return [{"id": r["id"], "released": r["releaseTime"]} for r in releases if r["id"] in allowed]

    async def install(self, kind: str, version: str, override=0):
        if version not in {r["id"] for r in await self.versions(kind)}:
            raise PanelError("نسخهٔ انتخاب‌شده برای این نوع سرور در دسترس نیست.")
        meta = await self.version_meta(version)
        required = int(meta.get("javaVersion", {}).get("majorVersion", 8))
        if kind == "paper":
            paper_meta = await self.http.data(f"https://fill.papermc.io/v3/projects/paper/versions/{version}")
            required = max(required, int(paper_meta.get("version", {}).get("java", {}).get("version", {}).get("minimum", required)))
        actual = override or (8 if required <= 8 else 17 if required <= 17 else 21 if required <= 21 else 25)
        if actual < required:
            raise PanelError(f"این نسخه حداقل Java {required} می‌خواهد.")
        java = self.settings.java(actual)
        base = self.settings.data_dir / "engines" / uuid.uuid4().hex
        base.mkdir()
        engine = {
            "id": base.name,
            "kind": kind,
            "version": version,
            "required_java": required,
            "java": actual,
            "build": "",
            "mode": "jar",
            "entry": "server.jar",
            "installed": time.time(),
        }
        self.log(f"نصب {kind} / Minecraft {version} با Java {actual} آغاز شد.", "panel")
        try:
            checksum = None
            if kind == "vanilla":
                item = meta["downloads"]["server"]
                url, checksum = item["url"], ("sha1", item["sha1"])
                engine["build"] = version
            elif kind == "paper":
                builds = await self.http.data(f"https://fill.papermc.io/v3/projects/paper/versions/{version}/builds")
                stable = [b for b in builds if b["channel"] == "STABLE"]
                if not stable:
                    raise PanelError("برای این نسخه هنوز بیلد پایدار Paper منتشر نشده است. نسخهٔ دیگری انتخاب کن.")
                build = max(stable, key=lambda b: b["id"])
                item = build["downloads"]["server:default"]
                url, checksum = item["url"], ("sha256", item["checksums"]["sha256"])
                engine["build"] = str(build["id"])
            elif kind == "purpur":
                item = await self.http.data(f"https://api.purpurmc.org/v2/purpur/{version}/latest")
                engine["build"] = str(item["build"])
                url = f"https://api.purpurmc.org/v2/purpur/{version}/{item['build']}/download"
                checksum = ("md5", item["md5"]) if item.get("md5") else None
            elif kind == "fabric":
                loaders = await self.http.data(f"https://meta.fabricmc.net/v2/versions/loader/{version}")
                installers = await self.http.data("https://meta.fabricmc.net/v2/versions/installer")
                loader = next((x["loader"]["version"] for x in loaders if x["loader"].get("stable")), None)
                installer = next((x["version"] for x in installers if x.get("stable")), None)
                if not loader or not installer:
                    raise PanelError("لودر/نصاب پایدار Fabric موجود نیست.")
                url = f"https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/{installer}/server/jar"
                engine["build"] = loader
            else:
                await self.install_forge_family(kind, version, base, engine, java)
                atomic_write(base / "engine.json", json.dumps(engine).encode())
                return engine
            self.log("دانلود فایل سرور و بررسی سلامت آن…", "panel")
            await self.http.jar(url, base / "server.jar", checksum)
            atomic_write(base / "engine.json", json.dumps(engine).encode())
            return engine
        except BaseException:
            shutil.rmtree(base, ignore_errors=True)
            raise

    async def install_forge_family(self, kind, version, base, engine, java):
        if kind == "forge":
            promos = (await self.http.data(FORGE_PROMOS))["promos"]
            build = promos.get(version + "-recommended") or promos.get(version + "-latest")
            if not build:
                raise PanelError("بیلد Forge برای این نسخه موجود نیست.")
            artifact = f"{version}-{build}"
            # Some legacy releases append a branch suffix, e.g. 1.8.9-...-1.8.9.
            if version.startswith("1.") and int(version.split(".")[1]) < 12:
                metadata_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
                try:
                    tree = ET.fromstring(await self.http.fetch(metadata_url))
                    entries = [x.text for x in tree.findall("./versioning/versions/version") if x.text]
                except ET.ParseError as exc:
                    raise PanelError("فهرست Maven Forge قابل خواندن نیست.", 502) from exc
                if artifact not in entries:
                    artifact = next((v for v in reversed(entries) if v.startswith(artifact + "-")), artifact)
            url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{artifact}/forge-{artifact}-installer.jar"
        else:
            candidates = [b for b in await self.neo_versions() if b.startswith(neo_prefix(version))]
            if not candidates:
                raise PanelError("بیلد پایدار NeoForge برای این نسخه موجود نیست.")
            build = max(candidates, key=lambda s: tuple(int(x) for x in s.split(".")))
            artifact = build
            url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{build}/neoforge-{build}-installer.jar"
        engine["build"] = build
        sha = (await self.http.fetch(url + ".sha1", maximum=4096)).decode().strip().split()[0]
        if not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
            raise PanelError("هش نصاب Forge/NeoForge معتبر نیست.", 502)
        installer = base / "installer.jar"
        await self.http.jar(url, installer, ("sha1", sha))
        self.log("اجرای نصاب رسمی؛ دانلود کتابخانه‌ها ممکن است چند دقیقه طول بکشد.", "panel")
        limit = memory_limit_mb()
        heap = min(768, max(384, (limit or 2048) - 384))
        process = await asyncio.create_subprocess_exec(
            java,
            f"-Xmx{heap}M",
            "-Djava.awt.headless=true",
            "-jar",
            str(installer),
            "--installServer",
            cwd=base,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            limit=256 * 1024,
        )

        async def output():
            while line := await process.stdout.readline():
                self.log(line.decode("utf-8", errors="replace").rstrip()[:32000], "installer")
            return await process.wait()

        try:
            code = await asyncio.wait_for(output(), timeout=900)
            if code:
                raise PanelError(f"نصاب با کد {code} بسته شد. جزئیات در کنسول است.", 502)
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                except ProcessLookupError:
                    pass
        args = (
            list(base.glob("libraries/net/minecraftforge/forge/*/unix_args.txt"))
            if kind == "forge"
            else list(base.glob("libraries/net/neoforged/neoforge/*/unix_args.txt"))
        )
        if args:
            text = args[0].read_text("utf-8")
            text = text.replace("libraries/", str(base / "libraries") + "/")
            text = re.sub(r"(-DlibraryDirectory=)libraries\b", lambda m: m[1] + str(base / "libraries"), text)
            atomic_write(base / "launch.args", text.encode())
            engine.update(mode="args", entry="launch.args")
        else:
            candidates = [f for f in base.glob("forge-*.jar") if "installer" not in f.name]
            main = None
            for candidate in candidates:
                try:
                    with zipfile.ZipFile(candidate) as jar:
                        if b"Main-Class:" in jar.read("META-INF/MANIFEST.MF"):
                            main = candidate
                            break
                except (KeyError, zipfile.BadZipFile):
                    pass
            if not main:
                raise PanelError("نصاب تمام شد ولی فایل اجرای سرور پیدا نشد. این بیلد پشتیبانی نمی‌شود.", 502)
            engine["entry"] = main.name
        installer.unlink(missing_ok=True)

    def launch(self, engine, override=0):
        if not re.fullmatch(r"[a-f0-9]{32}", engine["id"]):
            raise PanelError("شناسهٔ موتور ذخیره‌شده نامعتبر است.")
        actual = override or engine["java"]
        if actual < engine["required_java"]:
            raise PanelError(f"این نسخه حداقل Java {engine['required_java']} می‌خواهد.")
        java = self.settings.java(actual)
        base = safe_path(self.settings.data_dir / "engines", engine["id"])
        entry = safe_path(base, engine["entry"], allow_root=False)
        if not entry.is_file():
            raise PanelError("فایل اجرای سرور موجود نیست. نسخه را دوباره نصب کن.")
        if engine["mode"] == "jar":
            return java, ["-jar", str(entry), "nogui"]
        if engine["mode"] == "args":
            return java, ["@" + str(entry), "nogui"]
        raise PanelError("نوع فایل اجرا نامعتبر است.")


class AddonService:
    def __init__(self, settings, store, downloads, log):
        self.settings, self.store, self.http, self.log = settings, store, downloads, log

    def context(self):
        engine = self.store.config.get("engine")
        if not engine:
            raise PanelError("اول یک نسخهٔ سرور نصب کن.")
        kind = engine["kind"]
        if kind in {"fabric", "forge", "neoforge"}:
            return engine["version"], [kind], "mod", "mods"
        if kind in {"paper", "purpur"}:
            return engine["version"], ["paper", "spigot", "bukkit"], "plugin", "plugins"
        if kind == "spigot":
            return engine["version"], ["spigot", "bukkit"], "plugin", "plugins"
        raise PanelError("Vanilla مود یا پلاگین اجرا نمی‌کند. Fabric/Forge برای مود یا Paper/Purpur برای پلاگین نصب کن.")

    async def search(self, query, offset=0):
        version, loaders, kind, _ = self.context()
        facets = [
            [f"project_type:{kind}"],
            [f"versions:{version}"],
            [f"categories:{x}" for x in loaders],
            ["server_side:required", "server_side:optional"],
        ]
        params = urlencode({"query": query[:100], "limit": 12, "offset": offset, "facets": json.dumps(facets)})
        data = await self.http.data("https://api.modrinth.com/v2/search?" + params)
        return {
            "hits": [{k: h.get(k) for k in ["project_id", "slug", "title", "description", "downloads", "author"]} for h in data["hits"]],
            "total": data["total_hits"],
            "kind": kind,
            "version": version,
            "loaders": loaders,
        }

    async def choose(self, project, version, loaders, pinned=None):
        valid_id(project)
        obj = await self.http.data(f"https://api.modrinth.com/v2/project/{project}")
        if obj.get("server_side") == "unsupported":
            raise PanelError(f"{obj.get('title', project)} فقط سمت کلاینت است و روی سرور نصب نمی‌شود.")
        if pinned:
            valid_id(pinned)
            chosen = await self.http.data(f"https://api.modrinth.com/v2/version/{pinned}")
            if chosen["project_id"] != obj["id"]:
                raise PanelError("وابستگی مود به پروژهٔ درستی اشاره نمی‌کند.")
        else:
            params = urlencode({"loaders": json.dumps(loaders), "game_versions": json.dumps([version])})
            choices = await self.http.data(f"https://api.modrinth.com/v2/project/{project}/version?" + params)
            releases = [c for c in choices if c.get("version_type") == "release"]
            if not releases:
                raise PanelError(f"نسخهٔ سازگار و پایدار برای {obj.get('title', project)} پیدا نشد.")
            chosen = max(releases, key=lambda c: c["date_published"])
        if version not in chosen.get("game_versions", []) or not set(loaders).intersection(chosen.get("loaders", [])):
            raise PanelError("نسخهٔ وابستگی با Minecraft یا مودلودر فعلی سازگار نیست.")
        files = [f for f in chosen["files"] if f["filename"].lower().endswith(".jar")]
        file = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not file or Path(file["filename"]).name != file["filename"] or "/" in file["filename"] or "\\" in file["filename"]:
            raise PanelError("این پروژه JAR قابل نصب روی سرور ندارد.")
        return obj, chosen, file

    async def install(self, project):
        game, loaders, kind, folder = self.context()
        collected, visiting = {}, set()

        async def collect(pid, pinned=None):
            valid_id(pid)
            obj, version, file = await self.choose(pid, game, loaders, pinned)
            key = obj["id"]
            if key in collected:
                if collected[key][1]["id"] != version["id"]:
                    raise PanelError("دو مود به نسخه‌های متفاوت یک وابستگی نیاز دارند؛ نصب لغو شد.")
                return
            if key in visiting:
                return
            if len(collected) + len(visiting) >= 25:
                raise PanelError("تعداد وابستگی‌های مود بیش از سقف نصب خودکار است؛ دستی نصب کن.")
            visiting.add(key)
            for dep in version.get("dependencies", []):
                if dep["dependency_type"] != "required":
                    continue
                dep_project = dep.get("project_id")
                if not dep_project and dep.get("version_id"):
                    exact = await self.http.data(f"https://api.modrinth.com/v2/version/{valid_id(dep['version_id'])}")
                    dep_project = exact["project_id"]
                if not dep_project:
                    raise PanelError("وابستگی فایل‌محور باید دستی نصب شود؛ نصب خودکار لغو شد.")
                await collect(dep_project, dep.get("version_id"))
            visiting.remove(key)
            collected[key] = (obj, version, file)

        await collect(project)
        directory = safe_path(self.settings.server_dir, folder)
        directory.mkdir(exist_ok=True)
        stage = self.settings.data_dir / "tmp" / uuid.uuid4().hex
        stage.mkdir()
        records = self.store.get("addons", {})
        installed, names = [], set()
        try:
            for pid, (obj, version, file) in collected.items():
                filename = file["filename"]
                safe_path(directory, filename, allow_root=False)
                if filename in names:
                    raise PanelError("نام فایل دو مود یکسان است؛ نصب لغو شد.")
                names.add(filename)
                hashes = file.get("hashes", {})
                algorithm = "sha512" if hashes.get("sha512") else "sha1"
                if not hashes.get(algorithm):
                    raise PanelError("فایل مود هش معتبر ندارد.", 502)
                self.log(f"دانلود {obj['title']} {version['version_number']}", "panel")
                await self.http.jar(file["url"], stage / filename, (algorithm, hashes[algorithm]))
                installed.append(
                    {
                        "project_id": pid,
                        "title": obj["title"],
                        "version": version["version_number"],
                        "version_id": version["id"],
                        "file": filename,
                        "folder": folder,
                        "kind": kind,
                        "minecraft": game,
                        "loader": loaders[0],
                        "installed": time.time(),
                    }
                )
            # All downloads/checksums/dependencies succeed before touching the active files.
            rollback = stage / "rollback"
            rollback.mkdir()
            moved, written = [], []
            try:
                for record in installed:
                    previous = records.get(record["project_id"])
                    candidates = {record["file"]}
                    if previous and previous["folder"] == folder:
                        candidates.add(previous["file"])
                    for filename in candidates:
                        active = safe_path(directory, filename, allow_root=False)
                        if active.exists():
                            if not active.is_file():
                                raise PanelError("نام مود با یک پوشه تداخل دارد.")
                            if filename not in moved:
                                os.replace(active, rollback / filename)
                                moved.append(filename)
                    os.replace(stage / record["file"], directory / record["file"])
                    written.append(record["file"])
                for record in installed:
                    records[record["project_id"]] = record
                self.store.put("addons", records)
            except BaseException:
                for filename in written:
                    (directory / filename).unlink(missing_ok=True)
                for filename in moved:
                    os.replace(rollback / filename, directory / filename)
                raise
            return [r["title"] for r in installed]
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def installed(self):
        records = self.store.get("addons", {})
        result = []
        for folder in ["mods", "plugins"]:
            directory = safe_path(self.settings.server_dir, folder)
            if not directory.is_dir():
                continue
            for file in sorted(directory.glob("*.jar")):
                if file.is_symlink():
                    continue
                record = next((r for r in records.values() if r["file"] == file.name and r["folder"] == folder), {})
                result.append(
                    record | {"file": file.name, "folder": folder, "size": file.stat().st_size, "enabled": True, "manual": not bool(record)}
                )
            for file in sorted(directory.glob("*.jar.disabled")):
                if not file.is_symlink():
                    record = next((r for r in records.values() if r["file"] == file.name[:-9] and r["folder"] == folder), {})
                    result.append(
                        record
                        | {"file": file.name, "folder": folder, "size": file.stat().st_size, "enabled": False, "manual": not bool(record)}
                    )
        return result
