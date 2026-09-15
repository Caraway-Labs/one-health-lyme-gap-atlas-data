"""Phase 2 coverage for live adapters, durable resume, and generic effects."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from openpyxl import Workbook

from lyme_gap_atlas_data.ingestion import (
    AdapterKind,
    FileCheckpointStore,
    IngestionOrchestrator,
    InMemoryCheckpointStore,
    SnowflakeCheckpointStore,
    SnowflakeStageEffects,
    Stage,
    StageStatus,
    Tier,
    load_source_definition,
)
from lyme_gap_atlas_data.ingestion.adapters import (
    AcquisitionError,
    HttpXlsxAdapter,
    SocrataAdapter,
)
from lyme_gap_atlas_data.ingestion.runtime import (
    _UPSERT_BATCH_SIZE,
    _UPSERT_CONFORMED_SQL,
    _UPSERT_RAW_SQL,
    _UPSERT_STAGING_SQL,
    _lineage_rows,
)
from lyme_gap_atlas_data.ingestion.source_definition import source_definition_from_mapping
from lyme_gap_atlas_data.ingestion.types import RunState, RunStatus, StageCheckpoint

REPO = Path(__file__).resolve().parents[1]
X5J9 = REPO / "config" / "sources" / "cdc_x5j9_wybp.yml"
X5J9_FIXTURES = REPO / "tests" / "fixtures" / "sources" / "cdc_lyme_x5j9_wybp"
TICK = REPO / "config" / "sources" / "cdc_tick_ixodes_county_status.yml"


def _socrata_definition(**overrides: Any):
    document: dict[str, Any] = {
        "resource_key": "example_socrata",
        "source_id": "example",
        "dataset_id": "example-dataset",
        "definition_version": 1,
        "adapter_kind": AdapterKind.SOCRATA.value,
        "endpoint_template": "https://example.test/resource.json",
        "metadata_endpoint_template": "https://example.test/api/views/example",
        "deterministic_order_clause": ":id ASC",
        "incremental_strategy": "FULL_REFRESH",
        "geography_semantics": "COUNTY",
        "temporal_semantics": "YEAR",
        "quality_rules": [{"rule_id": "required_geography", "severity": "BLOCKING"}],
        "page_size": 2,
    }
    document.update(overrides)
    return source_definition_from_mapping(document)


def _xlsx_definition(**overrides: Any):
    document: dict[str, Any] = {
        "resource_key": "example_xlsx",
        "source_id": "example",
        "dataset_id": "example-workbook",
        "definition_version": 1,
        "adapter_kind": AdapterKind.HTTP_XLSX.value,
        "endpoint_template": "https://example.test/example.xlsx",
        "deterministic_order_clause": "FIPSCode ASC",
        "incremental_strategy": "SNAPSHOT_DIFF",
        "geography_semantics": "COUNTY",
        "temporal_semantics": "AS_OF_DATE",
        "workbook_sheet": "Data",
        "header_row": 1,
        "maximum_workbook_bytes": 1_048_576,
        "required_columns": ["FIPSCode", "State"],
    }
    document.update(overrides)
    return source_definition_from_mapping(document)


def test_socrata_live_acquisition_is_ordered_paginated_and_bounded() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/api/views/example"):
            return httpx.Response(200, json={"id": "example"}, request=request)
        offset = int(request.url.params["$offset"])
        page = (
            [{":id": "1", "fips": "08001"}, {":id": "2", "fips": "08003"}]
            if offset == 0
            else [{":id": "3", "fips": "08005"}]
        )
        return httpx.Response(200, json=page, request=request)

    definition = _socrata_definition(maximum_rows=3)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SocrataAdapter(client=client, sleep_fn=lambda _seconds: None).acquire(definition)

    assert result.detail == {
        "source": "live",
        "page_count": 2,
        "request_order": ":id ASC",
    }
    assert result.row_count == 3
    assert len(result.payload["sample"]) == 3
    data_requests = [request for request in requests if "/resource.json" in str(request.url)]
    assert [request.url.params["$limit"] for request in data_requests] == ["2", "1"]
    assert all(request.url.params["$order"] == ":id ASC" for request in data_requests)
    assert result.raw_payload is not None


def test_socrata_live_acquisition_retries_provider_failures() -> None:
    attempts = 0
    sleeps: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json=[{":id": "1", "fips": "08001"}], request=request)

    definition = _socrata_definition()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SocrataAdapter(client=client, sleep_fn=sleeps.append, max_retries=2).acquire(
            definition
        )

    assert result.row_count == 1
    assert attempts == 3  # metadata plus the retried data request
    assert sleeps == [1]


def test_socrata_live_acquisition_classifies_non_retryable_provider_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    definition = _socrata_definition()
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(AcquisitionError, match="rejected") as error,
    ):
        SocrataAdapter(client=client).acquire(definition)
    assert error.value.code == "HTTP_404"


def test_http_xlsx_live_acquisition_reads_declared_sheet_and_headers() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["FIPSCode", "State"])
    sheet.append(["08001", "CO"])
    sheet.append(["08003", "CO"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    body = buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
            request=request,
        )

    definition = _xlsx_definition(maximum_workbook_bytes=len(body))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = HttpXlsxAdapter(client=client).acquire(definition)

    assert result.row_count == 2
    assert result.payload["headers"] == ["FIPSCode", "State"]
    assert result.payload["sample"][0] == {"FIPSCode": "08001", "State": "CO"}
    assert result.raw_payload == body


def test_simplified_resume_uses_payload_persisted_by_a_previous_process(tmp_path: Path) -> None:
    definition = load_source_definition(X5J9)
    store_root = tmp_path / "runs"
    first = IngestionOrchestrator(store=FileCheckpointStore(store_root), fixture_dir=X5J9_FIXTURES)
    failed = first.run(definition, tier=Tier.A, fail_after_stage=Stage.ACQUIRE.value)
    acquire_attempts = failed.checkpoint(Stage.ACQUIRE).attempt_count  # type: ignore[union-attr]

    second = IngestionOrchestrator(store=FileCheckpointStore(store_root), fixture_dir=X5J9_FIXTURES)
    resumed = second.resume(failed.ingestion_run_id, definition=definition)

    assert resumed.status.value == "SUCCEEDED"
    assert resumed.checkpoint(Stage.ACQUIRE).attempt_count == acquire_attempts  # type: ignore[union-attr]
    assert resumed.checkpoint(Stage.VALIDATE).status is StageStatus.COMPLETED  # type: ignore[union-attr]


def test_dry_run_does_not_fail_quality_without_records() -> None:
    definition = load_source_definition(X5J9)
    state = IngestionOrchestrator(store=InMemoryCheckpointStore()).run(
        definition, tier=Tier.B, dry_run=True
    )
    assert state.status.value == "SUCCEEDED"
    quality = state.checkpoint(Stage.QUALITY)
    assert quality is not None and quality.detail["planned"] is True


def test_evidence_only_tick_definition_is_rejected_for_live_tiers() -> None:
    definition = load_source_definition(TICK)
    with pytest.raises(PermissionError, match="Evidence-only"):
        IngestionOrchestrator(store=InMemoryCheckpointStore()).run(
            definition, tier=Tier.B, dry_run=False
        )


def test_phase2_generic_migration_and_workflow_preserve_the_governed_boundary() -> None:
    migration = (
        REPO / "migrations" / "V069__generic_ingestion_records_and_publications.sql"
    ).read_text(encoding="utf-8")
    workflow = (REPO / ".github" / "workflows" / "run-ingestion.yml").read_text(encoding="utf-8")
    assert "RAW.GOVERNED_SOURCE_RECORDS" in migration
    assert "STAGING.GOVERNED_SOURCE_RECORDS" in migration
    assert "CONFORMED.GOVERNED_SOURCE_RECORDS" in migration
    assert "INGESTION_PUBLICATIONS" in migration
    assert "OH_LYME_{{ ENV }}_PIPELINE_RUNTIME" in migration
    assert "cdc_lyme" not in migration.lower()
    assert "--dry-run" not in workflow
    assert "environment_name" in workflow
    assert "Tier C execution belongs to the protected" in workflow
    assert "BEGIN ENCRYPTED PRIVATE KEY" in workflow
    assert 'export SNOWFLAKE_PRIVATE_KEY_B64="$(base64 --wrap=0 "$key_file")"' in workflow
    assert "The secret stores the PEM body" in workflow
    assert "trap 'rm -f \"$key_file\"' EXIT" in workflow
    assert "SNOWFLAKE_RUNTIME_USER" in workflow
    assert "SNOWFLAKE_RUNTIME_ROLE" in workflow
    assert "SNOWFLAKE_RUNTIME_PRIVATE_KEY_B64" in workflow
    assert "SNOWFLAKE_RUNTIME_PRIVATE_KEY_PASSPHRASE" in workflow
    assert "OH_LYME_{environment}_PIPELINE_SVC" in workflow
    assert "OH_LYME_{environment}_PIPELINE_RUNTIME" in workflow
    assert "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE()" in workflow
    assert "secrets.SNOWFLAKE_USER" not in workflow
    assert "secrets.SNOWFLAKE_ROLE" not in workflow
    assert "required_var in \\" in workflow
    assert "Missing required generic-ingestion configuration: $required_var" in workflow


class _RecordingEffects:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def register_artifact(self, _definition: Any, _state: Any, acquired: Any) -> dict[str, Any]:
        self.calls.append("register_artifact")
        return {"artifact_id": "test-artifact", "artifact_sha256": acquired.artifact_sha256}

    def materialize_normalized(
        self, _definition: Any, _state: Any, _records: Any
    ) -> dict[str, Any]:
        self.calls.append("materialize_normalized")
        return {"wrote": True}

    def load(self, _definition: Any, _state: Any, _records: Any) -> dict[str, Any]:
        self.calls.append("load")
        return {"wrote": True}

    def quality(self, _definition: Any, _state: Any, _records: Any) -> dict[str, Any]:
        self.calls.append("quality")
        return {"status": "PASSED"}

    def publish(self, _definition: Any, _state: Any, _records: Any) -> dict[str, Any]:
        self.calls.append("publish")
        return {"status": "STAGED"}


def test_orchestrator_calls_each_generic_stage_effect() -> None:
    effects = _RecordingEffects()
    definition = load_source_definition(X5J9)
    state = IngestionOrchestrator(
        store=InMemoryCheckpointStore(), fixture_dir=X5J9_FIXTURES, effects=effects
    ).run(definition, tier=Tier.A)
    assert state.status.value == "SUCCEEDED"
    assert effects.calls == [
        "register_artifact",
        "materialize_normalized",
        "load",
        "quality",
        "publish",
    ]


class _FakeCursor:
    def __init__(
        self, *, run: tuple[Any, ...] | None = None, rows: list[tuple[Any, ...]] | None = None
    ):
        self.run = run
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        self.executemany_calls.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.run

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor):
        self.fake_cursor = cursor
        self.committed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def autocommit(self, _enabled: bool) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.committed = True


def test_snowflake_checkpoint_store_maps_completed_and_preserves_timestamps() -> None:
    started = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    completed = datetime(2026, 9, 13, 12, 1, tzinfo=UTC)
    cursor = _FakeCursor(
        run=("run-1", "cdc_lyme_x5j9_wybp", "B", "COMPLETED"),
        rows=[
            (
                2,
                "ACQUIRE",
                "COMPLETED",
                1,
                "artifact-1",
                "a" * 64,
                "socrata_normalize_v1",
                None,
                None,
                None,
                {"row_count": 1},
                started,
                completed,
            )
        ],
    )
    connection = _FakeConnection(cursor)
    state = SnowflakeCheckpointStore(connection_factory=lambda: connection).load("run-1")

    assert state is not None
    assert state.status.value == "SUCCEEDED"
    assert state.source_definition_version == 2
    assert state.stages[0].started_at == str(started)
    assert state.stages[0].completed_at == str(completed)


def test_snowflake_checkpoint_store_writes_completed_for_succeeded_state() -> None:
    cursor = _FakeCursor()
    connection = _FakeConnection(cursor)
    state = RunState(
        ingestion_run_id="run-1",
        resource_key="example",
        source_definition_version=1,
        tier=Tier.B,
        status=RunStatus.SUCCEEDED,
        stages=[StageCheckpoint(stage=Stage.ACQUIRE, status=StageStatus.COMPLETED)],
    )
    SnowflakeCheckpointStore(connection_factory=lambda: connection).save(state)

    run_params = cursor.executed[0][1]
    assert run_params is not None and run_params[3] == "COMPLETED"
    assert connection.committed is True


class _FakeSpaces:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.uploads.append(kwargs)


def test_snowflake_stage_effects_registers_artifact_and_generic_rows() -> None:
    definition = load_source_definition(X5J9)
    adapter = SocrataAdapter()
    acquired = adapter.acquire(definition, fixture_dir=X5J9_FIXTURES)
    normalized = adapter.normalize(definition, acquired.payload).records
    state = RunState(
        ingestion_run_id="run-1",
        resource_key=definition.resource_key,
        source_definition_version=definition.definition_version,
        tier=Tier.B,
        status=RunStatus.RUNNING,
        stages=[],
    )
    cursor = _FakeCursor()
    connection = _FakeConnection(cursor)
    spaces = _FakeSpaces()
    effects = SnowflakeStageEffects(
        connection_factory=lambda: connection,
        spaces_client=spaces,
    )

    artifact = effects.register_artifact(definition, state, acquired)
    load = effects.load(definition, state, normalized)

    assert artifact["wrote"] is True
    assert len(spaces.uploads) == 1
    assert load["physical_relation"] == "RAW.GOVERNED_SOURCE_RECORDS"
    assert len(cursor.executed) == 3
    assert cursor.executemany_calls == []


def test_generic_projection_uses_bounded_multirow_merges() -> None:
    definition = load_source_definition(X5J9)
    state = RunState(
        ingestion_run_id="run-1",
        resource_key=definition.resource_key,
        source_definition_version=definition.definition_version,
        tier=Tier.B,
        status=RunStatus.RUNNING,
        stages=[],
    )
    records = [
        {"source_id": definition.source_id, "record": {":id": str(index), "fips": "08001"}}
        for index in range(_UPSERT_BATCH_SIZE + 1)
    ]
    cursor = _FakeCursor()
    connection = _FakeConnection(cursor)
    effects = SnowflakeStageEffects(connection_factory=lambda: connection)

    result = effects.load(definition, state, records)

    assert result["rows_inserted"] == _UPSERT_BATCH_SIZE + 1
    assert result["batches"] == 2
    assert len(cursor.executed) == 2
    assert cursor.executemany_calls == []
    assert all("FROM VALUES" in sql for sql, _params in cursor.executed)
    assert [len(params or ()) for _sql, params in cursor.executed] == [
        _UPSERT_BATCH_SIZE * 10,
        10,
    ]


def test_generic_row_identity_is_stable_when_source_order_changes() -> None:
    definition = load_source_definition(X5J9)
    state = RunState(
        ingestion_run_id="run-1",
        resource_key=definition.resource_key,
        source_definition_version=definition.definition_version,
        tier=Tier.B,
        status=RunStatus.RUNNING,
        stages=[],
    )
    first = {"source_id": definition.source_id, "record": {":id": "publisher-1", "fips": "08001"}}
    inserted = {
        "source_id": definition.source_id,
        "record": {":id": "publisher-0", "fips": "08000"},
    }

    original_id = _lineage_rows(definition, state, [first])[0][0]
    shifted_id = _lineage_rows(definition, state, [inserted, first])[1][0]

    assert shifted_id == original_id


def test_generic_projection_merges_update_lineage_and_uses_each_table_timestamp() -> None:
    for sql, timestamp_column in (
        (_UPSERT_RAW_SQL, "loaded_at"),
        (_UPSERT_STAGING_SQL, "normalized_at"),
        (_UPSERT_CONFORMED_SQL, "conformed_at"),
    ):
        assert "WHEN MATCHED THEN UPDATE SET" in sql
        assert f", {timestamp_column}=CURRENT_TIMESTAMP()" in sql
        assert f",\n   {timestamp_column})" in sql
