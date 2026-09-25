"""One resumable ingestion orchestrator for CLI and Actions."""

from __future__ import annotations

import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from ..settings import PipelineSettings
from .adapters import AcquisitionError, SourceAdapter, StreamingSourceAdapter, get_adapter
from .checkpoints import (
    BinaryArtifactStore,
    CheckpointStore,
    InMemoryCheckpointStore,
    PartitionStore,
    PayloadStore,
    RawArtifactStore,
)
from .identity import deterministic_record_id
from .partitioning import partition_records
from .runtime import NoopStageEffects, QualityFailure, SnowflakeStageEffects, StageEffects
from .source_definition import validate_source_definition
from .types import (
    FailureCategory,
    RunState,
    RunStatus,
    SourceDefinition,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
    ValidationResult,
)


class IngestionOrchestrator:
    """In-process state machine. Not a workflow engine."""

    def __init__(
        self,
        store: CheckpointStore | None = None,
        *,
        fixture_dir: Path | None = None,
        adapter: SourceAdapter | None = None,
        effects: StageEffects | None = None,
    ) -> None:
        self.store = store or InMemoryCheckpointStore()
        self.fixture_dir = fixture_dir
        self._adapter_override = adapter
        self._effects_override = effects
        self._payloads: dict[str, Any] = {}
        self._normalized: dict[str, Any] = {}

    def validate(self, definition: SourceDefinition) -> ValidationResult:
        return validate_source_definition(definition)

    def inspect(self, run_id: str) -> RunState:
        state = self.store.load(run_id)
        if state is None:
            raise KeyError(f"Unknown ingestion_run_id={run_id}")
        return state

    def run(
        self,
        definition: SourceDefinition,
        *,
        tier: Tier,
        dry_run: bool = False,
        fail_after_stage: str | None = None,
        run_id: str | None = None,
    ) -> RunState:
        if tier is Tier.C and dry_run is False:
            _require_protected_prod_execution()
        if tier is Tier.D and dry_run is False:
            raise PermissionError(
                "Tier D sources require the governed steward-review path before acquisition."
            )
        if tier in {Tier.B, Tier.C} and definition.extra.get("onboarding_mode") == "EVIDENCE_ONLY":
            raise PermissionError(
                "Evidence-only sources require the restricted Tier D operator envelope."
            )
        validation = self.validate(definition)
        if not validation.ok:
            raise ValueError(
                "Invalid SourceDefinition: "
                + "; ".join(f"{issue.code}:{issue.message}" for issue in validation.issues)
            )
        if tier is Tier.A and self.fixture_dir is None and not dry_run:
            raise ValueError("Tier A requires fixture_dir or --dry-run")

        state = RunState(
            ingestion_run_id=run_id or str(uuid.uuid4()),
            resource_key=definition.resource_key,
            source_definition_version=definition.definition_version,
            tier=tier,
            status=RunStatus.RUNNING,
            stages=[
                StageCheckpoint(stage=stage, status=StageStatus.PENDING)
                for stage in definition.stages
            ],
            dry_run=dry_run,
            next_action="run",
        )
        self.store.save(state)
        return self._execute(definition, state, fail_after_stage=fail_after_stage)

    def resume(
        self,
        run_id: str,
        *,
        definition: SourceDefinition,
        fail_after_stage: str | None = None,
    ) -> RunState:
        state = self.inspect(run_id)
        if state.resource_key != definition.resource_key:
            raise ValueError("Resume definition does not match the persisted resource_key")
        if state.source_definition_version != definition.definition_version:
            raise ValueError("Resume definition version does not match the persisted run")
        if state.status is RunStatus.SUCCEEDED:
            return state
        state.status = RunStatus.RUNNING
        state.next_action = "resume"
        self.store.save(state)
        return self._execute(definition, state, fail_after_stage=fail_after_stage)

    def _adapter(self, definition: SourceDefinition) -> SourceAdapter:
        if self._adapter_override is not None:
            return self._adapter_override
        return get_adapter(definition.adapter_kind)

    def _execute(
        self,
        definition: SourceDefinition,
        state: RunState,
        *,
        fail_after_stage: str | None,
    ) -> RunState:
        adapter = self._adapter(definition)
        effects = self._effects(state)
        streaming = isinstance(adapter, StreamingSourceAdapter)
        if streaming and not isinstance(self.store, PartitionStore):
            raise TypeError("Streaming adapter requires a partition checkpoint store")
        payload = self._payloads.get(state.ingestion_run_id)
        normalized = self._normalized.get(state.ingestion_run_id)
        if payload is None and isinstance(self.store, PayloadStore):
            payload = self.store.load_payload(state.ingestion_run_id)
        if payload is None and isinstance(self.store, BinaryArtifactStore):
            raw_binary = self.store.load_binary_artifact(state.ingestion_run_id)
            if raw_binary is not None:
                payload = adapter.restore_raw_payload(definition, raw_binary)
        if payload is None and isinstance(self.store, RawArtifactStore):
            raw_payload = self.store.load_source_artifact(state.ingestion_run_id)
            if raw_payload is not None:
                payload = adapter.restore_raw_payload(definition, raw_payload)
                if isinstance(self.store, PayloadStore) and not isinstance(payload, bytes):
                    self.store.save_payload(state.ingestion_run_id, payload)
        if normalized is None and isinstance(self.store, PayloadStore) and not streaming:
            normalized = self.store.load_normalized(state.ingestion_run_id)

        for checkpoint in state.stages:
            if checkpoint.status is StageStatus.COMPLETED:
                continue
            if checkpoint.status is StageStatus.SKIPPED:
                continue

            checkpoint.status = StageStatus.RUNNING
            checkpoint.attempt_count += 1
            checkpoint.started_at = datetime.now(UTC).isoformat()
            checkpoint.completed_at = None
            checkpoint.next_action = None
            checkpoint.failure_category = None
            checkpoint.redacted_diagnostic_code = None
            self.store.save(state)

            try:
                # fail_after_stage=X means X completed durably; failure is injected
                # when entering the following stage so resume does not replay X.
                if (
                    fail_after_stage
                    and _previous_stage_value(state, checkpoint.stage) == fail_after_stage
                ):
                    raise StageFailure(
                        FailureCategory.QUALITY,
                        "INJECTED_FAILURE",
                        f"resume:{checkpoint.stage.value}",
                    )
                if checkpoint.stage is Stage.ACQUIRE:
                    if state.dry_run and self.fixture_dir is None:
                        checkpoint.detail = {
                            "planned": True,
                            "endpoint": definition.endpoint_template,
                        }
                        checkpoint.artifact_sha256 = "dry-run"
                    else:
                        acquired = adapter.acquire(definition, fixture_dir=self.fixture_dir)
                        payload = acquired.payload
                        artifact = effects.register_artifact(definition, state, acquired)
                        if isinstance(payload, dict):
                            payload["_acquisition_lineage"] = {
                                "ingestion_run_id": state.ingestion_run_id,
                                "artifact_id": artifact["artifact_id"],
                                "retrieved_at": datetime.now(UTC).isoformat(),
                            }
                        self._payloads[state.ingestion_run_id] = payload
                        if isinstance(payload, bytes):
                            if isinstance(self.store, BinaryArtifactStore):
                                self.store.save_binary_artifact(
                                    state.ingestion_run_id, payload, acquired.artifact_sha256
                                )
                            elif not isinstance(self.store, RawArtifactStore):
                                raise TypeError(
                                    "Binary replay requires an artifact checkpoint store"
                                )
                        elif isinstance(self.store, PayloadStore):
                            self.store.save_payload(state.ingestion_run_id, payload)
                        checkpoint.artifact_id = str(artifact["artifact_id"])
                        checkpoint.artifact_sha256 = str(artifact["artifact_sha256"])
                        checkpoint.detail = {
                            "row_count": acquired.row_count,
                            "media_type": acquired.media_type,
                            **(acquired.detail or {}),
                            **artifact,
                        }
                elif checkpoint.stage is Stage.VALIDATE:
                    if payload is None and not state.dry_run:
                        raise RuntimeError("VALIDATE requires ACQUIRE payload")
                    if payload is not None:
                        result = adapter.validate_payload(definition, payload)
                        if not result.ok:
                            issue = result.issues[0]
                            raise StageFailure(
                                issue.category,
                                issue.code,
                                f"resume:{Stage.VALIDATE.value}",
                            )
                    checkpoint.detail = {"ok": True}
                elif checkpoint.stage is Stage.NORMALIZE:
                    if state.dry_run and payload is None:
                        checkpoint.transformation_version = "dry-run"
                        checkpoint.detail = {"planned": True}
                    else:
                        if payload is None:
                            raise RuntimeError("NORMALIZE requires ACQUIRE payload")
                        if streaming:
                            assert isinstance(self.store, PartitionStore)
                            if not self.store.partitions_complete(state.ingestion_run_id):
                                streamed = cast(StreamingSourceAdapter, adapter).normalize_iter(
                                    definition, payload
                                )
                                checkpoint.transformation_version = streamed.transformation_version
                                self.store.save(state)
                                count = 0
                                for part in partition_records(streamed.records):
                                    self.store.save_partition(state.ingestion_run_id, part)
                                    count += 1
                                self._validate_partition_identities(
                                    definition, state.ingestion_run_id
                                )
                                self.store.complete_partitions(state.ingestion_run_id, count)
                            partition_count = 0
                            record_count = 0
                            for part in self.store.iter_partitions(state.ingestion_run_id):
                                effects.materialize_normalized(
                                    definition, state, list(part.records)
                                )
                                partition_count += 1
                                record_count += len(part.records)
                            checkpoint.detail = {
                                "partition_count": partition_count,
                                "record_count": record_count,
                                "mode": "bounded_partitions",
                            }
                        else:
                            normalized_result = adapter.normalize(definition, payload)
                            normalized = normalized_result.records
                            self._normalized[state.ingestion_run_id] = normalized
                            if isinstance(self.store, PayloadStore):
                                self.store.save_normalized(state.ingestion_run_id, normalized)
                            checkpoint.transformation_version = (
                                normalized_result.transformation_version
                            )
                            checkpoint.detail = {
                                **(normalized_result.detail or {}),
                                **effects.materialize_normalized(definition, state, normalized),
                            }
                elif checkpoint.stage is Stage.LOAD:
                    if streaming and isinstance(self.store, PartitionStore):
                        loaded = 0
                        for part in self.store.iter_partitions(state.ingestion_run_id):
                            effects.load(definition, state, list(part.records))
                            loaded += len(part.records)
                        checkpoint.detail = {"record_count": loaded, "mode": "bounded_partitions"}
                    elif normalized is None and not state.dry_run:
                        raise RuntimeError("LOAD requires NORMALIZE payload")
                    else:
                        checkpoint.detail = effects.load(definition, state, normalized or [])
                elif checkpoint.stage is Stage.QUALITY:
                    if state.dry_run and normalized is None:
                        checkpoint.detail = {
                            "planned": True,
                            "rules_evaluated": [rule.rule_id for rule in definition.quality_rules],
                            "wrote": False,
                        }
                    elif streaming and isinstance(self.store, PartitionStore):
                        records = (
                            record
                            for part in self.store.iter_partitions(state.ingestion_run_id)
                            for record in part.records
                        )
                        checkpoint.detail = effects.quality_partitioned(definition, state, records)
                    else:
                        if normalized is None:
                            raise RuntimeError("QUALITY requires NORMALIZE payload")
                        checkpoint.detail = effects.quality(definition, state, normalized or [])
                elif checkpoint.stage is Stage.PUBLISH_STAGE:
                    if streaming and isinstance(self.store, PartitionStore):
                        record_count = sum(
                            len(part.records)
                            for part in self.store.iter_partitions(state.ingestion_run_id)
                        )
                        checkpoint.detail = effects.publish_partitioned(
                            definition, state, record_count
                        )
                    elif normalized is None and not state.dry_run:
                        raise RuntimeError("PUBLISH_STAGE requires NORMALIZE payload")
                    else:
                        checkpoint.detail = effects.publish(definition, state, normalized or [])
                elif checkpoint.stage is Stage.DISCOVER:
                    checkpoint.status = StageStatus.SKIPPED
                    checkpoint.detail = {"reason": "not_required_for_source"}
                    self.store.save(state)
                    continue
                else:
                    checkpoint.status = StageStatus.SKIPPED
                    checkpoint.detail = {"reason": "unhandled_stage_skipped"}
                    self.store.save(state)
                    continue

                checkpoint.status = StageStatus.COMPLETED
                checkpoint.completed_at = datetime.now(UTC).isoformat()
                self.store.save(state)
            except StageFailure as error:
                checkpoint.status = StageStatus.FAILED
                checkpoint.failure_category = error.category
                checkpoint.redacted_diagnostic_code = error.code
                checkpoint.next_action = error.next_action
                state.status = RunStatus.FAILED
                state.next_action = error.next_action
                self.store.save(state)
                return state
            except Exception as error:
                checkpoint.status = StageStatus.FAILED
                checkpoint.failure_category = _failure_category(error)
                checkpoint.redacted_diagnostic_code = _diagnostic_code(error)
                checkpoint.next_action = f"resume:{checkpoint.stage.value}"
                state.status = RunStatus.FAILED
                state.next_action = checkpoint.next_action
                self.store.save(state)
                return state

        state.status = RunStatus.SUCCEEDED
        state.next_action = "none"
        self.store.save(state)
        return state

    def _effects(self, state: RunState) -> StageEffects:
        if self._effects_override is not None:
            return self._effects_override
        if state.tier in {Tier.B, Tier.C} and not state.dry_run:
            return SnowflakeStageEffects()
        return NoopStageEffects()

    def _validate_partition_identities(self, definition: SourceDefinition, run_id: str) -> None:
        """Reject duplicate logical rows with a bounded disk-backed index."""
        assert isinstance(self.store, PartitionStore)
        with (
            tempfile.TemporaryDirectory(prefix="atlas-ingestion-ids-") as directory,
            closing(sqlite3.connect(str(Path(directory) / "identities.sqlite"))) as connection,
        ):
            connection.execute("PRAGMA cache_size=-2048")
            connection.execute("CREATE TABLE identities (record_id TEXT PRIMARY KEY)")
            for part in self.store.iter_partitions(run_id):
                for normalized in part.records:
                    record = normalized.get("record")
                    if not isinstance(record, dict):
                        continue
                    record_id = deterministic_record_id(
                        definition.resource_key, definition.definition_version, record
                    )
                    try:
                        connection.execute(
                            "INSERT INTO identities (record_id) VALUES (?)", (record_id,)
                        )
                    except sqlite3.IntegrityError as error:
                        raise ValueError("Duplicate logical record in normalized output") from error


class StageFailure(Exception):
    def __init__(self, category: FailureCategory, code: str, next_action: str) -> None:
        self.category = category
        self.code = code
        self.next_action = next_action
        super().__init__(code)


def _previous_stage_value(state: RunState, current: Stage) -> str | None:
    values = [checkpoint.stage.value for checkpoint in state.stages]
    try:
        index = values.index(current.value)
    except ValueError:
        return None
    if index == 0:
        return None
    return values[index - 1]


def _failure_category(error: Exception) -> FailureCategory:
    if isinstance(error, AcquisitionError):
        return FailureCategory.ACQUISITION
    if isinstance(error, QualityFailure):
        return FailureCategory.QUALITY
    if isinstance(error, PermissionError):
        return FailureCategory.PERMISSION
    error_name = type(error).__name__.casefold()
    if any(marker in error_name for marker in ("snowflake", "database", "programming")):
        return FailureCategory.WAREHOUSE
    if isinstance(error, (AssertionError, RuntimeError)):
        return FailureCategory.PROCESS
    return FailureCategory.CONFIGURATION


def _diagnostic_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(error).__name__.upper()


def _require_protected_prod_execution() -> None:
    """Require the production settings asserted by a protected workflow."""
    try:
        settings = PipelineSettings()
    except ValueError as error:
        raise PermissionError(
            "Tier C requires TOPX_ENV=prod, the governed PROD database, and "
            "ENABLE_PRODUCTION_EXECUTION=true"
        ) from error
    if settings.topx_env != "prod":
        raise PermissionError("Tier C execution requires TOPX_ENV=prod")
