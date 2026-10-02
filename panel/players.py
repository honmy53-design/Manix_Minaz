"""مانیکس: observed player sessions; no invented join times."""

import re
import time

NAME = r"[A-Za-z0-9_]{3,16}"


class PlayerTracker:
    def __init__(self, store):
        self.store = store
        self.history = store.get("players_seen", {})
        for item in self.history.values():
            item["online"] = False
        self.dirty = False
        self.last_full = None
        self.full_at = 0
        self.last_flush = 0

    def parse(self, text):
        body = text.split("]: ", 1)[-1]
        now = time.time()
        join = re.fullmatch(rf"({NAME}) joined the game", body)
        leave = re.fullmatch(rf"({NAME}) left the game", body)
        login = re.match(rf"({NAME})\[/([^\]]+)\] logged in with entity id", body)
        listed = re.match(r"There are (\d+) of a max(?:imum)? of \d+ players online:\s*(.*)$", body, re.I)
        if join or leave or login:
            name = (join or leave or login)[1]
            record = self.history.setdefault(name, {"name": name, "first_seen": now, "joined_at": None, "left_at": None, "online": False})
            if join:
                record.update(joined_at=now, online=True)
                if self.last_full is not None and name not in self.last_full:
                    self.last_full.append(name)
            if leave:
                record.update(left_at=now, online=False)
                if self.last_full is not None and name in self.last_full:
                    self.last_full.remove(name)
            if login:
                address = login[2]
                record["observed_address"] = address[:100]
            self.dirty = True
        if listed:
            names = [name.strip() for name in listed[2].split(",") if re.fullmatch(NAME, name.strip())]
            if len(names) == int(listed[1]):
                self.last_full, self.full_at = names, now
                for item in self.history.values():
                    item["online"] = item["name"] in names
                self.dirty = True
                return True
        return False

    def stopped(self):
        for item in self.history.values():
            item["online"] = False
        self.last_full = None
        self.dirty = True

    def details(self, sample, running):
        full = self.last_full if running and time.time() - self.full_at < 60 else None
        names = full if full is not None else sample if running else []
        return {
            "online": names,
            "source": "console-list" if full is not None else "status-sample",
            "online_info": [self.history.get(name, {"name": name, "joined_at": None}) | {"online": True} for name in names],
            "known": sorted(self.history.values(), key=lambda r: r.get("joined_at") or r.get("first_seen", 0), reverse=True)[:1000],
        }

    def flush(self, force=False):
        if self.dirty and (force or time.time() - self.last_flush > 30):
            ordered = sorted(self.history.items(), key=lambda p: p[1].get("first_seen", 0), reverse=True)[:5000]
            self.history = dict(ordered)
            self.store.put("players_seen", self.history)
            self.dirty = False
            self.last_flush = time.time()
