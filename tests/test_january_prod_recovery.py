"""Offline recovery invariants; no simulated result counts as PROD acceptance."""

import runpy
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import january_prod_recovery as recovery
from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.ingestion.artifact_replay import ArtifactMember
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import (
    FailureCategory,
    RunState,
    RunStatus,
    StageCheckpoint,
    StageStatus,
    Tier,
)


@pytest.fixture
def admitted(monkeypatch):
    for key, value in {
        "JANUARY_NORMALIZE_RECOVERY": "true",
        "JANUARY_BULK_REPAIR_VERIFIED": "true",
        "TOPX_ENV": "prod",
        "ENABLE_PRODUCTION_EXECUTION": "true",
        "ATLAS_JANUARY_PROD_SESSION": "true",
    }.items():
        monkeypatch.setenv(key, value)
    definition = load_source_definition(Path("config/sources/noaa_nclimgrid_daily_202501_prod.yml"))
    stages = [
        StageCheckpoint(
            stage=s,
            status=StageStatus.COMPLETED
            if i < 2
            else StageStatus.FAILED
            if i == 2
            else StageStatus.PENDING,
            attempt_count=1 if i < 3 else 0,
        )
        for i, s in enumerate(definition.stages)
    ]
    stages[0].detail = {
        "artifacts": [
            ArtifactMember(
                recovery.PLANNED_RUN,
                name,
                "primary" if i == 0 else "reference",
                name,
                "https://fixture.invalid/" + name,
                "application/octet-stream",
                digest,
                size,
            ).to_dict()
            for i, (name, digest, size) in enumerate(
                [("noaa", recovery.NOAA_SHA, 61013299), ("tiger", recovery.TIGER_SHA, 83989800)]
            )
        ]
    }
    stages[2].redacted_diagnostic_code = "PROGRAMMINGERROR"
    stages[2].failure_category = FailureCategory.WAREHOUSE
    stages[2].next_action = "resume:NORMALIZE"
    state = RunState(
        recovery.PLANNED_RUN,
        definition.resource_key,
        definition.definition_version,
        Tier.C,
        RunStatus.FAILED,
        stages,
        "resume:NORMALIZE",
    )
    return state, definition


def test_exact_failed_run_only(admitted):
    recovery.require_recovery_state(*admitted)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ingestion_run_id", "other"),
        ("status", RunStatus.RUNNING),
        ("dry_run", True),
        ("tier", Tier.B),
        ("next_action", "resume:LOAD"),
        ("source_definition_version", 999),
    ],
)
def test_recovery_rejects_scope_changes(admitted, field, value):
    state, definition = admitted
    setattr(state, field, value)
    with pytest.raises(PermissionError):
        recovery.require_recovery_state(state, definition)


@pytest.mark.parametrize("index", range(6))
def test_no_second_attempt_or_upstream_replay(admitted, index):
    state, definition = admitted
    state.stages[index].attempt_count += 1
    with pytest.raises(PermissionError):
        recovery.require_recovery_state(state, definition)


@pytest.mark.parametrize("index", range(6))
def test_partial_or_completed_stage_cannot_resume(admitted, index):
    state, definition = admitted
    state.stages[index].status = StageStatus.RUNNING
    with pytest.raises(PermissionError):
        recovery.require_recovery_state(state, definition)


def test_opt_in_is_required(admitted, monkeypatch):
    monkeypatch.delenv("JANUARY_NORMALIZE_RECOVERY")
    with pytest.raises(PermissionError):
        recovery.require_recovery_state(*admitted)


def test_changed_artifact_is_not_recoverable(admitted):
    state, definition = admitted
    state.stages[0].detail["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(PermissionError):
        recovery.require_recovery_state(state, definition)


def stage_cursor():
    cursor = Mock()
    results = [
        [("INGESTION_BULK_STAGE", "INTERNAL", "")],
        [
            ("STAGE_FILE_FORMAT", p, "String", v, None)
            for p, v in [("TYPE", "JSON"), ("COMPRESSION", "AUTO"), ("MULTI_LINE", "false")]
        ],
        [(p, "OH_LYME_PROD_RUNTIME", "STAGE", "ROLE") for p in ("READ", "WRITE")],
    ]
    cursor.description = [("name",), ("type",), ("url",)]

    def execute(sql):
        if sql.startswith("SHOW GRANTS"):
            cursor.description = [
                (c,) for c in ("privilege", "grantee_name", "granted_on", "granted_to")
            ]

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = results
    return cursor, results


def test_runtime_stage_checks_are_read_only():
    cursor, _ = stage_cursor()
    recovery.require_runtime_stage(cursor)
    assert all(c.args[0].startswith(("SHOW ", "DESC ")) for c in cursor.execute.call_args_list)


@pytest.mark.parametrize("which", range(3))
def test_missing_stage_configuration_or_grant_fails_closed(which):
    cursor, results = stage_cursor()
    results[which].pop()
    with pytest.raises(PermissionError):
        recovery.require_runtime_stage(cursor)


@pytest.mark.parametrize("output_index", range(7))
def test_any_partial_output_prevents_state_mutation(admitted, monkeypatch, output_index):
    monkeypatch.setattr(recovery, "verify_execution_resource", lambda *args: None)
    monkeypatch.setattr(recovery, "require_runtime_stage", lambda *args: None)
    cursor = Mock()
    cursor.fetchall.side_effect = [
        [("noaa_nclimgrid_daily_202501", 1), ("census_tiger_2025_us_county_analysis", 1)],
    ]
    cursor.fetchone.side_effect = [(0,)] * output_index + [(1,)]
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(recovery, "connect", lambda *args: nullcontext(connection))
    monkeypatch.setattr(recovery, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(
        recovery,
        "approved_capture_binding",
        lambda *a, **kw: {
            "noaa": {},
            "tiger": {
                "source_version_id": recovery.TIGER_VERSION,
                "decision_id": recovery.TIGER_DECISION,
            },
        },
    )
    original = deepcopy(admitted[0])
    with pytest.raises(PermissionError, match="OUTPUT_EXISTS"):
        recovery.verified_recovery_definition(*admitted)
    assert admitted[0] == original
    assert all(c.args[0].startswith("SELECT") for c in cursor.execute.call_args_list)


def test_forward_migration_preserves_v117_and_prod_scope():
    canonical = {m.version: m for m in migrations.load_migrations()}
    assert (
        canonical["V117"].sha256
        == "97dc205df634efdefa5dc561b36481068cfaa09dc6391d2acdc8cdf474add5e0"
    )
    migration = canonical["V153"]
    assert "V153" in migrations.PROD_ONLY_MIGRATION_VERSIONS
    assert (
        migrations.migration_execution_role(migration, migrations.PROD_DATABASE)
        == "OH_LYME_PROD_OWNER"
    )
    assert all(word not in migration.source for word in ("REPLACE", "DROP", "DELETE", "TRUNCATE"))
    assert "SNOWFLAKE_SSE" in migration.source and "OH_LYME_PROD_RUNTIME" in migration.source


def test_repair_runner_applies_only_v153(monkeypatch):
    canonical = {m.version: m for m in migrations.load_migrations()}
    plan = [canonical[k] for k in ("V150", "V151", "V152", "V153")]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *args: set())
    cursor = Mock()
    cursor.fetchall.side_effect = [[(k, canonical[k].sha256) for k in ("V151", "V152")], []]
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *a, **kw: nullcontext(connection))
    pending = [
        {
            "version": canonical[k].version,
            "filename": canonical[k].filename,
            "sha256": canonical[k].sha256,
        }
        for k in ("V150", "V153")
    ]
    assert migrations.apply_migrations(
        Mock(), migrations.PROD_DATABASE, expected_pending=pending, january_bulk_recovery_only=True
    ) == ["V153"]
    assert connection.execute_string.call_count == 1
    assert "SNOWFLAKE_SSE" in connection.execute_string.call_args.args[0]


def test_recovery_does_not_enable_implicit_january_resume(admitted, monkeypatch):
    from lyme_gap_atlas_data.ingestion.checkpoints import InMemoryCheckpointStore
    from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator

    state, definition = admitted
    store = InMemoryCheckpointStore()
    store.save(state)
    monkeypatch.delenv("JANUARY_NORMALIZE_RECOVERY")
    orchestrator = IngestionOrchestrator(store=store)
    with pytest.raises(PermissionError):
        orchestrator.resume(state.ingestion_run_id, definition=definition)
    assert store.load(state.ingestion_run_id) == state


def test_recovery_replays_members_before_any_state_write(admitted, monkeypatch):
    from lyme_gap_atlas_data.ingestion.checkpoints import SnowflakeCheckpointStore
    from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator

    state, definition = admitted
    store = Mock(spec=SnowflakeCheckpointStore)
    store.load.return_value = state
    monkeypatch.setattr(recovery, "verified_recovery_definition", lambda *args: definition)
    orchestrator = IngestionOrchestrator(store=store)
    monkeypatch.setattr(orchestrator, "_adapter", lambda *args: Mock())
    replay = Mock(side_effect=ValueError("retained checksum mismatch"))
    monkeypatch.setattr(orchestrator, "_restore_member_payload", replay)
    with pytest.raises(ValueError, match="checksum mismatch"):
        orchestrator.resume(state.ingestion_run_id, definition=definition)
    store.save.assert_not_called()


def test_existing_workflows_keep_mutually_exclusive_recovery_scope():
    source = Path(".github/workflows/run-prod-ingestion.yml").read_text()
    assert 'test "${{ inputs.operation }}" = resume' in source
    assert "timeout --signal=INT --kill-after=15s 1800s" in source
    assert "JANUARY_NORMALIZE_RECOVERY: ${{ inputs.january_normalize_recovery }}" in source
    promote = Path(".github/workflows/promote-prod.yml").read_text()
    assert "january_bulk_recovery_only != true" in promote
    assert "guard_ne january_climate_and_bulk_recovery true:true" in promote


@pytest.mark.parametrize("versions", [[], ["V153"], ["V150", "V151", "V153"]])
def test_repair_rejects_incomplete_or_widened_pending_before_connect(monkeypatch, versions):
    connection = Mock()
    monkeypatch.setattr(migrations, "connect", connection)
    canonical = {m.version: m for m in migrations.load_migrations()}
    pending = [
        {"version": key, "filename": canonical[key].filename, "sha256": canonical[key].sha256}
        for key in versions
    ]
    with pytest.raises(PermissionError):
        migrations.apply_migrations(
            Mock(),
            migrations.PROD_DATABASE,
            expected_pending=pending,
            january_bulk_recovery_only=True,
        )
    connection.assert_not_called()


def test_successful_recovery_replays_before_state_changes(admitted, monkeypatch):
    from lyme_gap_atlas_data.ingestion.checkpoints import SnowflakeCheckpointStore
    from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator

    state, definition = admitted
    store = Mock(spec=SnowflakeCheckpointStore)
    store.load.return_value = state
    monkeypatch.setattr(recovery, "verified_recovery_definition", lambda *args: definition)
    orchestrator = IngestionOrchestrator(store=store)
    monkeypatch.setattr(orchestrator, "_adapter", lambda *args: Mock())
    payload = object()

    def replay(*args):
        store.save.assert_not_called()
        assert state.status is RunStatus.FAILED
        return payload

    monkeypatch.setattr(orchestrator, "_restore_member_payload", replay)

    def execute(*args, **kwargs):
        assert orchestrator._payloads[state.ingestion_run_id] is payload
        assert state.stages[0].attempt_count == state.stages[1].attempt_count == 1
        assert state.status is RunStatus.RUNNING
        return state

    monkeypatch.setattr(orchestrator, "_execute", execute)
    assert orchestrator.resume(state.ingestion_run_id, definition=definition) is state
    store.save.assert_called_once()


@pytest.fixture
def deployment_receipt():
    verifier = runpy.run_path("scripts/verify_january_bulk_repair_receipt.py")
    run = {
        "repository": {"full_name": verifier["REPOSITORY"]},
        "path": ".github/workflows/promote-prod.yml",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "conclusion": "success",
    }
    jobs = {"jobs": [{"name": verifier["JOB"], "conclusion": "success"}]}
    line = (
        verifier["JOB"] + "\tApply only reviewed climate migrations\t2026-10-15Z "
        '{"applied": ["V153"], "excluded": ["V150"]}'
    )
    return verifier["require_receipt"], run, jobs, line


def test_canonical_actions_receipt_binds_exact_reviewed_migration(deployment_receipt):
    verify, run, jobs, line = deployment_receipt
    verify(run, jobs, line, "a" * 40)


@pytest.mark.parametrize(
    "key,value",
    [
        ("path", ".github/workflows/run-prod-ingestion.yml"),
        ("head_sha", "b" * 40),
        ("head_branch", "feature"),
        ("event", "push"),
        ("conclusion", "failure"),
        ("repository", {"full_name": "other/repository"}),
    ],
)
def test_unrelated_or_failed_deployment_is_rejected(deployment_receipt, key, value):
    verify, run, jobs, line = deployment_receipt
    run[key] = value
    with pytest.raises(ValueError):
        verify(run, jobs, line, "a" * 40)


@pytest.mark.parametrize("change", ["empty", "other_migration", "duplicate", "wrong_job"])
def test_missing_or_forged_migration_receipt_is_rejected(deployment_receipt, change):
    verify, run, jobs, line = deployment_receipt
    line = {
        "empty": "",
        "other_migration": line.replace("V153", "V152"),
        "duplicate": line + "\n" + line,
        "wrong_job": line.replace("Protected January", "Other January"),
    }[change]
    with pytest.raises(ValueError):
        verify(run, jobs, line, "a" * 40)


def test_no_migration_proof_means_no_resume(admitted, monkeypatch):
    monkeypatch.delenv("JANUARY_BULK_REPAIR_VERIFIED")
    with pytest.raises(PermissionError):
        recovery.require_recovery_state(*admitted)


@pytest.mark.parametrize("versions", [[], ["V154"], ["V150", "V153", "V154"]])
def test_point_optimization_rejects_unscoped_pending_before_connect(monkeypatch, versions):
    connection = Mock()
    monkeypatch.setattr(migrations, "connect", connection)
    canonical = {m.version: m for m in migrations.load_migrations()}
    pending = [
        {"version": k, "filename": canonical[k].filename, "sha256": canonical[k].sha256}
        for k in versions
    ]
    with pytest.raises(PermissionError):
        migrations.apply_migrations(
            Mock(),
            migrations.PROD_DATABASE,
            expected_pending=pending,
            january_point_query_only=True,
        )
    connection.assert_not_called()


def test_point_optimization_applies_v154_and_preserves_v150(monkeypatch):
    canonical = {m.version: m for m in migrations.load_migrations()}
    plan = [canonical[k] for k in ("V150", "V151", "V152", "V153", "V154")]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *args: {})
    cursor = Mock()
    cursor.fetchall.return_value = [(k, canonical[k].sha256) for k in ("V151", "V152", "V153")]
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *a, **kw: nullcontext(connection))
    pending = [
        {"version": k, "filename": canonical[k].filename, "sha256": canonical[k].sha256}
        for k in ("V150", "V154")
    ]
    assert migrations.apply_migrations(
        Mock(), migrations.PROD_DATABASE, expected_pending=pending, january_point_query_only=True
    ) == ["V154"]
    assert connection.execute_string.call_count == 1
    assert "ARRAY_CONTAINS" in connection.execute_string.call_args.args[0]


def test_point_workflow_does_not_promote_images_or_other_migrations():
    workflow = Path(".github/workflows/promote-prod.yml").read_text()
    assert "inputs.january_point_query_only != true" in workflow
    assert "JANUARY_POINT_QUERY_ONLY: ${{ inputs.january_point_query_only }}" in workflow
    assert "january_point_query_only }}' == true" in workflow
    assert "guard_eq january_point_query_scopes false:false" in workflow
    runner = Path("scripts/apply_january_prod_migrations.py").read_text()
    assert 'january_point_query_only=os.environ.get("JANUARY_POINT_QUERY_ONLY") == "true"' in runner


@pytest.mark.parametrize("fault", ["checksum", "missing-prior", "mixed", "dev", "extra-pending"])
def test_point_optimization_integrity_failure_never_executes_ddl(monkeypatch, fault):
    canonical = {m.version: m for m in migrations.load_migrations()}
    plan = [canonical[k] for k in ("V150", "V151", "V152", "V153", "V154")]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *args: {})
    cursor = Mock()
    applied = [
        (k, canonical[k].sha256)
        for k in ("V151", "V152", "V153")
        if fault != "missing-prior" or k != "V153"
    ]
    cursor.fetchall.return_value = applied
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *a, **kw: nullcontext(connection))
    pending = [
        {"version": k, "filename": canonical[k].filename, "sha256": canonical[k].sha256}
        for k in ("V150", "V154")
    ]
    if fault == "checksum":
        pending[1]["sha256"] = "0" * 64
    if fault == "extra-pending":
        pending.append(
            {
                "version": "V153",
                "filename": canonical["V153"].filename,
                "sha256": canonical["V153"].sha256,
            }
        )
    with pytest.raises((PermissionError, ValueError)):
        migrations.apply_migrations(
            Mock(),
            migrations.DEV_DATABASE if fault == "dev" else migrations.PROD_DATABASE,
            expected_pending=pending,
            january_point_query_only=True,
            january_climate_only=fault == "mixed",
        )
    connection.execute_string.assert_not_called()
