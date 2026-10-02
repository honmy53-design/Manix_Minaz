"""مانیکس: guarded JVM flags; never an arbitrary shell startup command."""

import re
import shlex

from .errors import PanelError

SAFE_FLAGS = {
    "-XX:+UseG1GC",
    "-XX:+UseZGC",
    "-XX:+UseSerialGC",
    "-XX:+UseParallelGC",
    "-XX:+ParallelRefProcEnabled",
    "-XX:+DisableExplicitGC",
    "-XX:+AlwaysPreTouch",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+UseStringDeduplication",
    "-Dfile.encoding=UTF-8",
}
GC_FLAGS = {"-XX:+UseG1GC", "-XX:+UseZGC", "-XX:+UseSerialGC", "-XX:+UseParallelGC"}


def validate_jvm_args(values):
    if len(values) > 24 or len(set(values)) != len(values):
        raise PanelError("حداکثر ۲۴ آرگومان یکتای JVM مجاز است.")
    for value in values:
        if value in SAFE_FLAGS:
            continue
        match = re.fullmatch(r"-XX:(MaxGCPauseMillis|G1ReservePercent|InitiatingHeapOccupancyPercent)=(\d{1,4})", value)
        if match:
            ranges = {"MaxGCPauseMillis": (10, 1000), "G1ReservePercent": (1, 50), "InitiatingHeapOccupancyPercent": (5, 90)}
            if ranges[match[1]][0] <= int(match[2]) <= ranges[match[1]][1]:
                continue
        if re.fullmatch(r"-XX:G1HeapRegionSize=(1|2|4|8|16|32)[mM]", value):
            continue
        raise PanelError("این آرگومان JVM مجاز نیست: " + value[:100])
    if len(set(values).intersection(GC_FLAGS)) > 1:
        raise PanelError("فقط یک نوع Garbage Collector انتخاب کن.")
    return values


def startup_argv(settings, store, engines):
    config = store.config
    if not config.get("engine"):
        raise PanelError("اول یک هستهٔ سرور نصب کن.")
    java, tail = engines.launch(config["engine"], config["java_override"])
    flags = validate_jvm_args(config.get("jvm_args", []))
    actual_java = config.get("java_override") or config["engine"]["java"]
    if "-XX:+UseZGC" in flags and actual_java < 17:
        raise PanelError("UseZGC در این پنل فقط با Java 17 به بالا مجاز است.")
    heap = int(config["memory_mb"])
    return [java, f"-Xms{min(256, heap)}M", f"-Xmx{heap}M", "-Djava.awt.headless=true", *flags, *tail]


def preview(settings, store, engines):
    if not store.config.get("engine"):
        return {"command": None, "args": [], "message": "بعد از نصب هسته، فرمان ساخته‌شدهٔ Java نمایش داده می‌شود."}
    args = startup_argv(settings, store, engines)
    return {"command": shlex.join(args), "args": args, "editable_shell": False}
