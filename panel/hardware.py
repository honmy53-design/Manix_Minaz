"""مانیکس: cgroup-aware node information and service-level network counters."""

import os
from pathlib import Path

import psutil


def quota_cpus():
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return round(int(quota) / int(period), 2)
    except (OSError, ValueError):
        pass
    return None


def service_memory_mb(game_mb=0):
    for name in ["/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"]:
        try:
            return round(int(Path(name).read_text().strip()) / 1024 / 1024, 1), "cgroup"
        except (OSError, ValueError):
            pass
    return round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024 + game_mb, 1), "estimated-panel-and-game"


def network_counters():
    counters = [counter for name, counter in psutil.net_io_counters(pernic=True).items() if name != "lo"]
    return sum(c.bytes_recv for c in counters), sum(c.bytes_sent for c in counters)


def service_cpu_seconds(game_process=None):
    try:
        pairs = dict(line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())
        return int(pairs["usage_usec"]) / 1_000_000, "cgroup"
    except (OSError, ValueError, KeyError):
        pass
    try:
        return int(Path("/sys/fs/cgroup/cpuacct/cpuacct.usage").read_text()) / 1_000_000_000, "cgroup"
    except (OSError, ValueError):
        pass
    own = psutil.Process().cpu_times()
    value = own.user + own.system
    if game_process:
        try:
            game = game_process.cpu_times()
            value += game.user + game.system
        except psutil.Error:
            pass
    return value, "estimated-panel-and-game"
