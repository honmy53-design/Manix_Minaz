import asyncio
import json
import logging
import os
import re
import shutil
import signal
import struct
import time
import uuid
from pathlib import Path
from collections import deque
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import psutil

from .config import memory_limit_mb, safe_heap_mb
from .errors import PanelError
from .hardware import network_counters, quota_cpus, service_cpu_seconds, service_memory_mb
from .players import PlayerTracker
from .startup import startup_argv
from .paths import atomic_write, ensure_properties, safe_path

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def varint(number):
    number &= 0xFFFFFFFF
    out = bytearray()
    while True:
        part = number & 127
        number >>= 7
        out.append(part | (128 if number else 0))
        if not number:
            return bytes(out)


async def read_varint(reader):
    number = 0
    for shift in range(0, 35, 7):
        byte = (await reader.readexactly(1))[0]
        number |= (byte & 127) << shift
        if not byte & 128:
            return number
    raise ValueError("invalid Minecraft varint")


async def minecraft_status(port):
    writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        host = b"localhost"
        handshake = b"\x00" + varint(-1) + varint(len(host)) + host + struct.pack(">H", port) + b"\x01"
        writer.write(varint(len(handshake)) + handshake + b"\x01\x00")
        await writer.drain()
        size = await read_varint(reader)
        if size > 1024 * 1024 or await read_varint(reader) != 0:
            return None
        length = await read_varint(reader)
        if length > size or length > 1024 * 1024:
            return None
        return json.loads(await reader.readexactly(length))
    except (OSError, ValueError, asyncio.IncompleteReadError):
        return None
    finally:
        if writer:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


class ServerManager:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.process = None
        self.reader_task = None
        self.waiter_task = None
        self.sample_task = None
        self.crash_task = None
        self.phase = "stopped" if store.config["engine"] else "not_installed"
        self.started = 0
        self.last_exit = None
        self.last_exit_expected = None
        self.expected_stop = False
        self.closing = False
        self.lock = asyncio.Lock()
        self.active_job = None
        self.job_tasks = set()
        self.recent_jobs = deque(maxlen=30)
        self.lines = deque(maxlen=2000)
        self.sequence = 0
        self.panel_started = time.time()
        self.metrics_at = 0
        self.schedule_callback = None
        self.network_previous = None
        self.cpu_previous = None
        self.players = PlayerTracker(store)
        self.player_event = asyncio.Event()
        self.player_query_lock = asyncio.Lock()
        self.metrics = {
            "cpu_percent": 0,
            "memory_mb": 0,
            "players_online": 0,
            "players_max": 0,
            "players": [],
            "disk_used_mb": 0,
            "disk_total_mb": 0,
        }
        self.ps_process = None
        self.crashes = deque(maxlen=5)
        self.engine_service = None
        self.backup_callback = None
        self.logger = logging.getLogger(f"manix.console.{id(self)}")
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        self.handler = RotatingFileHandler(settings.panel_dir / "console.log", maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.logger.addHandler(self.handler)

    @property
    def running(self):
        return self.process is not None and self.process.returncode is None

    def log(self, text, source="server"):
        text = ANSI.sub("", str(text)).replace("\x00", "")[:32000]
        text = "".join(c for c in text if ord(c) >= 32 or c in "\t\n")
        self.sequence += 1
        self.lines.append({"id": self.sequence, "time": time.time(), "text": text, "source": source})
        self.logger.info("[%s] %s", source, text)
        if source == "server" and self.players.parse(text):
            self.player_event.set()

    def check_available(self, stopped=False):
        if self.lock.locked():
            raise PanelError("یک عملیات دیگر در حال اجراست؛ تا پایانش صبر کن.", 409)
        if stopped and self.running:
            raise PanelError("برای این تغییر اول سرور بازی را خاموش کن.", 409)

    @asynccontextmanager
    async def exclusive(self, stopped=False):
        self.check_available(stopped)
        await self.lock.acquire()
        try:
            yield
        finally:
            self.lock.release()

    async def new_job(self, title, function, *, stopped=False):
        self.check_available(stopped)
        await self.lock.acquire()
        job = {"id": uuid.uuid4().hex, "title": title, "state": "queued", "created": time.time(), "message": "در صف اجرا", "download": None}
        self.active_job = job
        try:
            self.store.save_job(job)
        except Exception as exc:
            self.active_job = None
            self.lock.release()
            logging.exception("Cannot persist queued job")
            raise PanelError("ثبت عملیات روی Volume ناموفق بود. فضای دیسک/دیتابیس را بررسی کن و بکاپ اضافی را حذف کن.", 507) from exc
        self.recent_jobs.append(job)

        async def execute():
            try:
                job.update(state="running", message="در حال اجرا…")
                self.store.save_job(job)
                self.log(title, "panel")
                result = await function()
                job.update(state="done", message="عملیات با موفقیت تمام شد.")
                if isinstance(result, dict):
                    job.update(result)
                self.store.audit("job.done", title)
            except asyncio.CancelledError:
                job.update(state="failed", message="عملیات به دلیل خاموش شدن سرویس قطع شد.")
                raise
            except PanelError as exc:
                job.update(state="failed", message=exc.message)
                self.log(exc.message, "panel")
                try:
                    self.store.audit("job.failed", title + ": " + exc.message)
                except Exception:
                    logging.exception("Cannot persist failed-job audit")
            except Exception:
                logging.exception("Manix job failed: %s", title)
                job.update(state="failed", message="خطای داخلی یا ذخیره‌سازی رخ داد؛ فضای Volume و لاگ Railway را بررسی کن.")
                self.log(job["message"], "panel")
            finally:
                job["finished"] = time.time()
                try:
                    self.store.save_job(job)
                except Exception:
                    logging.exception("Cannot persist finished job; in-memory result retained")
                finally:
                    self.active_job = None
                    self.lock.release()

        task = asyncio.create_task(execute(), name="job:" + job["id"])
        self.job_tasks.add(task)
        task.add_done_callback(self.job_tasks.discard)
        return dict(job)

    async def boot(self):
        self.log("مانیکس آماده است. فقط یک worker و یک replica اجرا کن.", "panel")
        self.sample_task = asyncio.create_task(self.sample_loop())
        config = self.store.config
        if config.get("autostart") and config.get("desired_running") and config.get("engine"):
            try:
                async with self.exclusive():
                    await self.start(internal=True)
            except PanelError as exc:
                self.log(exc.message, "panel")

    async def start(self, internal=False):
        if self.running:
            raise PanelError("سرور از قبل روشن است.", 409)
        config = self.store.config
        if not config.get("engine"):
            raise PanelError("اول از بخش نسخه‌ها یک سرور نصب کن.")
        if not config.get("eula_accepted"):
            raise PanelError("برای روشن کردن، باید خودت توافق‌نامهٔ Minecraft EULA را بپذیری.")
        heap = int(config["memory_mb"])
        maximum = safe_heap_mb()
        if maximum is not None and heap > maximum:
            raise PanelError(f"رم سرویس کافی نیست. با این سهمیه حداکثر heap پیشنهادی {maximum} MB است؛ رم را کم کن یا سرویس را ارتقا بده.")
        args = startup_argv(self.settings, self.store, self.engine_service)
        port = config.get("game_port", self.settings.mc_port)
        ensure_properties(self.settings.server_dir, port)
        atomic_write(safe_path(self.settings.server_dir, "eula.txt"), b"# Accepted by the server owner in Manix\neula=true\n")
        self.expected_stop = False
        self.last_exit = None
        self.log(f"شروع سرور با heap={heap} MB؛ پورت داخلی {port}", "panel")
        java_path = Path(args[0]).resolve()
        environment = dict(os.environ, JAVA_HOME=str(java_path.parent.parent))
        environment["PATH"] = str(java_path.parent) + os.pathsep + environment.get("PATH", "")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                cwd=self.settings.server_dir,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                limit=512 * 1024,
            )
        except OSError as exc:
            raise PanelError("اجرای Java ناموفق بود. Dockerfile و لاگ Railway را بررسی کن.") from exc
        self.phase, self.started = "starting", time.time()
        try:
            self.ps_process = psutil.Process(self.process.pid)
            self.ps_process.cpu_percent()
        except psutil.Error:
            self.ps_process = None
        if not internal:
            config["desired_running"] = True
            self.store.save_config()
        self.store.audit("server.start", config["engine"]["kind"] + " " + config["engine"]["version"])
        process = self.process
        self.reader_task = asyncio.create_task(self.read_output(process))
        self.waiter_task = asyncio.create_task(self.watch_exit(process))

    async def read_output(self, process):
        buffer = b""

        def emit(raw):
            text = raw.decode("utf-8", errors="replace").rstrip()
            self.log(text)
            if "Done (" in text and self.phase == "starting":
                self.phase = "running"

        try:
            while chunk := await process.stdout.read(8192):
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    emit(raw)
                if len(buffer) > 32000:
                    emit(buffer[:32000])
                    buffer = buffer[32000:]
            if buffer:
                emit(buffer)
        except OSError:
            self.log("ارتباط خروجی کنسول بسته شد.", "panel")

    async def watch_exit(self, process):
        code = await process.wait()
        expected = self.expected_stop or self.closing
        if process is self.process:
            self.phase = "stopped"
            self.players.stopped()
            self.last_exit = code
            self.last_exit_expected = self.expected_stop
            self.ps_process = None
            self.metrics.update(cpu_percent=0, memory_mb=0, players_online=0, players=[])
        self.log(f"فرایند بازی بسته شد؛ exit={code}" + (" (توقف درخواستی)" if expected else " (توقف غیرمنتظره)"), "panel")
        if code in {-9, 137}:
            self.log("کد 137 / SIGKILL ممکن است ناشی از کمبود رم باشد؛ مصرف و سهمیهٔ Railway را بررسی کن.", "panel")
        if not expected and self.store.config.get("auto_restart") and self.store.config.get("desired_running"):
            now = time.time()
            self.crashes.append(now)
            if len([t for t in self.crashes if now - t < 600]) >= 3:
                self.log("۳ توقف غیرمنتظره در ۱۰ دقیقه؛ برای جلوگیری از حلقهٔ کرش، ری‌استارت خودکار متوقف شد.", "panel")
            else:
                self.crash_task = asyncio.create_task(self.restart_after_crash())

    async def restart_after_crash(self):
        await asyncio.sleep(10)
        if self.closing or self.running or not self.store.config.get("desired_running") or not self.store.config.get("auto_restart"):
            return
        try:
            await self.new_job("بازیابی پس از توقف غیرمنتظره", lambda: self.start(internal=True))
        except PanelError as exc:
            self.log("بازیابی خودکار انجام نشد: " + exc.message, "panel")

    async def command(self, text, audit=True):
        text = text.strip()
        if text.startswith("/"):
            text = text[1:]
        if not text or len(text) > 1024 or any(ord(c) < 32 for c in text):
            raise PanelError("دستور باید یک خط و حداکثر ۱۰۲۴ کاراکتر باشد.")
        if not self.running or self.phase == "stopping":
            raise PanelError("سرور برای دریافت دستور روشن نیست.", 409)
        try:
            self.process.stdin.write((text + "\n").encode("utf-8"))
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            raise PanelError("اتصال کنسول بسته شده است.", 409) from None
        self.log("> " + text, "command")
        if audit:
            self.store.audit("console.command", text[:256])

    async def stop(self, internal=False):
        if not internal:
            self.store.config["desired_running"] = False
            self.store.save_config()
        if not self.running:
            return
        self.expected_stop = True
        self.phase = "stopping"
        process = self.process
        self.log("ذخیره و توقف امن سرور…", "panel")
        try:
            process.stdin.write(b"stop\n")
            await process.stdin.drain()
            await asyncio.wait_for(process.wait(), self.settings.stop_timeout)
        except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
            self.log("توقف عادی پاسخ نداد؛ ارسال SIGTERM.", "panel")
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), 10)
            except asyncio.TimeoutError:
                self.log("ارسال SIGKILL؛ آخرین تغییرات ذخیره‌نشده ممکن است از دست برود.", "panel")
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            except ProcessLookupError:
                pass
        if self.reader_task:
            await asyncio.gather(self.reader_task, return_exceptions=True)
        if self.waiter_task:
            await asyncio.gather(self.waiter_task, return_exceptions=True)
        self.phase = "stopped"
        self.store.audit("server.stop", "temporary" if internal else "manual")

    async def kill(self):
        self.store.config["desired_running"] = False
        self.store.save_config()
        if not self.running:
            return {"message": "بازی از قبل خاموش است."}
        self.expected_stop = True
        self.phase = "stopping"
        self.log("Kill اجباری؛ آخرین تغییرات ذخیره‌نشدهٔ دنیا ممکن است از دست برود.", "panel")
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await self.process.wait()
        await asyncio.gather(*[t for t in [self.reader_task, self.waiter_task] if t], return_exceptions=True)
        self.phase = "stopped"
        self.store.audit("server.kill", "explicit owner request")

    async def query_players(self):
        if not self.running or self.phase != "running" or self.lock.locked() or self.player_query_lock.locked():
            return
        if time.time() - self.players.full_at < 5:
            return
        async with self.player_query_lock:
            self.player_event.clear()
            try:
                await self.command("list", audit=False)
                await asyncio.wait_for(self.player_event.wait(), 0.8)
            except (asyncio.TimeoutError, PanelError):
                pass

    async def restart(self):
        await self.stop(internal=True)
        await self.start(internal=False)

    def status(self):
        config = self.store.config
        history = {job["id"]: job for job in self.store.jobs()}
        history.update({job["id"]: job for job in self.recent_jobs})
        jobs = sorted(history.values(), key=lambda job: job["created"], reverse=True)[:8]
        memory, memory_source = service_memory_mb(self.metrics["memory_mb"])
        limit = memory_limit_mb()
        warnings = []
        if limit and memory > limit * 0.85:
            warnings.append("مصرف حافظهٔ سرویس به سهمیه نزدیک شده است.")
        if self.metrics.get("disk_free_mb", 1000) < 256:
            warnings.append("فضای آزاد دیسک کمتر از ۲۵۶ MB است؛ بکاپ یا فایل اضافه را بررسی کن.")
        return {
            "node": {
                "name": os.getenv("RAILWAY_SERVICE_NAME", "نود مانیکس"),
                "region": os.getenv("RAILWAY_REPLICA_REGION", os.getenv("RAILWAY_REGION", "local")),
                "status": "ready" if self.metrics_at and time.time() - self.metrics_at < 12 else "initializing",
                "cpus_quota": quota_cpus(),
                "cpu_percent": self.metrics.get("node_cpu_percent", 0),
                "memory_mb": memory,
                "memory_source": memory_source,
                "uptime": int(time.time() - self.panel_started),
            },
            "warnings": warnings,
            "metrics_at": self.metrics_at,
            "phase": self.phase,
            "running": self.running,
            "uptime": int(time.time() - self.started) if self.running else 0,
            "last_exit": self.last_exit,
            "last_exit_expected": self.last_exit_expected,
            "engine": config["engine"],
            "name": config["server_name"],
            "heap_mb": config["memory_mb"],
            "memory_limit_mb": memory_limit_mb(),
            "recommended_heap_mb": safe_heap_mb(),
            "metrics": dict(self.metrics),
            "busy": self.lock.locked(),
            "job": self.active_job,
            "jobs": jobs,
            "volume_attached": bool(os.getenv("RAILWAY_VOLUME_MOUNT_PATH")) if self.settings.railway else True,
            "mc_port": config.get("game_port", self.settings.mc_port),
        }

    async def sample_loop(self):
        disk_tick = 0
        while not self.closing:
            try:
                if self.ps_process and self.running:
                    self.metrics["cpu_percent"] = round(self.ps_process.cpu_percent(), 1)
                    self.metrics["memory_mb"] = round(self.ps_process.memory_info().rss / 1024 / 1024, 1)
                    if self.phase != "stopping":
                        data = await asyncio.wait_for(minecraft_status(self.store.config.get("game_port", self.settings.mc_port)), 1.5)
                        if data:
                            players = data.get("players", {})
                            self.metrics.update(
                                players_online=players.get("online", 0),
                                players_max=players.get("max", 0),
                                players=[p.get("name", "") for p in players.get("sample", [])],
                            )
                            if self.phase == "starting":
                                self.phase = "running"
                if time.monotonic() - disk_tick > 30:
                    usage = await asyncio.to_thread(shutil.disk_usage, self.settings.data_dir)
                    self.metrics.update(
                        disk_used_mb=round(usage.used / 1024 / 1024),
                        disk_total_mb=round(usage.total / 1024 / 1024),
                        disk_free_mb=round(usage.free / 1024 / 1024),
                    )
                    disk_tick = time.monotonic()
                now = time.monotonic()
                cpu_seconds, cpu_source = service_cpu_seconds(self.ps_process if self.running else None)
                cpu_rate = 0
                if self.cpu_previous:
                    previous_time, previous_cpu = self.cpu_previous
                    cpu_rate = max(0, cpu_seconds - previous_cpu) / max(0.01, now - previous_time) * 100
                self.cpu_previous = now, cpu_seconds
                self.metrics.update(node_cpu_percent=round(cpu_rate, 1), node_cpu_source=cpu_source)
                received, sent = network_counters()
                rx, tx = 0, 0
                if self.network_previous:
                    previous_time, previous_rx, previous_tx = self.network_previous
                    elapsed = max(0.01, now - previous_time)
                    rx, tx = max(0, received - previous_rx) / elapsed, max(0, sent - previous_tx) / elapsed
                self.network_previous = now, received, sent
                self.metrics.update(
                    network_rx_bytes=received,
                    network_tx_bytes=sent,
                    network_rx_kbps=round(rx / 1024, 2),
                    network_tx_kbps=round(tx / 1024, 2),
                )
                self.metrics_at = time.time()
                self.players.flush()
                if self.schedule_callback and not self.lock.locked():
                    await self.schedule_callback()
                config = self.store.config
                hours = config.get("backup_hours", 0)
                if (
                    hours
                    and config.get("engine")
                    and self.backup_callback
                    and not self.lock.locked()
                    and (not self.running or self.phase == "running")
                ):
                    if time.time() - config.get("last_auto_backup", 0) > hours * 3600 and time.time() - config.get(
                        "last_auto_backup_attempt", 0
                    ) > min(3600, hours * 3600):
                        # A failed backup must not stop/restart the game every two seconds.
                        config["last_auto_backup_attempt"] = time.time()
                        self.store.save_config()
                        await self.new_job("بکاپ زمان‌بندی‌شده", self.backup_callback)
                restart_hours = config.get("restart_hours", 0)
                if (
                    restart_hours
                    and self.running
                    and self.phase == "running"
                    and not self.lock.locked()
                    and time.time() - self.started > restart_hours * 3600
                ):
                    await self.new_job("ری‌استارت زمان‌بندی‌شده", self.restart)
            except asyncio.CancelledError:
                raise
            except (psutil.Error, PanelError, OSError, asyncio.TimeoutError):
                pass
            except Exception:
                logging.exception("Metrics / scheduler error")
            await asyncio.sleep(2)

    async def close(self):
        self.closing = True
        tasks = list(self.job_tasks)
        for task in [self.sample_task, self.crash_task, *tasks]:
            if task:
                task.cancel()
        await asyncio.gather(*[t for t in [self.sample_task, self.crash_task, *tasks] if t], return_exceptions=True)
        await self.stop(internal=True)
        try:
            self.players.flush(force=True)
        except Exception:
            logging.exception("Cannot save Manix player observations during shutdown")
        self.handler.close()
        self.logger.removeHandler(self.handler)
