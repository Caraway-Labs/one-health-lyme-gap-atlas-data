"""Bounded read-only preflight and measurements for Story #446."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data.ingestion import nclimgrid_pilot_measurement as pilot
from lyme_gap_atlas_data.ingestion.types import (
    RunState,
    RunStatus,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)


def _state(status: RunStatus = RunStatus.FAILED) -> RunState:
    from lyme_gap_atlas_data.ingestion.nclimgrid_longitudinal import definition_mapping

    digest = definition_mapping("202501")["source_definition_sha256"]
    acquire = StageCheckpoint(
        Stage.ACQUIRE,
        StageStatus.COMPLETED,
        detail={"source_definition_sha256": digest},
    )
    return RunState("run-1", pilot.RESOURCE_KEY, 1, Tier.B, status, [acquire])


@pytest.mark.parametrize(
    ("identity", "disposition"),
    [
        (
            {
                "user_matches": False,
                "role_matches": True,
                "database_matches": True,
                "warehouse_matches": True,
            },
            "IDENTITY_MISMATCH",
        ),
        (
            {
                "user_matches": True,
                "role_matches": False,
                "database_matches": True,
                "warehouse_matches": True,
            },
            "IDENTITY_MISMATCH",
        ),
        (
            {
                "user_matches": True,
                "role_matches": True,
                "database_matches": False,
                "warehouse_matches": True,
            },
            "IDENTITY_MISMATCH",
        ),
        (
            {
                "user_matches": True,
                "role_matches": True,
                "database_matches": True,
                "warehouse_matches": False,
            },
            "IDENTITY_MISMATCH",
        ),
    ],
)
def test_preflight_fails_closed_on_each_identity_mismatch(monkeypatch, identity, disposition):
    monkeypatch.setattr(pilot, "_identity", lambda: identity)
    assert pilot.preflight()["disposition"] == disposition


def test_v103_checksum_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(
        pilot,
        "_identity",
        lambda: {
            "user_matches": True,
            "role_matches": True,
            "database_matches": True,
            "warehouse_matches": True,
        },
    )
    monkeypatch.setattr(
        pilot, "_migration_state", lambda: {"v103_present": True, "v103_checksum_matches": False}
    )
    assert pilot.preflight()["disposition"] == "V103_MISMATCH"


@pytest.mark.parametrize(
    ("privileges", "ready"),
    [
        ({"SELECT"}, True),
        (set(), False),
        ({"INSERT"}, False),
        ({"SELECT", "INSERT"}, False),
        ({"SELECT", "UPDATE"}, False),
        ({"SELECT", "DELETE"}, False),
        ({"SELECT", "OWNERSHIP"}, False),
    ],
)
def test_runtime_ledger_grant_contract(monkeypatch, privileges, ready):
    columns = ("privilege", "granted_on", "name", "grantee_name")

    class Cursor:
        description = [(column,) for column in columns]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            assert sql == "SHOW GRANTS TO ROLE OH_LYME_DEV_RUNTIME"

        def fetchall(self):
            return [
                (privilege, "TABLE", pilot.LEDGER, pilot.EXPECTED_ROLE) for privilege in privileges
            ]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(pilot, "connect", lambda _settings: Connection())
    result = pilot._runtime_ledger_grants()
    assert result["select_only"] is ready
    assert result["select"] is ("SELECT" in privileges)
    for privilege in ("INSERT", "UPDATE", "DELETE", "OWNERSHIP"):
        assert result[privilege.lower()] is (privilege in privileges)


def test_preflight_rejects_broad_ledger_grants_before_table_reads(monkeypatch):
    monkeypatch.setattr(
        pilot,
        "_identity",
        lambda: {
            "user_matches": True,
            "role_matches": True,
            "database_matches": True,
            "warehouse_matches": True,
        },
    )
    monkeypatch.setattr(
        pilot, "_migration_state", lambda: {"v103_present": True, "v103_checksum_matches": True}
    )
    monkeypatch.setattr(
        pilot,
        "_runtime_ledger_grants",
        lambda: {"select_only": False, "select": True, "insert": True},
    )
    monkeypatch.setattr(
        pilot, "_table_baseline", lambda: pytest.fail("ledger mismatch must stop preflight")
    )
    assert pilot.preflight()["disposition"] == "LEDGER_GRANT_MISMATCH"


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([], "READY_FOR_PILOT"),
        ([_state(RunStatus.SUCCEEDED)], "EXISTING_SUCCESS"),
        ([_state(RunStatus.RUNNING)], "EXISTING_NONTERMINAL_RUN"),
        ([_state(RunStatus.FAILED)], "AMBIGUOUS_RUN_STATE"),
        ([_state(RunStatus.PAUSED)], "AMBIGUOUS_RUN_STATE"),
    ],
)
def test_matching_run_dispositions(monkeypatch, runs, expected):
    monkeypatch.setattr(pilot, "_query_one", lambda *args, **kwargs: (0, 0))
    monkeypatch.setattr(
        pilot, "_table_baseline", lambda: {table: {"row_count": 0} for table in pilot.TABLES}
    )
    monkeypatch.setattr(
        pilot,
        "_identity",
        lambda: {
            "user_matches": True,
            "role_matches": True,
            "database_matches": True,
            "warehouse_matches": True,
        },
    )
    monkeypatch.setattr(
        pilot, "_migration_state", lambda: {"v103_present": True, "v103_checksum_matches": True}
    )
    monkeypatch.setattr(pilot, "_runtime_ledger_grants", lambda: {"select_only": True})

    class Store:
        def load(self, run_id):
            return runs[0] if runs else None

    monkeypatch.setattr(pilot, "SnowflakeCheckpointStore", Store)
    monkeypatch.setattr(
        pilot,
        "_query_all",
        lambda *args, **kwargs: (
            [(item.ingestion_run_id,) for item in runs] if "INGESTION_RUNS" in args[0] else []
        ),
    )
    assert pilot.preflight()["disposition"] == expected


def test_definition_mismatch_is_ambiguous():
    state = _state(RunStatus.SUCCEEDED)
    state.checkpoint(Stage.ACQUIRE).detail["source_definition_sha256"] = "different"
    assert pilot._classify_runs([state])[0] == "AMBIGUOUS_RUN_STATE"


def test_table_visibility_failure_is_reported(monkeypatch):
    monkeypatch.setattr(
        pilot,
        "_identity",
        lambda: {
            "user_matches": True,
            "role_matches": True,
            "database_matches": True,
            "warehouse_matches": True,
        },
    )
    monkeypatch.setattr(
        pilot, "_migration_state", lambda: {"v103_present": True, "v103_checksum_matches": True}
    )
    monkeypatch.setattr(pilot, "_runtime_ledger_grants", lambda: {"select_only": True})
    monkeypatch.setattr(pilot, "_table_baseline", lambda: (_ for _ in ()).throw(PermissionError()))
    result = pilot.preflight()
    assert result["disposition"] == "INSUFFICIENT_VISIBILITY"


def test_run_inspection_validates_exact_run_id_before_store_access(monkeypatch):
    class Store:
        def load(self, _run_id):
            pytest.fail("invalid run ID must not open the store")

    monkeypatch.setattr(pilot, "SnowflakeCheckpointStore", Store)
    with pytest.raises(pilot.MeasurementError):
        pilot.inspect_run("bad;select 1")


def test_inspection_queries_are_bound_to_the_supplied_run(monkeypatch):
    queries = []

    class Store:
        def load(self, run_id):
            return _state(RunStatus.RUNNING)

    def one(sql, params=()):
        queries.append((sql, params))
        return (0, 0, 0, None, None) if "NORMALIZED_PARTITIONS" in sql else (0,)

    def all_rows(sql, params=()):
        queries.append((sql, params))
        return []

    monkeypatch.setattr(pilot, "SnowflakeCheckpointStore", Store)
    monkeypatch.setattr(pilot, "_query_one", one)
    monkeypatch.setattr(pilot, "_query_all", all_rows)
    pilot.inspect_run("run-1")
    assert queries
    assert all(params == ("run-1",) for _sql, params in queries)
    assert all(sql.lstrip().startswith("SELECT") for sql, _params in queries)


def test_ordered_read_uses_only_checkpoint_selects(monkeypatch):
    queries = []

    class Store:
        def load(self, _run_id):
            return _state(RunStatus.SUCCEEDED)

        def iter_partitions(self, _run_id):
            return iter([SimpleNamespace(ordinal=0), SimpleNamespace(ordinal=1)])

    def one(sql, _params=()):
        queries.append(sql)
        return (2,)

    monkeypatch.setattr(pilot, "SnowflakeCheckpointStore", Store)
    monkeypatch.setattr(pilot, "_query_one", one)
    result = pilot.ordered_read("run-1")
    assert result["partition_count"] == 2
    assert result["writes_performed"] is False
    assert queries and all(sql.lstrip().startswith("SELECT") for sql in queries)


def test_timed_report_is_pinned_to_one_month_and_one_run(monkeypatch):
    state = _state(RunStatus.SUCCEEDED)

    class Store:
        def load(self, _run_id):
            return state

        def iter_partitions(self, run_id):
            assert run_id == "run-1"
            return iter(())

    def build(store, *, start, end, county_csv):
        assert [run.ingestion_run_id for run in store.list_runs()] == ["run-1"]
        assert start == end == "202501"
        assert list(store.iter_partitions("run-1")) == []
        county_csv.write_text("month\n202501\n", encoding="utf-8")
        return {
            "start_month": start,
            "end_month": end,
            "captured_month_count": 1,
            "selected_normalized_partition_bytes": 5,
            "months": [{"month": "202501", "normalized_partition_count": 1}],
        }

    monkeypatch.setattr(pilot, "SnowflakeCheckpointStore", Store)
    monkeypatch.setattr(pilot, "build_coverage_report", build)
    assert pilot.time_report("run-1")["report_status"] == "COMPLETED"


def test_cli_exposes_only_semantic_measurement_arguments():
    from lyme_gap_atlas_data.cli import source_nclimgrid_pilot_measure

    assert set(inspect.signature(source_nclimgrid_pilot_measure).parameters) == {
        "action",
        "run_id",
    }


def test_benchmark_history_is_bounded_to_run_and_reports_transport_residue(monkeypatch):
    start = datetime(2026, 9, 28, 2, 59, tzinfo=UTC)
    end = start + timedelta(minutes=26)
    statements = []
    rows = [
        ("before", "SELECT", "SELECT 1", start - timedelta(seconds=1), start),
        (
            "merge",
            "MERGE",
            "MERGE INTO GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS",
            start,
            start + timedelta(seconds=2),
        ),
        (
            "put",
            "PUT",
            "PUT file://transport",
            start + timedelta(seconds=3),
            start + timedelta(seconds=4),
        ),
        (
            "remove",
            "REMOVE",
            "REMOVE @GOVERNANCE.INGESTION_BULK_STAGE",
            start + timedelta(seconds=5),
            start + timedelta(seconds=6),
        ),
        ("after", "SELECT", "SELECT 2", end + timedelta(seconds=1), end + timedelta(seconds=2)),
    ]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            statements.append(sql)

        def fetchall(self):
            return rows if len(statements) == 1 else []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(pilot, "_run", lambda _run_id: _state(RunStatus.SUCCEEDED))
    monkeypatch.setattr(
        pilot,
        "_identity",
        lambda: dict.fromkeys(
            ("user_matches", "role_matches", "database_matches", "warehouse_matches"), True
        ),
    )

    def run_window(sql, params):
        assert "status='COMPLETED'" in sql
        assert params == ("run-1",)
        return start, end

    monkeypatch.setattr(pilot, "_query_one", run_window)
    monkeypatch.setattr(pilot, "connect", lambda _settings: Connection())
    result = pilot.benchmark_history("run-1")
    assert result["query_count"] == 3
    assert result["query_type_counts"] == {"MERGE": 1, "PUT": 1, "REMOVE": 1}
    assert result["path_spans"]["checkpoint"]["query_count"] == 1
    assert result["transport_object_count"] == 0
    assert statements[0].startswith("SELECT ")
    assert statements[1] == "LIST @GOVERNANCE.INGESTION_BULK_STAGE/run-1/"


def test_measurement_workflow_is_read_only_and_confined_to_dev():
    workflow = Path(".github/workflows/run-ingestion.yml").read_text(encoding="utf-8")
    assert "nclimgrid-pilot-measurement" in workflow
    assert "inputs.operation == 'nclimgrid-pilot-measurement' && 'dev'" in workflow
    assert (
        "inputs.operation != 'nclimgrid-pilot-measurement' && "
        "inputs.operation != 'january-source-registration' && secrets.SPACES_BUCKET"
    ) in workflow
    assert 'test "${{ inputs.recapture }}" = "false"' in workflow
    assert 'test "${{ inputs.publish }}" = "false"' in workflow
    assert (
        'test "$SOURCE_DEFINITION" = "config/sources/noaa_nclimgrid_daily_202501.yml"' in workflow
    )
    assert "MEASUREMENT_RUN_ID: ${{ inputs.run_id }}" in workflow
    block = workflow.rsplit(
        'if [ "${{ inputs.operation }}" = "nclimgrid-pilot-measurement" ]; then', 1
    )[1]
    block = block.split('elif [ "${{ inputs.operation }}" = "run" ]; then', 1)[0]
    assert "atlas-data source nclimgrid-pilot-measure" in block
    assert "atlas-data source run" not in block
    assert "atlas-data source nclimgrid-batch" not in block
    assert "atlas-data runs resume" not in block
    assert "apply-migrations" not in block
