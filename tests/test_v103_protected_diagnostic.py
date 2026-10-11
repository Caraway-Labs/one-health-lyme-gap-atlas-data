"""The protected V103 diagnostic cannot cross into migration execution."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from lyme_gap_atlas_data.migrations import DEV_DATABASE, migration_plan

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy-dev.yml"
SCRIPT = ROOT / "scripts/diagnose_v103_dev.py"
SPEC = importlib.util.spec_from_file_location("diagnose_v103_dev", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def _fixture_query(
    *,
    visible: bool = True,
    wrong_owner: bool = False,
    wrong_type: bool = False,
    wrong_checksum: bool = False,
    missing_runtime: str | None = None,
    v104_applied: bool = True,
) -> tuple[diagnostic.Query, list[str]]:
    called: list[str] = []
    expected = diagnostic._source_tables()
    applied = [
        {"VERSION": item["version"], "FILENAME": item["filename"], "SHA256": item["sha256"]}
        for item in migration_plan(DEV_DATABASE)
        if item["version"] != "V104" or v104_applied
    ]
    if wrong_checksum:
        next(row for row in applied if row["VERSION"] == "V103")["SHA256"] = "0" * 64

    def query(sql: str) -> list[dict[str, Any]]:
        called.append(sql)
        if "CURRENT_USER()" in sql:
            return [
                {
                    "USER_NAME": diagnostic.MIGRATION_USER,
                    "ROLE_NAME": diagnostic.MIGRATION_ROLE,
                    "DATABASE_NAME": DEV_DATABASE,
                    "WAREHOUSE_NAME": "DEV_WH",
                }
            ]
        if "SCHEMA_MIGRATIONS" in sql:
            return applied
        if "INFORMATION_SCHEMA.SCHEMATA" in sql:
            return [{"SCHEMA_OWNER": "ACCOUNTADMIN", "IS_MANAGED_ACCESS": "NO"}]
        if "SHOW GRANTS ON SCHEMA" in sql:
            return [
                {
                    "grantee_name": diagnostic.MIGRATION_ROLE,
                    "privilege": "CREATE TABLE",
                    "grant_option": "false",
                }
            ]
        if "SHOW ROLES LIKE" in sql:
            return [{"name": diagnostic.RUNTIME_ROLE}]
        for name in diagnostic.TABLE_NAMES:
            if name not in sql:
                continue
            if "SHOW TABLES" in sql:
                return (
                    [
                        {
                            "name": name,
                            "owner": "ACCOUNTADMIN" if wrong_owner else diagnostic.MIGRATION_ROLE,
                            "created_on": "2026-09-26T00:00:00Z",
                            "rows": 0,
                            "bytes": 0,
                            "kind": "TABLE",
                        }
                    ]
                    if visible
                    else []
                )
            if "DESCRIBE TABLE" in sql:
                rows = [
                    {
                        "name": column["name"],
                        "type": column["type"],
                        "kind": "COLUMN",
                        "null?": "Y" if column["nullable"] else "N",
                    }
                    for column in expected[name]["columns"]
                ]
                if wrong_type and name == diagnostic.TABLE_NAMES[0]:
                    rows[0]["type"] = "NUMBER(38,0)"
                return rows
            if "SHOW PRIMARY KEYS" in sql:
                return [
                    {"column_name": column, "key_sequence": ordinal}
                    for ordinal, column in enumerate(expected[name]["primary_key"], 1)
                ]
            if "SHOW GRANTS ON TABLE" in sql:
                grants = [
                    {"grantee_name": diagnostic.RUNTIME_ROLE, "privilege": privilege}
                    for privilege in ("SELECT", "INSERT")
                    if privilege != missing_runtime
                ]
                if name == "GOVERNED_SOURCE_RECORD_REVISIONS":
                    grants.append(
                        {"grantee_name": diagnostic.MIGRATION_ROLE, "privilege": "SELECT"}
                    )
                return grants
        raise AssertionError(f"Unexpected diagnostic query: {sql}")

    return query, called


def test_identity_mismatch_fails_closed_before_metadata_queries() -> None:
    query, called = _fixture_query()
    result = diagnostic.diagnose(query, "OTHER_WH", "reviewed-commit")
    assert result["disposition"] == "IDENTITY_MISMATCH"
    assert result["identity_matches"]["warehouse"] is False
    assert len(called) == 1


def test_wrong_effective_role_fails_closed() -> None:
    regular_query, called = _fixture_query()

    def wrong_role(sql: str) -> list[dict[str, Any]]:
        rows = regular_query(sql)
        if "CURRENT_USER()" in sql:
            rows[0]["ROLE_NAME"] = "ACCOUNTADMIN"
        return rows

    result = diagnostic.diagnose(wrong_role, "DEV_WH", "reviewed-commit")
    assert result["disposition"] == "IDENTITY_MISMATCH"
    assert result["identity_matches"]["role"] is False
    assert len(called) == 1


def test_invisible_tables_are_unknown_not_absent() -> None:
    query, called = _fixture_query(visible=False)
    result = diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")
    assert result["disposition"] == "INSUFFICIENT_VISIBILITY"
    assert result["ledger"]["v103_present"] is True
    assert all(table["exists"] == "UNKNOWN" for table in result["tables"].values())
    assert all(re.match(r"^(SELECT|SHOW|DESCRIBE)\b", sql) for sql in called)
    assert all("ONE_HEALTH_LYME_GAP_ATLAS_PROD" not in sql for sql in called)


@pytest.mark.parametrize("v104_applied", [True, False])
def test_visible_matching_state_ignores_unrelated_later_migration(
    v104_applied: bool,
) -> None:
    query, called = _fixture_query(v104_applied=v104_applied)
    result = diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")
    assert result["disposition"] == "VERIFIED_APPLIED"
    assert result["ledger"]["v103_source_matches"] is True
    assert ("V104" in result["ledger"]["pending_versions"]) is not v104_applied
    assert all(table["definition_matches_v103"] is True for table in result["tables"].values())
    assert all(re.match(r"^(SELECT|SHOW|DESCRIBE)\b", sql) for sql in called)


@pytest.mark.parametrize(
    ("wrong_owner", "wrong_type"),
    [(True, False), (False, True)],
)
def test_ownership_and_definition_mismatch_stop_verification(
    wrong_owner: bool, wrong_type: bool
) -> None:
    query, _ = _fixture_query(wrong_owner=wrong_owner, wrong_type=wrong_type)
    assert diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")["disposition"] == (
        "APPLIED_STATE_MISMATCH"
    )


def test_ledger_checksum_mismatch_takes_precedence_over_live_state() -> None:
    query, called = _fixture_query(wrong_checksum=True, wrong_type=True)
    result = diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")
    assert result["disposition"] == "LEDGER_SOURCE_MISMATCH"
    assert result["ledger"]["v103_source_matches"] is False
    assert all(re.match(r"^(SELECT|SHOW|DESCRIBE)\b", sql) for sql in called)


def test_future_migration_pending_does_not_block_v103_verification() -> None:
    query, _ = _fixture_query()
    plan = migration_plan(DEV_DATABASE)
    future_version = f"V{max(int(item['version'][1:]) for item in plan) + 1:03d}"
    plan.append(
        {
            "version": future_version,
            "filename": f"{future_version}__future.sql",
            "sha256": "1" * 64,
        }
    )
    with patch.object(diagnostic, "migration_plan", return_value=plan):
        result = diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")
    assert result["disposition"] == "VERIFIED_APPLIED"
    assert result["ledger"]["pending_versions"] == [future_version]


@pytest.mark.parametrize("missing_runtime", ["SELECT", "INSERT"])
def test_missing_runtime_grant_fails_verification(missing_runtime: str) -> None:
    query, _ = _fixture_query(missing_runtime=missing_runtime)
    assert diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")["disposition"] == (
        "APPLIED_STATE_MISMATCH"
    )


@pytest.mark.parametrize(
    ("options", "expected_disposition"),
    [
        ({}, "VERIFIED_APPLIED"),
        ({"visible": False}, "INSUFFICIENT_VISIBILITY"),
        ({"wrong_owner": True}, "APPLIED_STATE_MISMATCH"),
        ({"wrong_checksum": True}, "LEDGER_SOURCE_MISMATCH"),
    ],
)
def test_every_diagnostic_disposition_queries_metadata_only(
    options: dict[str, Any], expected_disposition: str
) -> None:
    query, called = _fixture_query(**options)
    assert diagnostic.diagnose(query, "DEV_WH", "reviewed-commit")["disposition"] == (
        expected_disposition
    )
    assert called
    assert all(re.match(r"^(SELECT|SHOW|DESCRIBE)\b", sql) and ";" not in sql for sql in called)
    assert all("ONE_HEALTH_LYME_GAP_ATLAS_PROD" not in sql for sql in called)


def test_snow_cli_guard_rejects_mutation_without_invoking_cli() -> None:
    with patch.object(diagnostic.subprocess, "run") as run:
        for sql in ("GRANT SELECT ON TABLE X TO ROLE Y", "SELECT 1; DELETE FROM X"):
            with pytest.raises(ValueError, match="read-only metadata"):
                diagnostic._snow_query(Path("protected.toml"), sql)
        run.assert_not_called()


def test_workflow_diagnostic_exits_before_migration_commands() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow[True]["workflow_dispatch"]["inputs"]["diagnose_v103_state"]["type"] == "boolean"
    assert set(workflow[True]["workflow_dispatch"]["inputs"]) == {
        "expected_pending_json",
        "diagnose_v103_state",
        "diagnose_legacy_dev_reconciliations",
        "diagnose_v143_cleanup_owner",
        "diagnose_query_id",
        "diagnose_climate_dev",
        "diagnose_climate_views",
        "diagnose_intelligence_dev",
        "register_eid_expedited_dev",
        "feed_preflight_accounting_confirmed",
        "diagnose_january_pair",
        "diagnose_january_runtime_init",
        "january_budget_evidence",
        "reviewed_commit",
    }
    steps = workflow["jobs"]["deploy"]["steps"]
    shell = next(
        step["run"]
        for step in steps
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    branch = shell.split('if [ "$DIAGNOSE_V103_STATE" = "true" ]; then', 1)[1].split("\nfi\n", 1)[0]
    assert 'python scripts/diagnose_v103_dev.py --config-file "$config_file"' in branch
    assert re.search(r"\n\s*exit 0\s*$", branch)
    assert "reconcile-legacy-dev-migrations" not in branch
    assert "apply-migrations" not in branch
    assert "source run" not in branch
    assert "PROD" not in branch
    assert shell.index('if [ "$DIAGNOSE_V103_STATE" = "true" ]; then') < shell.rindex(
        "apply-reviewed-dev-migrations"
    )
    early = shell.split('if [ "$feed_batch" = "true" ]; then', 1)[1].split("exit 0", 1)[0]
    assert 'test "$DIAGNOSE_V103_STATE" != "true"' in early
    assert "QUERY_HISTORY_BY_USER" in shell


def test_january_pair_uses_separate_dev_identities_and_exits_before_migration() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    shell = step["run"]
    pair = shell.split('if [ "$DIAGNOSE_JANUARY_PAIR" = "true" ]; then', 1)[1].split(
        'if [ "$DIAGNOSE_INTELLIGENCE_DEV" = "true" ]; then', 1
    )[0]
    assert shell.index('if [ "$DIAGNOSE_JANUARY_PAIR" = "true" ]; then') < shell.rindex(
        "apply-reviewed-dev-migrations"
    )
    assert 'test "$GITHUB_SHA" = "$REVIEWED_COMMIT"' in pair
    assert 'test "$SNOWFLAKE_ROLE" = OH_LYME_DEV_MIGRATION_DEPLOYER' in pair
    assert 'test "$RUNTIME_ROLE" = OH_LYME_DEV_RUNTIME' in pair
    assert 'test "$DIAGNOSE_LEGACY_DEV_RECONCILIATIONS" != "true"' in pair
    assert pair.index("verify_january_donor_dev.py") < pair.index("JANUARY_DONOR_HANDOFF_SHA256")
    assert "membership.artifact_sha256 == $sha" in pair
    consumer = pair.split('if ! SNOWFLAKE_USER="$RUNTIME_USER"', 1)[1].split(
        'if [ "$DIAGNOSE_LEGACY_DEV_RECONCILIATIONS" = "true" ]; then', 1
    )[0]
    assert consumer.index("| {status, failure, code_sha}'") < consumer.index("exit 2")
    assert consumer.count("| {status, failure, code_sha}'") == 2
    assert consumer.count("exit 2") == 2
    assert consumer.count("REDACTED_RECEIPT_UNAVAILABLE") == 2
    assert 'if ! jq -e --arg sha "$donor_sha" --arg code "$GITHUB_SHA"' in consumer
    assert "annual_manifest_sha256" in pair
    assert 'rm -f "$key_file"' in pair
    assert 'pem_footer="$(tail -n 1 "$key_file")"' not in pair
    assert "printf '%s%s\\n' '-----END ENCRYPTED ' 'PRIVATE KEY-----'" in pair
    assert "printf '%s\\n' \"$RUNTIME_PRIVATE_KEY_B64\" | fold -w 64" in pair
    assert "env -u RUNTIME_USER -u RUNTIME_ROLE" in pair
    assert "trap cleanup EXIT" in pair
    assert "exit 0" in pair


def test_runtime_pem_must_not_reuse_donor_final_line() -> None:
    fold = shutil.which("fold")
    if fold is None:
        pytest.skip("GNU fold is needed to reproduce the protected Linux shell")
    password = b"fixture-password"

    def encrypted_pem() -> bytes:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password),
        )

    donor_lines = encrypted_pem().splitlines()
    runtime_lines = encrypted_pem().splitlines()
    donor_body = b"".join(donor_lines[1:-1])
    folded = subprocess.run(
        [fold, "-w", "64"], input=donor_body, capture_output=True, check=True
    ).stdout
    donor_file = donor_lines[0] + b"\n" + folded + donor_lines[-1] + b"\n"
    copied_final_line = donor_file.splitlines()[-1]
    assert copied_final_line != donor_lines[-1]
    runtime_body = b"\n".join(runtime_lines[1:-1])
    contaminated = runtime_lines[0] + b"\n" + runtime_body + b"\n" + copied_final_line + b"\n"
    with pytest.raises(ValueError):
        serialization.load_pem_private_key(contaminated, password=password)
    correct = runtime_lines[0] + b"\n" + runtime_body + b"\n" + runtime_lines[-1] + b"\n"
    assert serialization.load_pem_private_key(correct, password=password) is not None


def test_january_blocked_receipt_emits_only_sanitized_reason(tmp_path: Path) -> None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for the protected workflow")
    receipt = tmp_path / "january-membership-diagnostic-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "failure": {"stage": "PRE_CONNECTION", "category": "MEMBERSHIP_DONOR_HANDOFF_PATH"},
                "code_sha": "a" * 40,
                "account_binding": "SENSITIVE_ACCOUNT",
                "donor": "SENSITIVE_DONOR",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            jq,
            "-e",
            "-c",
            'select(.status == "BLOCKED" and .failure != null) | {status, failure, code_sha}',
            str(receipt),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "status": "BLOCKED",
        "failure": {"stage": "PRE_CONNECTION", "category": "MEMBERSHIP_DONOR_HANDOFF_PATH"},
        "code_sha": "a" * 40,
    }
    assert "SENSITIVE" not in result.stdout
