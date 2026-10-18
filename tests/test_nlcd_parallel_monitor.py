"""Telemetry failure is diagnostic evidence, not a worker shutdown instruction."""

import subprocess
from pathlib import Path

import pytest

from lyme_gap_atlas_data import nlcd_parallel_monitor as monitor


@pytest.mark.parametrize("error", ["timeout", "command", "json"])
def test_telemetry_failure_preserves_traceback_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    monkeypatch.setattr(monitor.os, "getloadavg", lambda: (1, 1, 1), raising=False)
    original = Path.read_text

    def read(path: Path, *args: object, **kwargs: object) -> str:
        if path.as_posix() == "/proc/stat":
            return "cpu 1 2 3 4 5 6 7 8\n"
        if path.as_posix() == "/proc/diskstats":
            return "8 0 vda 1 2 3 4 5 6 7 8 9 10 11\n"
        if path.as_posix() == "/proc/meminfo":
            return "MemAvailable: 123 kB\n"
        return original(path)

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if error == "timeout":
            raise subprocess.TimeoutExpired("docker stats", 15)
        if error == "command":
            raise subprocess.CalledProcessError(1, "docker stats")
        return subprocess.CompletedProcess([], 0, stdout="incomplete JSON")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(monitor.subprocess, "run", run)
    record = monitor.observe(tmp_path)
    assert "Traceback" in record["monitor_error"]
    assert "docker" not in record
    assert record["memory"]["MemAvailable"] == 123 * 1024
