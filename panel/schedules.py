"""مانیکس: persistent one-off, daily and weekly tasks with explicit IANA timezone."""

import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import PanelError

ACTIONS = {"start", "stop", "restart", "backup", "command"}


def validate_command(value):
    value = value.strip().lstrip("/")
    if not value or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise PanelError("دستور باید یک خط غیرخالی، حداکثر ۱۰۲۴ کاراکتر باشد.")
    if value.split()[0].lower() in {"stop", "restart", "minecraft:stop", "bukkit:restart", "spigot:restart"}:
        raise PanelError("توقف و ری‌استارت باید از Task مخصوص خودشان انجام شوند.")
    return value


def zone(name):
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise PanelError("منطقهٔ زمانی معتبر IANA انتخاب کن؛ مثلاً Asia/Tehran.") from exc


def civil(year, month, day, hour, minute, tz):
    value = datetime(year, month, day, hour, minute, tzinfo=tz, fold=0)
    roundtrip = value.astimezone(timezone.utc).astimezone(tz)
    if (roundtrip.year, roundtrip.month, roundtrip.day, roundtrip.hour, roundtrip.minute) != (year, month, day, hour, minute):
        return None  # Non-existent DST wall-clock times are not silently shifted.
    return value


def next_run(task, now=None):
    now = time.time() if now is None else now
    tz = zone(task["timezone"])
    if task["mode"] == "once":
        try:
            value = datetime.fromisoformat(task.get("at", ""))
            if value.tzinfo:
                value = value.astimezone(tz)
            else:
                value = civil(value.year, value.month, value.day, value.hour, value.minute, tz)
        except ValueError as exc:
            raise PanelError("زمان یک‌باره نامعتبر است.") from exc
        if value is None or value.timestamp() <= now:
            raise PanelError("زمان اجرای یک‌باره باید در آینده و در ساعت معتبر باشد.")
        return value.timestamp()
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", task.get("time", ""))
    if not match:
        raise PanelError("زمان را به صورت HH:MM وارد کن.")
    hour, minute = int(match[1]), int(match[2])
    today = datetime.fromtimestamp(now, tz).date()
    for offset in range(15):
        date = today + timedelta(days=offset)
        if task["mode"] == "weekly" and date.weekday() != task.get("weekday"):
            continue
        value = civil(date.year, date.month, date.day, hour, minute, tz)
        if value is not None and value.timestamp() > now + 0.01:
            return value.timestamp()
    raise PanelError("زمان اجرای بعدی پیدا نشد.")


class ScheduleService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.backoff_until = 0

    def list(self):
        tasks = self.ctx.store.get("schedules", {})
        jobs = {job["id"]: job for job in self.ctx.store.jobs()}
        jobs.update({job["id"]: job for job in self.ctx.manager.recent_jobs})
        for task in tasks.values():
            job = jobs.get(task.get("last_job"))
            if task.get("last_result") == "claimed" and job and job["state"] == "failed":
                task["last_result"] = "failed"
        return sorted(tasks.values(), key=lambda t: t.get("next_run") or float("inf"))

    def save(self, task, identifier=None):
        tasks = self.ctx.store.get("schedules", {})
        if identifier and identifier not in tasks:
            raise PanelError("Task پیدا نشد.", 404)
        if not identifier and len(tasks) >= 50:
            raise PanelError("حداکثر ۵۰ Task مجاز است.")
        zone(task["timezone"])
        if task["action"] not in ACTIONS:
            raise PanelError("عملیات زمان‌بندی معتبر نیست.")
        if task["action"] == "command":
            task["command"] = validate_command(task["command"])
        identifier = identifier or uuid.uuid4().hex
        previous = tasks.get(identifier, {})
        task.update(
            id=identifier,
            next_run=next_run(task) if task["enabled"] else None,
            last_run=previous.get("last_run"),
            last_result=previous.get("last_result"),
            created=previous.get("created", time.time()),
        )
        tasks[identifier] = task
        self.ctx.store.put("schedules", tasks)
        self.ctx.store.audit("schedule.save", task["name"])
        return task

    def toggle(self, identifier, enabled):
        tasks = self.ctx.store.get("schedules", {})
        if identifier not in tasks:
            raise PanelError("Task پیدا نشد.", 404)
        task = tasks[identifier]
        task["enabled"] = enabled
        task["next_run"] = next_run(task) if enabled else None
        self.ctx.store.put("schedules", tasks)

    def delete(self, identifier):
        tasks = self.ctx.store.get("schedules", {})
        tasks.pop(identifier, None)
        self.ctx.store.put("schedules", tasks)
        self.ctx.store.audit("schedule.delete", identifier)

    async def operation(self, task):
        manager = self.ctx.manager
        if task["action"] == "start":
            if manager.running:
                return {"message": "بازی از قبل روشن بود؛ Task بدون تغییر تمام شد."}
            return await manager.start()
        if task["action"] == "stop":
            return await manager.stop()
        if task["action"] == "restart":
            return await manager.restart()
        if task["action"] == "backup":
            return await self.ctx.backups.create(automatic=True)
        await manager.command(task["command"])
        return {"message": "دستور زمان‌بندی ارسال شد."}

    async def tick(self, now=None):
        now = time.time() if now is None else now
        if now < self.backoff_until or self.ctx.manager.lock.locked():
            return
        tasks = self.ctx.store.get("schedules", {})
        due = sorted(
            [t for t in tasks.values() if t.get("enabled") and t.get("next_run", float("inf")) <= now], key=lambda t: t["next_run"]
        )
        if not due:
            return
        task = due[0]
        if self.ctx.manager.phase == "starting" and task["action"] in {"backup", "command", "restart"}:
            return
        # No large burst of stale starts/commands after days of downtime.
        missed = now - task["next_run"] > 600
        if task["mode"] == "once":
            task.update(enabled=False, next_run=None)
        else:
            task["next_run"] = next_run(task, now + 0.1)
        task["last_run"] = now
        task["last_result"] = "missed" if missed else "claimed"
        self.ctx.store.put("schedules", tasks)
        if missed:
            self.ctx.store.audit("schedule.missed", task["name"])
            return
        snapshot = dict(task)

        async def execute():
            result = "done"
            try:
                return await self.operation(snapshot)
            except BaseException:
                result = "failed"
                raise
            finally:
                latest = self.ctx.store.get("schedules", {})
                if snapshot["id"] in latest:
                    latest[snapshot["id"]]["last_result"] = result
                    self.ctx.store.put("schedules", latest)

        try:
            job = await self.ctx.manager.new_job("زمان‌بندی: " + task["name"], execute)
            latest = self.ctx.store.get("schedules", {})
            if task["id"] in latest:
                latest[task["id"]]["last_job"] = job["id"]
                self.ctx.store.put("schedules", latest)
        except PanelError:
            self.backoff_until = now + 60
            task["last_result"] = "failed"
            tasks[task["id"]] = task
            self.ctx.store.put("schedules", tasks)
