"""Optional Linux telemetry process; never owns or terminates calculation workers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def observe(root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"utc": datetime.now(UTC).isoformat()}
    try:
        loadavg = getattr(os, "getloadavg", None)
        if loadavg is None:
            raise OSError("Linux load metrics unavailable")
        record["load"] = list(loadavg())
        record["free_disk_bytes"] = shutil.disk_usage(root).free
        record["cpu_ticks"] = Path("/proc/stat").read_text().splitlines()[0]
        record["diskstats"] = [
            line
            for line in Path("/proc/diskstats").read_text().splitlines()
            if line.split()[2] in ("vda", "vda1")
        ]
        record["memory"] = {
            line.split(":")[0]: int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.split(":")[0] in ("MemTotal", "MemAvailable", "Cached", "Dirty")
        }
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        record["docker"] = [json.loads(line) for line in result.stdout.splitlines() if line]
    except Exception:
        # A timeout/vanishing stats observation must not kill a healthy supervisor.
        # Keep the exception, rather than converting missing telemetry to zero usage.
        record["monitor_error"] = traceback.format_exc()
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--max-duration", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.max_duration <= 7 * 86400:
        parser.error("Invalid bounded monitor duration")
    started = time.monotonic()
    with args.output.open("a", encoding="utf-8") as handle:
        while time.monotonic() - started < args.max_duration:
            record = observe(args.root)
            record["elapsed_seconds"] = time.monotonic() - started
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            time.sleep(10)


if __name__ == "__main__":
    main()
