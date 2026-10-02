"""مانیکس / Manix: Optional network smoke test. Downloads to a disposable directory, never accepts EULA."""

import argparse
import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from panel.config import Settings
from panel.engines import Downloads, EngineService
from panel.paths import ensure_properties


async def run(args):
    root = Path(tempfile.mkdtemp(prefix="manix-sources-", dir=args.directory))
    settings = Settings(root, "qa", "source-check-only-password")
    settings.prepare()
    http = Downloads()
    lines = []

    def log(message, source="panel"):
        lines.append(str(message))
        if source != "installer":
            print(message, flush=True)

    engines = EngineService(settings, http, log)
    try:
        for item in args.targets:
            kind, version = item.split("/", 1)
            versions = await engines.versions(kind)
            assert version in {v["id"] for v in versions}, (kind, version)
            print(f"LIST OK {kind}: {len(versions)} supported release versions", flush=True)
            if not args.download:
                continue
            engine = await engines.install(kind, version)
            print(f"INSTALL OK {kind}/{version}: build={engine['build']} java={engine['java']} mode={engine['mode']}", flush=True)
            if args.launch:
                game = root / (kind + "-game")
                game.mkdir()
                ensure_properties(game, 25565)
                (game / "eula.txt").write_text("eula=false\n")
                java, argv = engines.launch(engine)
                proc = await asyncio.create_subprocess_exec(
                    java, "-Xmx768M", *argv, cwd=game, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
                )
                try:
                    output, _ = await asyncio.wait_for(proc.communicate(), 180)
                except BaseException:
                    proc.kill()
                    await proc.wait()
                    raise
                text = output.decode(errors="replace")
                (root / (kind + ".log")).write_text(text)
                if (
                    "eula" not in text.lower()
                    or "exception in thread" in text.lower()
                    or "could not find or load main class" in text.lower()
                ):
                    raise AssertionError(f"{kind} did not reach EULA gate: {text[-6000:]}")
                print(f"LAUNCH OK {kind}/{version}: reached EULA gate (NOT accepted); exit={proc.returncode}", flush=True)
    finally:
        await http.close()
        if args.keep:
            print("QA artifacts (do not upload to GitHub):", root)
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        default=["vanilla/1.21.1", "paper/1.21.1", "purpur/1.21.1", "fabric/1.21.1", "forge/1.20.1", "neoforge/1.21.1"],
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--launch", action="store_true", help="requires --download; runs only to EULA gate")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--directory", default=None)
    args = parser.parse_args()
    if args.launch and not args.download:
        parser.error("--launch requires --download")
    for version in (8, 17, 21, 25):
        candidate = os.getenv(f"JAVA_{version}_BIN")
        if candidate:
            print(f"Using operator-supplied Java {version}: {candidate}")
    asyncio.run(run(args))
