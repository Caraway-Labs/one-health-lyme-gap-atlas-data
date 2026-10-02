"""Evidence/privacy regressions independent of Snowflake credentials."""

import copy
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from lyme_gap_atlas_data.metadata_cli import app
from lyme_gap_atlas_data.metadata_snapshots import (
    collect_dev,
    digest,
    evidence_hash,
    load_scope,
    render_report,
    report,
    snapshot,
    snapshot_schema,
    snow_rows,
    validate_snapshot,
)

NOW = datetime(2026, 10, 2, tzinfo=UTC)
HEAD = "a" * 40


@pytest.fixture
def facts():
    return {
        "source": "synthetic",
        "identity": {"role": "read", "environment": "dev"},
        "ledger_complete": False,
        "objects": [
            {
                "table_schema": "GOVERNANCE",
                "table_name": "INGESTION_RUNS",
                "table_type": "BASE TABLE",
                "table_owner": "OH_LYME_DEV_OWNER",
                "comment": "PRIVATE_SENTINEL",
            }
        ],
        "columns": [
            {
                "table_schema": "GOVERNANCE",
                "table_name": "INGESTION_RUNS",
                "column_name": "STATUS",
                "data_type": "TEXT",
                "is_nullable": "NO",
                "ordinal_position": 6,
                "character_maximum_length": 16777216,
                "default": "'PRIVATE_SENTINEL'",
            }
        ],
        "grants": [
            {
                "grantee_name": "OH_LYME_DEV_RUNTIME",
                "granted_on": "ROLE",
                "name": "OH_LYME_DEV_OWNER",
                "privilege": "USAGE",
            },
            {
                "grantee_name": "OH_LYME_DEV_OWNER",
                "granted_on": "TABLE",
                "name": "ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INGESTION_RUNS",
                "privilege": "INSERT",
                "grant_option": False,
                "granted_by": "PRIVATE_SENTINEL",
            },
        ],
        "future_grants": [
            {
                "grantee_name": "OH_LYME_DEV_RUNTIME",
                "grant_on": "TABLE",
                "name": "ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.<TABLE>",
                "privilege": "INSERT",
                "grant_option": False,
            }
        ],
        "unavailable": [],
    }


def make(facts, **kwargs):
    return snapshot(facts, environment="dev", generated_at=NOW, code_commit=HEAD, **kwargs)


def test_deterministic_hash_and_sanitized_fields(facts):
    first = make(facts)
    second = snapshot(
        facts, environment="dev", generated_at=NOW + timedelta(hours=1), code_commit="b" * 40
    )
    assert first["content"] == second["content"]
    assert first["semantic_hash"] == second["semantic_hash"]
    validate_snapshot(first)
    assert "PRIVATE_SENTINEL" not in json.dumps(first)
    assert first["content"]["future_grants"]
    assert first["content"]["objects"][0]["owner"] == "owner"


def test_adversarial_rows_are_never_copied(facts):
    for key in ("objects", "columns", "grants", "future_grants", "procedures", "migrations"):
        facts.setdefault(key, []).append(
            {
                "name": "PRIVATE_SENTINEL",
                "table_schema": "GOVERNANCE",
                "table_name": "INGESTION_RUNS",
                "column_name": "STATUS",
                "data_type": "PRIVATE_SENTINEL",
                "table_type": "PRIVATE_SENTINEL",
                "table_owner": "PRIVATE_SENTINEL",
                "privilege": "PRIVATE_SENTINEL",
                "grantee_name": "PRIVATE_SENTINEL",
                "version": "PRIVATE_SENTINEL",
                "sha256": "PRIVATE_SENTINEL",
                "body": "PRIVATE_SENTINEL",
                "path": "C:/PRIVATE_SENTINEL",
                "host": "internal.invalid",
            }
        )
    value = make(facts)
    assert "PRIVATE_SENTINEL" not in json.dumps(value)
    assert "internal.invalid" not in json.dumps(value)
    assert value["visibility"] == "partial"


def test_empty_role_filtered_result_never_proves_absence(facts):
    facts["objects"] = []
    result = report(make(facts), now=NOW)
    assert any(
        x["category"] == "unknown" and "empty role-filtered" in x["reason"]
        for x in result["findings"]
    )
    assert not any(x["category"] == "missing" for x in result["findings"])
    assert result["consequential_use"] == "blocked"
    assert result["mutation_started"] is False


def test_visible_inherited_capability_and_renamed_role(facts):
    result = report(make(facts), now=NOW)
    assert not any(
        x["subject"] == "governed_source_run:GOVERNANCE.INGESTION_RUNS:INSERT"
        for x in result["findings"]
    )
    facts["grants"][0]["name"] = "PRIVATE_SENTINEL"
    renamed = report(make(facts), now=NOW)
    assert any(
        x["subject"] == "governed_source_run:GOVERNANCE.INGESTION_RUNS:INSERT"
        and x["category"] == "unknown"
        for x in renamed["findings"]
    )
    assert "PRIVATE_SENTINEL" not in render_report(renamed)


@pytest.mark.parametrize("offset", [timedelta(hours=25), timedelta(seconds=-1)])
def test_stale_or_future_snapshots(facts, offset):
    assert any(x["category"] == "stale" for x in report(make(facts), now=NOW + offset)["findings"])


def test_schema_drift_and_hidden_baseline(facts):
    prior = make(facts)
    facts["columns"][0]["is_nullable"] = "YES"
    result = report(make(facts), now=NOW, baseline=prior)
    assert any(
        x["category"] == "mismatched" and x["subject"] == "columns" for x in result["findings"]
    )
    facts["columns"] = []
    assert any(
        x["category"] == "unknown" and x["subject"] == "columns"
        for x in report(make(facts), now=NOW, baseline=prior)["findings"]
    )


def test_procedure_execution_mode_change(facts):
    scope = load_scope()
    scope["procedures"] = {
        "GOVERNANCE.SP_REVIEW(NUMBER)": {"execute_as": "OWNER", "returns": "BOOLEAN"}
    }
    facts["procedures"] = [
        {
            "signature": "GOVERNANCE.SP_REVIEW(NUMBER)",
            "data_type": "BOOLEAN",
            "execute_as": "CALLER",
            "body": "PRIVATE_SENTINEL",
        }
    ]
    value = make(facts, scope=scope)
    result = report(value, now=NOW, scope=scope)
    assert any(
        x["category"] == "mismatched" and "execution mode" in x["reason"]
        for x in result["findings"]
    )
    assert "PRIVATE_SENTINEL" not in json.dumps(value)


def test_hash_changes_when_visibility_fails(facts):
    first = make(facts)
    facts["unavailable"] = ["grants"]
    assert make(facts)["semantic_hash"] != first["semantic_hash"]


def test_reordered_duplicate_rows_have_identical_hash(facts):
    first = make(facts)
    shuffled = copy.deepcopy(facts)
    for category in ("objects", "columns", "grants", "future_grants"):
        shuffled[category] = list(reversed(shuffled[category] * 2))
    assert make(shuffled)["semantic_hash"] == first["semantic_hash"]


def test_line_ending_equivalent_checksum_and_legacy_unknown(facts):
    import hashlib

    from lyme_gap_atlas_data.migrations import load_migrations

    migration = load_migrations()[0]
    checksum = hashlib.sha256(migration.source.replace("\r\n", "\n").encode()).hexdigest()
    facts["migrations"] = [{"version": migration.version, "sha256": checksum}]
    assert make(facts)["content"]["migrations"][0]["checksum"] == "match"
    facts["migrations"][0]["sha256"] = "PRIVATE_SENTINEL"
    value = make(facts)
    assert value["content"]["migrations"][0]["checksum"] == "unverified_mismatch"
    assert "PRIVATE_SENTINEL" not in json.dumps(value)


def test_missing_migration_only_complete_ledger(facts):
    facts["ledger_complete"] = True
    result = report(make(facts), now=NOW)
    assert any(
        x["category"] == "missing" and x["subject"].endswith(":V071") for x in result["findings"]
    )


@pytest.mark.parametrize("key", ["scope", "content", "unavailable", "generated_at"])
def test_untrusted_snapshot_cannot_leak_values(facts, key):
    value = make(facts)
    value[key] = {"secret": "PRIVATE_SENTINEL"}
    with pytest.raises(ValueError, match="public contract") as error:
        report(value, now=NOW)
    assert "PRIVATE_SENTINEL" not in str(error.value)


def test_cli_rejects_untrusted_input_without_echo(tmp_path):
    path = tmp_path / "hostile.json"
    path.write_text(json.dumps({"scope": "PRIVATE_SENTINEL"}))
    result = CliRunner().invoke(app, ["report", "--snapshot", str(path)])
    assert result.exit_code == 1
    assert "PRIVATE_SENTINEL" not in result.output


def test_stale_and_tampered_baseline_skips_comparison(facts):
    prior = make(facts)
    prior["semantic_hash"] = "0" * 64
    result = report(make(facts), now=NOW, baseline=prior)
    assert any(
        x["subject"] == "baseline" and x["category"] == "mismatched" for x in result["findings"]
    )
    prior = make(facts)
    prior["generated_at"] = (NOW - timedelta(days=2)).isoformat()
    result = report(make(facts), now=NOW, baseline=prior)
    assert any(x["subject"] == "baseline" and x["category"] == "stale" for x in result["findings"])


def test_live_identity_and_stop_on_error():
    calls = []

    def query(sql):
        calls.append(sql)
        if sql.startswith("SELECT CURRENT_ROLE"):
            return [
                {
                    "ROLE": "OH_LYME_DEV_READ",
                    "DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                    "USER_PRESENT": True,
                    "WAREHOUSE_PRESENT": True,
                }
            ]
        raise RuntimeError("PRIVATE_SENTINEL")

    facts = collect_dev(load_scope(), query=query)
    assert len(calls) == 2
    assert facts["unavailable"]
    assert not facts["ledger_complete"]
    assert "PRIVATE_SENTINEL" not in json.dumps(make(facts))
    with pytest.raises(RuntimeError, match="Unexpected audit"):
        collect_dev(load_scope(), query=lambda _: [])


def test_snow_banner_timeout_and_secondary_role_safety():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            [], 0, 'banner\n[{"SAFE": true}]\n', "PRIVATE_SENTINEL"
        ),
    ) as run:
        assert snow_rows("SELECT 1") == [{"SAFE": True}]
        assert "NONE" in run.call_args.args[0]
        assert "--silent" in run.call_args.args[0]
        assert run.call_args.kwargs["timeout"] == 120
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired("snow", 120, output="PRIVATE_SENTINEL"),
    ):
        with pytest.raises(RuntimeError) as error:
            snow_rows("SELECT 1")
        assert "PRIVATE_SENTINEL" not in str(error.value)


def test_schema_file_matches_runtime_and_tamper_report(facts):
    path = Path("docs/contracts/snowflake-snapshots/v1.schema.json")
    assert json.loads(path.read_text()) == snapshot_schema()
    value = make(facts)
    forged_token = "a1" * 32
    value["semantic_hash"] = forged_token
    result = report(value, now=NOW)
    assert any(x["subject"] == "semantic_hash" for x in result["findings"])
    assert forged_token not in json.dumps(result)
    assert result["semantic_hash"] == evidence_hash(value)
    value["semantic_hash"] = evidence_hash(value)
    assert digest(value["scope"]) == value["scope_hash"]
