from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX worker wrapper exercised in Linux CI")
@pytest.mark.parametrize(
    "state", ["inactive", "active", "activating", "deactivating", "failed", "unknown", "", "ERROR"]
)
def test_worker_launch_requires_positive_inactive_state(tmp_path: Path, state: str) -> None:
    commands = {
        "realpath": "echo /var/tmp/atlas-nlcd-relay/12345678-1234-1234-1234-123456789abc",
        "stat": 'if [ "$2" = "%a" ]; then echo 700; else echo 1; fi',
        "id": "echo 1",
        "systemctl": (
            'if [ "$3" = "--property=LoadState" ]; then echo loaded; '
            'elif [ "$FAKE_STATE" = ERROR ]; then exit 1; '
            'else printf "%s\\n" "$FAKE_STATE"; fi'
        ),
        "cat": "echo 12345678-1234-1234-1234-123456789abc",
        "mkdir": "exit 0",
        "timeout": "echo LAUNCH",
        "docker": "exit 1",
    }
    for name, body in commands.items():
        path = tmp_path / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "FAKE_STATE": state,
    }
    script = Path(__file__).parents[1] / "scripts/run_nlcd_storage_once.sh"
    result = subprocess.run(
        ["/bin/bash", str(script), "owned-directory", "canary"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert ("LAUNCH" in result.stdout) is (state == "inactive")
    assert (result.returncode == 0) is (state == "inactive")
