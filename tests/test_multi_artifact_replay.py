"""Two source-faithful binary members through the canonical resume path (#432)."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lyme_gap_atlas_data.ingestion.adapters import (
    AcquireResult,
    AcquisitionArtifact,
    StreamingNormalizeResult,
)
from lyme_gap_atlas_data.ingestion.artifact_replay import (
    ArtifactMember,
    resolve_member,
    validate_members,
)
from lyme_gap_atlas_data.ingestion.checkpoints import (
    ArtifactMemberStore,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    SnowflakeCheckpointStore,
)
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.runtime import SnowflakeStageEffects
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import (
    AdapterKind,
    RunState,
    RunStatus,
    Stage,
    Tier,
    ValidationResult,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = load_source_definition(ROOT / "config/sources/cdc_x5j9_wybp.yml")
SCIENTIFIC = b"CDF\x01\x00\xff\x13\x80" * 8
GEOMETRY = b"PK\x03\x04fake-tiger-zip\x00\xff"


def artifacts() -> tuple[AcquisitionArtifact, ...]:
    return (
        AcquisitionArtifact(
            "scientific-source",
            SCIENTIFIC,
            "application/x-netcdf",
            "https://source.example.test/month.nc",
            "SCIENTIFIC_SOURCE",
        ),
        AcquisitionArtifact(
            "analysis-geometry",
            GEOMETRY,
            "application/zip",
            "https://source.example.test/counties.zip",
            "ANALYSIS_GEOMETRY",
        ),
    )


class TwoBinaryAdapter:
    kind = AdapterKind.SOCRATA

    def __init__(self, *, allow_acquire: bool = True, fail_after: int | None = None) -> None:
        self.allow_acquire = allow_acquire
        self.fail_after = fail_after
        self.acquire_count = 0
        self.restored: list[tuple[bytes, bytes]] = []

    def acquire(self, definition: Any, *, fixture_dir: Path | None = None) -> AcquireResult:
        assert self.allow_acquire
        self.acquire_count += 1
        return AcquireResult(
            SCIENTIFIC,
            hashlib.sha256(SCIENTIFIC).hexdigest(),
            "application/x-netcdf",
            raw_payload=SCIENTIFIC,
            artifacts=artifacts(),
        )

    def restore_artifacts(
        self, definition: Any, run_id: str, store: ArtifactMemberStore
    ) -> tuple[bytes, bytes]:
        restored = (
            store.load_artifact_member(run_id, name="scientific-source"),
            store.load_artifact_member(run_id, role="ANALYSIS_GEOMETRY"),
        )
        self.restored.append(restored)
        return restored

    def restore_raw_payload(self, definition: Any, raw_payload: bytes) -> Any:
        raise AssertionError("Named replay must not use single-artifact restore")

    def validate_payload(self, definition: Any, payload: Any) -> ValidationResult:
        return ValidationResult(ok=payload == (SCIENTIFIC, GEOMETRY))

    def normalize_iter(self, definition: Any, payload: Any) -> StreamingNormalizeResult:
        assert payload == (SCIENTIFIC, GEOMETRY)

        def rows() -> Any:
            for index in range(252):
                if index == self.fail_after:
                    self.fail_after = None
                    raise ValueError("fixture partition interruption")
                yield {"record": {":id": str(index), "fips": "08000", "value": index}}

        return StreamingNormalizeResult(rows(), "two-binary-fixture-v1")

    def normalize(self, definition: Any, payload: Any) -> Any:
        raise AssertionError("Streaming normalization is required")


@pytest.mark.parametrize("failure", ["ACQUIRE", "NORMALIZE"])
def test_fresh_process_resume_replays_both_members_and_partitions(
    tmp_path: Path, failure: str
) -> None:
    original = TwoBinaryAdapter(fail_after=251 if failure == "NORMALIZE" else None)
    store = FileCheckpointStore(tmp_path)
    first = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=original).run(
        DEFINITION,
        tier=Tier.A,
        fail_after_stage="ACQUIRE" if failure == "ACQUIRE" else None,
    )
    assert first.status is RunStatus.FAILED
    run_id = first.ingestion_run_id
    members = store.list_artifact_members(run_id)
    assert [member.name for member in members] == ["analysis-geometry", "scientific-source"]
    assert {member.sha256 for member in members} == {
        hashlib.sha256(SCIENTIFIC).hexdigest(),
        hashlib.sha256(GEOMETRY).hexdigest(),
    }
    assert all(member.ingestion_run_id == run_id and member.artifact_id for member in members)
    assert all(member.source_uri and member.media_type and member.role for member in members)
    assert len(list(tmp_path.glob(f"{run_id}.member-*.bin"))) == 2
    assert len(list(store.iter_partitions(run_id))) == (1 if failure == "NORMALIZE" else 0)

    del original, store
    resumed_adapter = TwoBinaryAdapter(allow_acquire=False)
    resumed_store = FileCheckpointStore(tmp_path)
    resumed = IngestionOrchestrator(
        resumed_store, fixture_dir=tmp_path, adapter=resumed_adapter
    ).resume(run_id, definition=DEFINITION)
    assert resumed.status is RunStatus.SUCCEEDED, (
        resumed.checkpoint(Stage.NORMALIZE),
        resumed_adapter.restored,
    )
    assert resumed_adapter.acquire_count == 0
    assert resumed_adapter.restored and all(
        item == (SCIENTIFIC, GEOMETRY) for item in resumed_adapter.restored
    )
    assert len(list(resumed_store.iter_partitions(run_id))) == 2
    assert resumed_store.partitions_complete(run_id)


@pytest.mark.parametrize("fault", ["missing", "corrupt", "metadata", "duplicate"])
def test_member_faults_fail_closed_without_reacquisition(tmp_path: Path, fault: str) -> None:
    store = FileCheckpointStore(tmp_path)
    first = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=TwoBinaryAdapter()).run(
        DEFINITION, tier=Tier.A, fail_after_stage="ACQUIRE"
    )
    run_id = first.ingestion_run_id
    member = resolve_member(store.list_artifact_members(run_id), name="analysis-geometry")
    binary_path = tmp_path / f"{run_id}.member-{member.member_id}.bin"
    metadata_path = tmp_path / f"{run_id}.member-{member.member_id}.json"
    if fault == "missing":
        binary_path.unlink()
    elif fault == "corrupt":
        binary_path.write_bytes(GEOMETRY + b"replacement")
    elif fault == "metadata":
        document = json.loads(metadata_path.read_text())
        document["sha256"] = "0" * 64
        metadata_path.write_text(json.dumps(document))
    else:
        duplicate = tmp_path / f"{run_id}.member-{'f' * 64}.json"
        duplicate.write_bytes(metadata_path.read_bytes())
    adapter = TwoBinaryAdapter(allow_acquire=False)
    resumed = IngestionOrchestrator(
        FileCheckpointStore(tmp_path), fixture_dir=tmp_path, adapter=adapter
    ).resume(run_id, definition=DEFINITION)
    assert resumed.status is RunStatus.FAILED
    assert adapter.acquire_count == 0
    assert resumed.checkpoint(Stage.ACQUIRE).status.value == "COMPLETED"


def test_duplicate_and_ambiguous_identity_and_reordered_enumeration(tmp_path: Path) -> None:
    store = InMemoryCheckpointStore()
    members = (
        ArtifactMember(
            "run-1",
            "science",
            "INPUT",
            "artifact-a",
            "source-a",
            "binary/a",
            hashlib.sha256(SCIENTIFIC).hexdigest(),
            len(SCIENTIFIC),
        ),
        ArtifactMember(
            "run-1",
            "geometry",
            "INPUT",
            "artifact-b",
            "source-b",
            "binary/b",
            hashlib.sha256(GEOMETRY).hexdigest(),
            len(GEOMETRY),
        ),
    )
    for member, body in zip(reversed(members), reversed((SCIENTIFIC, GEOMETRY)), strict=True):
        store.save_artifact_member(member, body)
    assert store.list_artifact_members("run-1") == validate_members(members)
    assert store.load_artifact_member("run-1", name="science") == SCIENTIFIC
    with pytest.raises(ValueError, match="ambiguous"):
        store.load_artifact_member("run-1", role="INPUT")
    with pytest.raises(ValueError, match="ambiguous"):
        store.load_artifact_member("run-1", name="missing")
    with pytest.raises(ValueError, match="Duplicate"):
        validate_members((*members, members[0]))
    with pytest.raises(ValueError, match="mismatch"):
        store.save_artifact_member(
            replace(members[0], sha256=hashlib.sha256(b"new").hexdigest()), b"new"
        )


def test_duplicate_acquisition_names_fail_before_capture(tmp_path: Path) -> None:
    class DuplicateAdapter(TwoBinaryAdapter):
        def acquire(self, definition: Any, *, fixture_dir: Path | None = None) -> AcquireResult:
            acquired = super().acquire(definition, fixture_dir=fixture_dir)
            return replace(acquired, artifacts=(artifacts()[0], artifacts()[0]))

    state = IngestionOrchestrator(
        FileCheckpointStore(tmp_path), fixture_dir=tmp_path, adapter=DuplicateAdapter()
    ).run(DEFINITION, tier=Tier.A)
    assert state.status is RunStatus.FAILED
    assert state.checkpoint(Stage.ACQUIRE).redacted_diagnostic_code == "VALUEERROR"
    assert not list(tmp_path.glob(f"{state.ingestion_run_id}.member-*.bin"))


def test_legacy_one_binary_adapter_needs_no_member_configuration(tmp_path: Path) -> None:
    class LegacyAdapter:
        kind = AdapterKind.SOCRATA

        def __init__(self, *, may_acquire: bool) -> None:
            self.may_acquire = may_acquire
            self.acquire_count = 0

        def acquire(self, definition: Any, *, fixture_dir: Path | None = None) -> AcquireResult:
            assert self.may_acquire
            self.acquire_count += 1
            return AcquireResult(
                SCIENTIFIC,
                hashlib.sha256(SCIENTIFIC).hexdigest(),
                "application/x-netcdf",
                raw_payload=SCIENTIFIC,
            )

        def restore_raw_payload(self, definition: Any, raw_payload: bytes) -> bytes:
            return raw_payload

        def validate_payload(self, definition: Any, payload: Any) -> ValidationResult:
            return ValidationResult(ok=payload == SCIENTIFIC)

        def normalize_iter(self, definition: Any, payload: Any) -> StreamingNormalizeResult:
            assert payload == SCIENTIFIC
            return StreamingNormalizeResult(
                iter(({"record": {":id": "one", "fips": "08000", "value": 1}},)),
                "legacy-binary-fixture-v1",
            )

        def normalize(self, definition: Any, payload: Any) -> Any:
            raise AssertionError("Streaming normalization is required")

    first_adapter = LegacyAdapter(may_acquire=True)
    first = IngestionOrchestrator(
        FileCheckpointStore(tmp_path), fixture_dir=tmp_path, adapter=first_adapter
    ).run(DEFINITION, tier=Tier.A, fail_after_stage="ACQUIRE")
    assert first.status is RunStatus.FAILED
    checkpoint = first.checkpoint(Stage.ACQUIRE)
    assert checkpoint is not None
    assert checkpoint.artifact_id == (
        f"planned:{first.ingestion_run_id}:{hashlib.sha256(SCIENTIFIC).hexdigest()[:32]}"
    )
    assert checkpoint.artifact_sha256 == hashlib.sha256(SCIENTIFIC).hexdigest()
    assert FileCheckpointStore(tmp_path).load_binary_artifact(first.ingestion_run_id) == SCIENTIFIC
    assert not list(tmp_path.glob(f"{first.ingestion_run_id}.member-*.bin"))
    resumed_adapter = LegacyAdapter(may_acquire=False)
    resumed = IngestionOrchestrator(
        FileCheckpointStore(tmp_path), fixture_dir=tmp_path, adapter=resumed_adapter
    ).resume(first.ingestion_run_id, definition=DEFINITION)
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed_adapter.acquire_count == 0


class Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> Cursor:
        return self._cursor


def test_snowflake_spaces_named_member_requires_exact_ledger_and_bytes() -> None:
    body = GEOMETRY
    member = ArtifactMember(
        "run-1",
        "analysis-geometry",
        "ANALYSIS_GEOMETRY",
        "artifact-geometry",
        "https://source.example.test/counties.zip",
        "application/zip",
        hashlib.sha256(body).hexdigest(),
        len(body),
        "s3://one-health-lyme-gap-atlas-data-dev/dev/run/geometry",
    )
    cursor = Cursor(
        [
            (
                member.artifact_uri,
                member.sha256,
                member.byte_count,
                member.media_type,
                member.source_uri,
                member.role,
                member.row_count,
            )
        ]
    )

    class Spaces:
        def __init__(self, value: bytes) -> None:
            self.value = value

        def get_object(self, **_kwargs: Any) -> dict[str, io.BytesIO]:
            return {"Body": io.BytesIO(self.value)}

    class Store(SnowflakeCheckpointStore):
        def load(self, run_id: str) -> RunState | None:
            state = RunState(run_id, DEFINITION.resource_key, 1, Tier.B, RunStatus.FAILED)
            from lyme_gap_atlas_data.ingestion.types import StageCheckpoint, StageStatus

            state.stages = [
                StageCheckpoint(
                    Stage.ACQUIRE,
                    StageStatus.COMPLETED,
                    detail={"artifacts": [member.to_dict()]},
                )
            ]
            return state

    store = Store(connection_factory=lambda: Connection(cursor), spaces_client=Spaces(body))
    assert store.list_artifact_members("run-1") == (member,)
    assert store.load_artifact_member("run-1", name=member.name) == body
    assert "a.artifact_id=%s" in cursor.executed[-1][0]
    assert cursor.executed[-1][1] == ("run-1", member.artifact_id, "run-1")
    store._spaces_client = Spaces(body + b"bad")
    with pytest.raises(ValueError, match="checksum"):
        store.load_artifact_member("run-1", name=member.name)
    cursor.rows = [
        (
            member.artifact_uri,
            member.sha256,
            member.byte_count,
            member.media_type,
            "https://source.example.test/replaced.zip",
            member.role,
            member.row_count,
        )
    ]
    with pytest.raises(ValueError, match="metadata mismatch"):
        store.load_artifact_member("run-1", name=member.name)
    cursor.rows = []
    with pytest.raises(ValueError, match="missing or ambiguous"):
        store.load_artifact_member("run-1", name=member.name)
    cursor.rows = [(None,) * 7, (None,) * 7]
    with pytest.raises(ValueError, match="missing or ambiguous"):
        store.load_artifact_member("run-1", name=member.name)


def test_snowflake_member_ids_do_not_follow_artifact_order() -> None:
    class RecordingCursor:
        def __init__(self) -> None:
            self.rows: list[tuple[str, tuple[Any, ...] | None]] = []

        def __enter__(self) -> RecordingCursor:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
            self.rows.append((sql, params))

    class RecordingConnection(Connection):
        def autocommit(self, _value: bool) -> None:
            return None

        def commit(self) -> None:
            return None

    class Spaces:
        def put_object(self, **_kwargs: Any) -> None:
            return None

    cursor = RecordingCursor()
    effects = SnowflakeStageEffects(
        connection_factory=lambda: RecordingConnection(cursor), spaces_client=Spaces()
    )
    state = RunState("run-1", DEFINITION.resource_key, 1, Tier.B, RunStatus.RUNNING)
    acquired = AcquireResult(
        SCIENTIFIC,
        hashlib.sha256(SCIENTIFIC).hexdigest(),
        "application/x-netcdf",
        raw_payload=SCIENTIFIC,
        artifacts=artifacts(),
    )
    first = effects.register_artifact(DEFINITION, state, acquired)
    second = effects.register_artifact(
        DEFINITION, state, replace(acquired, artifacts=tuple(reversed(artifacts())))
    )
    assert {item["name"]: item["artifact_id"] for item in first["artifacts"]} == {
        item["name"]: item["artifact_id"] for item in second["artifacts"]
    }
    assert first["artifact_id"] == second["artifact_id"]
    request_ids = [params[0] for sql, params in cursor.rows if "INGESTION_REQUESTS" in sql]
    assert request_ids[:2] == list(reversed(request_ids[2:]))
