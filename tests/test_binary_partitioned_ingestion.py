"""Story #426 fixture proof for replay, bounded partitions, and resume."""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lyme_gap_atlas_data.ingestion.adapters import (
    AcquireResult,
    StreamingNormalizeResult,
)
from lyme_gap_atlas_data.ingestion.checkpoints import (
    FileCheckpointStore,
    SnowflakeCheckpointStore,
)
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.partitioning import MAX_PARTITION_BYTES, partition_records
from lyme_gap_atlas_data.ingestion.runtime import SnowflakeStageEffects, _insert_revisions
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import (
    AdapterKind,
    RunState,
    RunStatus,
    Stage,
    Tier,
    ValidationResult,
)
from lyme_gap_atlas_data.semantic_release import SemanticSource, _read_source_rows

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "config/sources/cdc_x5j9_wybp.yml"
BINARY = b"CDF\x01\x00\xff\x13\x80" * 64


class BinaryFixtureAdapter:
    kind = AdapterKind.SOCRATA

    def __init__(self, *, fail_once_after: int | None = None, total: int = 1001) -> None:
        self.acquire_count = 0
        self.fail_once_after = fail_once_after
        self.total = total

    def acquire(self, definition: Any, *, fixture_dir: Path | None = None) -> AcquireResult:
        self.acquire_count += 1
        return AcquireResult(
            payload=BINARY,
            artifact_sha256=hashlib.sha256(BINARY).hexdigest(),
            media_type="application/x-netcdf",
            raw_payload=BINARY,
        )

    def restore_raw_payload(self, definition: Any, raw_payload: bytes) -> bytes:
        return raw_payload

    def validate_payload(self, definition: Any, payload: Any) -> ValidationResult:
        return ValidationResult(ok=payload == BINARY)

    def normalize_iter(self, definition: Any, payload: Any) -> StreamingNormalizeResult:
        def rows() -> Any:
            for index in range(self.total):
                if self.fail_once_after == index:
                    self.fail_once_after = None
                    raise ValueError("fixture partition boundary failure")
                yield {"record": {":id": str(index), "fips": "08000", "value": index}}

        return StreamingNormalizeResult(rows(), "binary-fixture-v1")

    def normalize(self, definition: Any, payload: Any) -> Any:
        raise AssertionError("Streaming adapter must not materialize all records")


def test_binary_file_replay_and_corruption(tmp_path: Path) -> None:
    store = FileCheckpointStore(tmp_path)
    digest = hashlib.sha256(BINARY).hexdigest()
    store.save_binary_artifact("run-1", BINARY, digest)
    store.save_binary_artifact("run-1", BINARY, digest)
    assert store.load_binary_artifact("run-1") == BINARY
    assert not (tmp_path / "run-1.payload.json").exists()
    assert digest == hashlib.sha256(store.load_binary_artifact("run-1") or b"").hexdigest()
    (tmp_path / "run-1.artifact.bin").write_bytes(BINARY + b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        store.load_binary_artifact("run-1")


def test_deterministic_bounded_partitions_and_duplicate_protection(tmp_path: Path) -> None:
    rows = ({"record": {"id": index}} for index in range(1001))
    parts = list(partition_records(rows))
    assert [len(part.records) for part in parts] == [250, 250, 250, 250, 1]
    assert [part.partition_id for part in parts] == [
        part.partition_id
        for part in partition_records({"record": {"id": index}} for index in range(1001))
    ]
    assert all(part.byte_count <= MAX_PARTITION_BYTES for part in parts)
    store = FileCheckpointStore(tmp_path)
    for part in parts:
        store.save_partition("run-1", part)
    store.save_partition("run-1", parts[0])
    with pytest.raises(ValueError, match="mismatch"):
        store.save_partition("run-1", replace(parts[0], sha256="0" * 64))
    store.complete_partitions("run-1", len(parts))
    store.complete_partitions("run-1", len(parts))
    assert store.partitions_complete("run-1")
    assert list(store.iter_partitions("run-1")) == parts
    assert not (tmp_path / "run-1.normalized.json").exists()
    with pytest.raises(ValueError, match="Completed partition set"):
        store.save_partition(
            "run-1", replace(next(partition_records([{"record": {"id": 1002}}])), ordinal=5)
        )


def test_partial_run_resumes_without_reacquire_or_monolithic_checkpoint(tmp_path: Path) -> None:
    store = FileCheckpointStore(tmp_path)
    adapter = BinaryFixtureAdapter(fail_once_after=251)
    definition = load_source_definition(DEFINITION)
    first = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter).run(
        definition, tier=Tier.A
    )
    assert first.status.value == "FAILED"
    assert len(list(store.iter_partitions(first.ingestion_run_id))) == 1
    resumed = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter).resume(
        first.ingestion_run_id, definition=definition
    )
    assert resumed.status.value == "SUCCEEDED"
    assert adapter.acquire_count == 1
    assert sum(len(part.records) for part in store.iter_partitions(first.ingestion_run_id)) == 1001
    assert store.partitions_complete(first.ingestion_run_id)
    assert not (tmp_path / f"{first.ingestion_run_id}.normalized.json").exists()
    assert not (tmp_path / f"{first.ingestion_run_id}.payload.json").exists()


def test_failure_before_first_partition_and_completed_retry(tmp_path: Path) -> None:
    store = FileCheckpointStore(tmp_path)
    adapter = BinaryFixtureAdapter(fail_once_after=0, total=3)
    definition = load_source_definition(DEFINITION)
    first = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter).run(
        definition, tier=Tier.A
    )
    assert first.status.value == "FAILED"
    assert list(store.iter_partitions(first.ingestion_run_id)) == []
    assert not store.partitions_complete(first.ingestion_run_id)
    runner = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter)
    completed = runner.resume(first.ingestion_run_id, definition=definition)
    assert completed.status.value == "SUCCEEDED"
    assert runner.resume(first.ingestion_run_id, definition=definition).status.value == "SUCCEEDED"
    assert len(list(store.iter_partitions(first.ingestion_run_id))) == 1
    assert adapter.acquire_count == 1


def test_duplicate_logical_record_across_partitions_fails_closed(tmp_path: Path) -> None:
    class DuplicateAdapter(BinaryFixtureAdapter):
        def normalize_iter(self, definition: Any, payload: Any) -> StreamingNormalizeResult:
            def rows() -> Any:
                for index in range(251):
                    yield {"record": {":id": str(index if index < 250 else 0), "fips": "08000"}}

            return StreamingNormalizeResult(rows(), "binary-fixture-v1")

    store = FileCheckpointStore(tmp_path)
    definition = load_source_definition(DEFINITION)
    state = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=DuplicateAdapter()).run(
        definition, tier=Tier.A
    )
    assert state.status.value == "FAILED"
    assert not store.partitions_complete(state.ingestion_run_id)
    assert len(list(store.iter_partitions(state.ingestion_run_id))) == 2


def test_large_stream_never_creates_monolithic_normalized_checkpoint(tmp_path: Path) -> None:
    store = FileCheckpointStore(tmp_path)
    definition = load_source_definition(DEFINITION)
    state = IngestionOrchestrator(
        store, fixture_dir=tmp_path, adapter=BinaryFixtureAdapter(total=20_001)
    ).run(definition, tier=Tier.A)
    assert state.status.value == "SUCCEEDED"
    assert len(list(store.iter_partitions(state.ingestion_run_id))) == 81
    assert all(
        path.stat().st_size < 1_000_000
        for path in tmp_path.glob(f"{state.ingestion_run_id}.part-*.json")
    )
    assert not (tmp_path / f"{state.ingestion_run_id}.normalized.json").exists()


def test_identical_binary_across_runs_keeps_content_identity_and_capture_lineage(
    tmp_path: Path,
) -> None:
    adapter = BinaryFixtureAdapter(total=2)
    store = FileCheckpointStore(tmp_path)
    definition = load_source_definition(DEFINITION)
    runner = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter)
    first = runner.run(definition, tier=Tier.A)
    second = runner.run(definition, tier=Tier.A)
    first_artifact = first.checkpoint(Stage.ACQUIRE)
    second_artifact = second.checkpoint(Stage.ACQUIRE)
    assert first_artifact is not None and second_artifact is not None
    assert first_artifact.artifact_sha256 == second_artifact.artifact_sha256
    assert first_artifact.artifact_id != second_artifact.artifact_id
    assert store.load_binary_artifact(first.ingestion_run_id) == BINARY
    assert store.load_binary_artifact(second.ingestion_run_id) == BINARY


class _Cursor:
    def __init__(
        self,
        fetched: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
        fetches: list[tuple[Any, ...] | None] | None = None,
    ) -> None:
        self.fetched = fetched
        self.fetches = fetches or []
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def __iter__(self) -> Any:
        return iter(self.rows)

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        assert params is None or sql.count("%s") == len(params)
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        if self.fetches:
            return self.fetches.pop(0)
        return self.fetched

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.committed = False

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self._cursor

    def autocommit(self, _enabled: bool) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def test_snowflake_partition_uses_bounded_additive_row() -> None:
    part = next(partition_records([{"record": {"id": 1}}]))
    cursor = _Cursor(fetches=[None, (part.partition_id, part.sha256, 1, part.byte_count)])
    connection = _Connection(cursor)
    SnowflakeCheckpointStore(connection_factory=lambda: connection).save_partition("run-1", part)
    assert connection.committed
    sql, params = cursor.executed[1]
    assert "INGESTION_RUN_NORMALIZED_PARTITIONS" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "WHEN MATCHED" not in sql
    assert params is not None and len(str(params[-1]).encode()) <= MAX_PARTITION_BYTES

    completed_cursor = _Cursor((1,))
    completed_store = SnowflakeCheckpointStore(
        connection_factory=lambda: _Connection(completed_cursor)
    )
    with pytest.raises(ValueError, match="Completed partition set"):
        completed_store.save_partition("run-1", replace(part, ordinal=1))


def test_snowflake_partition_replay_and_completion_query_shape() -> None:
    part = next(partition_records([{"record": {"id": 1}}]))
    cursor = _Cursor(
        (1,),
        rows=[(part.ordinal, part.sha256, part.byte_count, list(part.records))],
    )
    connection = _Connection(cursor)
    store = SnowflakeCheckpointStore(connection_factory=lambda: connection)
    assert list(store.iter_partitions("run-1")) == [part]
    store.complete_partitions("run-1", 1)
    assert store.partitions_complete("run-1")
    assert connection.committed
    assert any("ORDER BY partition_ordinal" in sql for sql, _ in cursor.executed)
    assert any("INGESTION_RUN_PARTITION_COMPLETIONS" in sql for sql, _ in cursor.executed)


def test_snowflake_binary_replay_verifies_source_bytes() -> None:
    digest = hashlib.sha256(BINARY).hexdigest()
    cursor = _Cursor(("s3://one-health-lyme-gap-atlas-data-dev/dev/run/artifact", digest))
    connection = _Connection(cursor)

    class Spaces:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def get_object(self, **_kwargs: Any) -> dict[str, io.BytesIO]:
            return {"Body": io.BytesIO(self.body)}

    store = SnowflakeCheckpointStore(
        connection_factory=lambda: connection, spaces_client=Spaces(BINARY)
    )
    assert store.load_source_artifact("run-1") == BINARY
    assert "RAW_ARTIFACTS" in cursor.executed[0][0]
    corrupt = SnowflakeCheckpointStore(
        connection_factory=lambda: connection, spaces_client=Spaces(BINARY + b"bad")
    )
    with pytest.raises(ValueError, match="checksum"):
        corrupt.load_source_artifact("run-1")


def test_snowflake_binary_capture_keeps_bytes_and_distinct_run_artifacts() -> None:
    class Spaces:
        def __init__(self) -> None:
            self.bodies: list[bytes] = []

        def put_object(self, **kwargs: Any) -> None:
            self.bodies.append(kwargs["Body"])

    cursor = _Cursor()
    connection = _Connection(cursor)
    spaces = Spaces()
    effects = SnowflakeStageEffects(connection_factory=lambda: connection, spaces_client=spaces)
    definition = load_source_definition(DEFINITION)
    acquired = BinaryFixtureAdapter(total=1).acquire(definition)

    def state(run_id: str) -> RunState:
        return RunState(
            ingestion_run_id=run_id,
            resource_key=definition.resource_key,
            source_definition_version=definition.definition_version,
            tier=Tier.B,
            status=RunStatus.RUNNING,
        )

    first = effects.register_artifact(definition, state("run-1"), acquired)
    second = effects.register_artifact(definition, state("run-2"), acquired)
    assert first["artifact_sha256"] == second["artifact_sha256"]
    assert first["artifact_id"] != second["artifact_id"]
    assert spaces.bodies == [BINARY, BINARY]
    assert any("RAW_ARTIFACTS" in sql for sql, _ in cursor.executed)


def test_physical_revision_identity_preserves_prior_lineage() -> None:
    def revision(run: str, artifact_hash: str, value: int) -> tuple[str, str]:
        cursor = _Cursor()
        row = (
            "logical-1",
            "source",
            "dataset",
            "resource",
            1,
            run,
            "publisher-row",
            "a" * 64,
            f'{{"record":{{"value":{value}}}}}',
            "2026-09-24T00:00:00Z",
        )
        _insert_revisions(cursor, [row], f"artifact-{run}", artifact_hash, "method-v1")
        sql, params = cursor.executed[-1]
        assert "WHEN MATCHED THEN UPDATE" not in sql
        assert params is not None
        return str(params[1]), str(params[7])

    original, original_run = revision("run-1", "a" * 64, 1)
    unchanged, repeat_run = revision("run-2", "a" * 64, 1)
    revised_same_value, revised_run = revision("run-3", "b" * 64, 1)
    revised_value, _ = revision("run-4", "b" * 64, 2)
    assert original == unchanged
    assert original_run == "run-1" and repeat_run == "run-2"
    assert revised_same_value != original
    assert revised_run == "run-3"
    assert revised_value != revised_same_value


def test_generic_semantic_read_resolves_each_immutable_run_capture() -> None:
    class CaptureCursor(_Cursor):
        def __init__(self) -> None:
            super().__init__()
            self.captures: dict[str, tuple[Any, ...]] = {}
            self.selected: list[tuple[Any, ...]] = []

        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
            super().execute(sql, params)
            if "MERGE INTO GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS" in sql:
                assert params is not None
                run = str(params[7])
                capture = (
                    params[2],
                    params[3],
                    params[4],
                    params[5],
                    params[6],
                    run,
                    params[8],
                    params[11],
                    params[14],
                    params[15],
                )
                self.captures.setdefault(run, capture)
            elif (
                "FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS" in sql
                and "SELECT record_id" in sql
            ):
                assert params is not None
                row = self.captures.get(str(params[1]))
                self.selected = [row] if row is not None else []
            elif "FROM CONFORMED.GOVERNED_SOURCE_RECORDS" in sql:
                self.selected = []

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self.selected

    cursor = CaptureCursor()
    source = SemanticSource(
        source_key="context_svi",
        resource_key="resource",
        source_id="source",
        dataset_id="dataset",
        label="source",
        vintage="2026",
        source_url="https://example.test",
        note="",
        data_source_version_id="version",
        ingestion_run_id="run-A",
        artifact_id="artifact-A",
        artifact_sha256="a" * 64,
        definition_version=1,
        field_map={},
    )
    for run, artifact, value in (
        ("run-A", "a" * 64, 10),
        ("run-B", "b" * 64, 12),
        ("run-C", "b" * 64, 12),
    ):
        row = (
            "logical-1",
            "source",
            "dataset",
            "resource",
            1,
            run,
            "publisher-row",
            "a" * 64,
            f'{{"record":{{"value":{value}}}}}',
            "2026-09-24T00:00:00Z",
        )
        _insert_revisions(cursor, [row], f"artifact-{run}", artifact, "method-v1")

    assert len(cursor.captures) == 3
    assert cursor.captures["run-A"][7] == "a" * 64
    assert cursor.captures["run-A"][5] == "run-A"
    assert cursor.captures["run-A"][6] == "publisher-row"
    for run, expected in (("run-A", 10), ("run-B", 12), ("run-C", 12)):
        rows = _read_source_rows(cursor, replace(source, ingestion_run_id=run))
        assert len(rows) == 1
        assert rows[0]["payload"] == f'{{"record":{{"value":{expected}}}}}'
        assert rows[0]["ingestion_run_id"] == run
    assert not any("WHEN MATCHED THEN UPDATE" in sql for sql, _ in cursor.executed)

    class LegacyCursor(CaptureCursor):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
            super().execute(sql, params)
            if "FROM CONFORMED.GOVERNED_SOURCE_RECORDS" in sql:
                self.selected = [cursor.captures["run-A"]]

    legacy = LegacyCursor()
    legacy_rows = _read_source_rows(legacy, replace(source, ingestion_run_id="run-A"))
    assert legacy_rows[0]["payload"] == '{"record":{"value":10}}'
    assert "FROM CONFORMED.GOVERNED_SOURCE_RECORDS" in legacy.executed[-1][0]
