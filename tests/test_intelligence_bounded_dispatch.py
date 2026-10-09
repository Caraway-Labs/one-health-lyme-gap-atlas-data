"""Executable, offline validation of the bounded feed dispatch branches."""

import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.migrations import load_migrations

ROOT = Path(__file__).parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def test_exact_prerequisite_branch_exits_before_both_standalone_sql_reads():
    steps = workflow("deploy-dev.yml")["jobs"]["deploy"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    branch = script.index('if [ "$feed_batch" = "true" ]')
    apply = script.index("uv run atlas-data pipeline apply-reviewed-dev-migrations", branch)
    end = script.index("exit 0", apply)
    assert branch < apply < end < script.index("SELECT CURRENT_ACCOUNT()")
    assert end < script.index("SELECT version, filename, sha256, applied_at")
    assert 'test "$FEED_PREFLIGHT_ACCOUNTING_CONFIRMED" = "true"' in script[branch:end]
    assert "selected = is_intelligence_prerequisite_batch(reviewed)" in script
    assert "--feed-preflight-accounting-confirmed --confirm" in script[branch:end]


def test_workflow_selector_uses_actual_v142_metadata_without_credentials():
    steps = workflow("deploy-dev.yml")["jobs"]["deploy"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    selector = script.split("feed_batch=\"$(uv run python - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    v142 = next(item for item in load_migrations() if item.version == "V142")
    reviewed = [{"version": v142.version, "filename": v142.filename, "sha256": v142.sha256}]
    environment = os.environ.copy()
    environment["EXPECTED_PENDING_JSON"] = json.dumps(reviewed)
    result = subprocess.run(
        [sys.executable, "-c", selector],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "true"
    environment["EXPECTED_PENDING_JSON"] = json.dumps(
        reviewed + [{"version": "V141", "filename": "V141__other.sql", "sha256": "a" * 64}]
    )
    mixed = subprocess.run(
        [sys.executable, "-c", selector], capture_output=True, text=True, env=environment
    )
    assert mixed.returncode != 0


def guard_script(inputs):
    steps = workflow("run-ingestion.yml")["jobs"]["ingest"]["steps"]
    script = next(
        step["run"] for step in steps if step.get("name") == "Enforce environment and tier boundary"
    )
    start = script.index('if [ "${INTELLIGENCE_ACQUISITION_ONLY:-false}" = "true" ]')
    script = script[start : script.index("\nfi\n", start) + 4]
    for name, value in inputs.items():
        script = script.replace("${{ inputs." + name + " }}", value)
    assert "${{" not in script
    return script


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"definition": "config/sources/intelligence_nih_news_releases.yml"},
        {"definition": "config/sources/intelligence_cdc_vital_signs.yml"},
        {"operation": "resume"},
        {"operation": "validate"},
        {"operation": "spaces-readiness"},
        {"environment_name": "production"},
        {"tier": "A"},
        {"tier": "C"},
        {"run_id": "existing"},
        {"publish": "true"},
        {"recapture": "true"},
        {"definition": "config/sources/cdc_x5j9_wybp.yml"},
    ],
)
def test_capture_validation_executes_without_any_provider_operation(override):
    values = {
        "operation": "run",
        "environment_name": "dev",
        "tier": "B",
        "publish": "false",
        "recapture": "false",
        "run_id": "",
        "definition": "config/sources/intelligence_cdc_eid_expedited.yml",
    } | override
    bash = Path("C:/Program Files/Git/bin/bash.exe")
    executable = str(bash) if bash.exists() else shutil.which("bash")
    assert executable is not None
    environment = dict(
        os.environ,
        INTELLIGENCE_ACQUISITION_ONLY="true",
        SOURCE_DEFINITION=values["definition"],
        MEASUREMENT_RUN_ID=values["run_id"],
    )
    result = subprocess.run(
        [
            executable,
            "-e",
            "-c",
            guard_script(
                {key: value for key, value in values.items() if key not in ("definition", "run_id")}
            ),
        ],
        env=environment,
        capture_output=True,
        timeout=15,
    )
    assert (result.returncode == 0) == (
        override
        in (
            {},
            {"definition": "config/sources/intelligence_nih_news_releases.yml"},
            {"definition": "config/sources/intelligence_cdc_vital_signs.yml"},
        )
    )


def test_capture_stop_reuses_cli_and_skips_untimed_identity_probe():
    steps = workflow("run-ingestion.yml")["jobs"]["ingest"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Execute orchestrator operation with ephemeral Snowflake key"
    )
    assert 'if [ "${INTELLIGENCE_ACQUISITION_ONLY:-false}" != "true" ]' in script
    assert "extra_args+=(--fail-after-stage ACQUIRE)" in script
    assert '--tier "${{ inputs.tier }}" "${extra_args[@]}"' in script
    assert "|| true" not in script


@pytest.mark.parametrize("index", [None, 0, 1, 2, 3])
def test_prerequisite_identity_verified_inside_existing_session_limits(monkeypatch, index):
    identity = [
        "OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
        "OH_LYME_DEV_MIGRATION_DEPLOYER",
        "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "OH_LYME_DEV_INGEST_XS_WH",
    ]
    if index is not None:
        identity[index] = "WRONG"
    cursor = Mock()
    cursor.fetchone.return_value = tuple(identity)
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(runtime, "connect", lambda *_: nullcontext(connection))
    if index is None:
        runtime.verify_prerequisite_identity(Mock())
    else:
        with pytest.raises(PermissionError, match="IDENTITY"):
            runtime.verify_prerequisite_identity(Mock())
    assert cursor.execute.call_count == 1
