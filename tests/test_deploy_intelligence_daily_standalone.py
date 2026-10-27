"""The deploy script must run with plain python and no installed package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "scripts/deploy_intelligence_daily.py",
    "scripts/prod_intelligence_daily_job_spec.py",
)


def test_scripts_import_without_installed_package() -> None:
    # -S skips site-packages, so the editable install is not importable. This is
    # how the promote and run-once workflows run these scripts.
    for script in SCRIPTS:
        result = subprocess.run(
            [sys.executable, "-S", str(ROOT / script), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0, (script, result.stderr[-400:])
        assert "ModuleNotFoundError" not in result.stderr
