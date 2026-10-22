"""No Snowflake connection; current metadata is reported without legacy assumptions."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ownership_report", ROOT / "scripts/report_dev_cleanup_ownership.py"
)
assert SPEC and SPEC.loader
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def identity():
    return [
        {
            "USER_NAME": diagnostic.USER,
            "ROLE_NAME": diagnostic.ROLE,
            "DATABASE_NAME": diagnostic.DATABASE,
            "WAREHOUSE_NAME": diagnostic.WAREHOUSE,
        }
    ]


def grant(privilege, role, option=False):
    return {
        "privilege": privilege,
        "granted_to": "ROLE",
        "grantee_name": role,
        "grant_option": option,
        "private_raw_column": "DO_NOT_PRINT",
    }


@pytest.mark.parametrize(
    "owner",
    [
        "OH_LYME_DEV_MIGRATION_DEPLOYER",
        "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER",
        "UNEXPECTED_EXISTING_OWNER",
    ],
)
def test_reports_current_owners_and_all_visible_grants_without_pre_handoff_expectations(owner):
    calls = []

    def query(sql):
        calls.append(sql)
        if sql == diagnostic.IDENTITY_SQL:
            return identity()
        if sql == diagnostic.OBJECT_SQL[diagnostic.PROCEDURE]:
            return [
                grant("OWNERSHIP", owner, True),
                grant("USAGE", "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP"),
                grant("USAGE", "UNEXPECTED_ROLE"),
            ]
        return [grant("OWNERSHIP", "VIEW_OWNER"), grant("SELECT", owner)]

    result = diagnostic.report(query)
    assert result["status"] == "COMPLETE" and result["writes"] is False
    assert result["objects"][0]["owner"] == owner
    assert result["objects"][1]["owner"] == "VIEW_OWNER"
    assert len(result["objects"][0]["grants"]) == 3
    assert len(result["objects"][1]["grants"]) == 2
    assert "DO_NOT_PRINT" not in json.dumps(result)
    assert set(calls) == diagnostic.ALLOWED_SQL and len(calls) == 3


def test_one_denied_object_does_not_hide_independent_view_readback_or_leak_error():
    def query(sql):
        if sql == diagnostic.IDENTITY_SQL:
            return identity()
        if sql == diagnostic.OBJECT_SQL[diagnostic.PROCEDURE]:
            raise RuntimeError("SECRET_PROVIDER_ERROR")
        return [grant("OWNERSHIP", "VIEW_OWNER")]

    result = diagnostic.report(query)
    assert result["status"] == "PARTIAL"
    assert result["objects"][0]["owner"] is None
    assert result["objects"][1]["owner"] == "VIEW_OWNER"
    assert "SECRET_PROVIDER_ERROR" not in json.dumps(result)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [grant("USAGE", "ROLE_ONLY")],
        [grant("OWNERSHIP", "A"), grant("OWNERSHIP", "B")],
        [grant("USAGE", "A")] * 65,
    ],
)
def test_missing_partial_duplicate_and_oversized_metadata_remains_unknown(rows):
    result = diagnostic.object_report(diagnostic.VIEW, rows)
    assert result["status"] == "UNKNOWN" and result["owner"] is None


def test_wrong_identity_stops_before_object_queries():
    calls = []

    def query(sql):
        calls.append(sql)
        return [{**identity()[0], "ROLE_NAME": "ACCOUNTADMIN"}]

    assert diagnostic.report(query)["reason"] == "IDENTITY_MISMATCH"
    assert calls == [diagnostic.IDENTITY_SQL]


@pytest.mark.parametrize(
    "inputs,ref",
    [
        ({diagnostic.MODE: True, "expected_pending_json": "[]"}, "refs/heads/main"),
        ({diagnostic.MODE: True, "register_eid_expedited_dev": True}, "refs/heads/main"),
        ({diagnostic.MODE: True}, "refs/heads/feature"),
        ({diagnostic.MODE: False}, "refs/heads/main"),
    ],
)
def test_dispatch_rejects_mixed_or_non_main_modes(inputs, ref):
    with pytest.raises(ValueError):
        diagnostic.validate_dispatch(inputs, ref)


def test_dispatch_allows_only_new_read_mode_and_existing_disabled_inputs():
    diagnostic.validate_dispatch(
        {
            diagnostic.MODE: "true",
            "expected_pending_json": "",
            "register_eid_expedited_dev": "false",
        },
        "refs/heads/main",
    )


def test_cli_wrapper_is_allowlisted_bounded_and_sanitizes_provider_output(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout="SECRET", stderr="SECRET")

    monkeypatch.setattr(diagnostic.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="^DEV_OWNERSHIP_QUERY_UNAVAILABLE$"):
        diagnostic.snow_query(Path("fixture-only-config"), diagnostic.IDENTITY_SQL)
    assert calls[0][1]["timeout"] == 15 and calls[0][1]["capture_output"] is True
    with pytest.raises(ValueError, match="ALLOWLISTED"):
        diagnostic.snow_query(Path("fixture-only-config"), "DELETE FROM X")
    assert len(calls) == 1


def test_new_workflow_mode_validates_before_credentials_and_exits_before_legacy_paths():
    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    assert workflow.index('--validate-event "$GITHUB_EVENT_PATH"') < workflow.index(
        'key_file="$RUNNER_TEMP/oh-lyme-dev-pipeline-key.p8"'
    )
    invocation = workflow.index("timeout 70s uv run python scripts/report_dev_cleanup_ownership.py")
    legacy = workflow.index("timeout 120s uv run python scripts/diagnose_v143_cleanup_owner.py")
    assert invocation < workflow.index("exit 0", invocation) < legacy


def test_other_mutating_jobs_are_disabled_for_report_mode():
    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    conditions = [line.strip() for line in workflow.splitlines() if line.startswith("    if:")]
    assert len(conditions) == 4
    assert all("inputs.report_dev_cleanup_ownership != true" in line for line in conditions[1:])
