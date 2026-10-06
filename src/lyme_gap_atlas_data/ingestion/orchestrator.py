"""One resumable ingestion orchestrator for CLI and Actions."""

from __future__ import annotations

import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from ..intelligence_raw_runtime import FeedRawRetention, buffer_namespace
from ..settings import PipelineSettings
from .adapters import AcquisitionError, SourceAdapter, StreamingSourceAdapter, get_adapter
from .artifact_replay import ArtifactMember, validate_members
from .checkpoints import (
    ArtifactMemberStore,
    ArtifactMemberWriter,
    BinaryArtifactStore,
    CheckpointStore,
    InMemoryCheckpointStore,
    PartitionStore,
    PayloadStore,
    RawArtifactStore,
    SnowflakeCheckpointStore,
)
from .identity import deterministic_record_id
from .partitioning import NormalizedPartition, partition_records
from .runtime import (
    NoopStageEffects,
    QualityFailure,
    SnowflakeStageEffects,
    StageEffects,
    _acquisition_artifacts,
)
from .source_definition import validate_source_definition
from .types import (
    AdapterKind,
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


@runtime_checkable
class RetainedArtifactSourceAdapter(Protocol):
    """Optional adapter hook for named binary inputs from a retained run."""

    def restore_artifacts(
        self, definition: SourceDefinition, run_id: str, store: ArtifactMemberStore
    ) -> Any: ...


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
        self._raw_namespace = buffer_namespace("process")

    def _raw_failure(self, state: RunState, error: PermissionError) -> RunState:
        self._payloads.pop(state.ingestion_run_id, None)
        state.status = RunStatus.FAILED
        state.next_action = "new-approved-feed-run"
        checkpoint = next(
            (
                stage
                for stage in state.stages
                if stage.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}
            ),
            None,
        )
        if checkpoint is not None:
            checkpoint.status = StageStatus.FAILED
            checkpoint.failure_category = FailureCategory.POLICY_LICENSE
            code = str(error)
            checkpoint.redacted_diagnostic_code = (
                code
                if code.startswith("INTELLIGENCE_RAW_") and code.replace("_", "").isalnum()
                else "INTELLIGENCE_RAW_RETENTION_REQUIRED"
            )
            checkpoint.next_action = state.next_action
        self.store.save(state)
        return state

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
        try:
            return self._execute_retained(definition, state, fail_after_stage=fail_after_stage)
        except PermissionError as error:
            if str(error).startswith("INTELLIGENCE_RAW_"):
                return self._raw_failure(state, error)
            raise
        finally:
            retention = getattr(self._adapter(definition), "feed_retention", None)
            if isinstance(retention, FeedRawRetention):
                retention.release_buffer(self._raw_namespace + "/" + state.ingestion_run_id)

    def _execute_retained(
        self,
        definition: SourceDefinition,
        state: RunState,
        *,
        fail_after_stage: str | None,
    ) -> RunState:
        adapter = self._adapter(definition)
        effects = self._effects(state)
        retention: FeedRawRetention | None = getattr(adapter, "feed_retention", None)
        acquired_checkpoint = state.checkpoint(Stage.ACQUIRE)
        retained_feed = definition.adapter_kind is AdapterKind.RSS_ATOM
        restore_feed = bool(
            acquired_checkpoint and acquired_checkpoint.status is StageStatus.COMPLETED
        )
        try:
            if retained_feed and not state.dry_run:
                if retention is None and self.fixture_dir is None:
                    raise PermissionError("INTELLIGENCE_RAW_RETENTION_REQUIRED")
                if isinstance(retention, FeedRawRetention):
                    if id(getattr(self.store, "feed_retention", None)) != id(retention):
                        raise PermissionError("INTELLIGENCE_RAW_CHECKPOINTS_REQUIRED")
                    adapter.bind_run_source(definition, state.ingestion_run_id)  # type: ignore[attr-defined]
                    if restore_feed:
                        retention.require_run(state.ingestion_run_id)
        except PermissionError as error:
            return self._raw_failure(state, error)
        streaming = isinstance(adapter, StreamingSourceAdapter)
        if streaming and not isinstance(self.store, PartitionStore):
            raise TypeError("Streaming adapter requires a partition checkpoint store")
        if retention is not None and state.ingestion_run_id in self._payloads:
            try:
                with retention.copy_access(
                    state.ingestion_run_id,
                    "process_payload",
                    self._raw_namespace + "/" + state.ingestion_run_id,
                ):
                    payload = self._payloads[state.ingestion_run_id]
            except PermissionError as error:
                return self._raw_failure(state, error)
        else:
            payload = self._payloads.get(state.ingestion_run_id)
        recovered_acquisition = None
        recover_payload = getattr(self.store, "recover_acquisition_payload", None)
        if retained_feed and not restore_feed and not state.dry_run and callable(recover_payload):
            # Immutable Snowflake payload can commit before the ACQUIRE stage
            # checkpoint. Recover its original manifest, never a fresh attempt.
            payload = recover_payload(state.ingestion_run_id)
            if payload is not None:
                if not adapter.validate_payload(definition, payload).ok:
                    raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
                recovered_acquisition = effects.recover_acquisition(  # type: ignore[attr-defined]
                    definition, state, payload
                )
                restore_feed = True
        normalized = self._normalized.get(state.ingestion_run_id)
        member_adapter = isinstance(adapter, RetainedArtifactSourceAdapter)
        has_members = bool(
            acquired_checkpoint is not None
            and isinstance(acquired_checkpoint.detail.get("artifacts"), list)
            and len(acquired_checkpoint.detail["artifacts"]) > 1
        )
        if (
            payload is None
            and (not retained_feed or restore_feed)
            and not (member_adapter and has_members)
            and isinstance(self.store, PayloadStore)
        ):
            if (
                definition.adapter_kind is AdapterKind.RETAINED_ANNUAL_NLCD_AGGREGATE
                and restore_feed
                and isinstance(self.store, RawArtifactStore)
            ):
                # Snowflake VARIANT can alter decimal serialization in the old
                # convenience checkpoint. Replay the real, checksum-verified
                # captured artifact for this exact retained scientific cohort.
                source_bytes = self.store.load_source_artifact(state.ingestion_run_id)
                if source_bytes is None:
                    raise ValueError("Retained NLCD source artifact is missing or ambiguous")
                payload = adapter.restore_raw_payload(definition, source_bytes)
            else:
                payload = self.store.load_payload(state.ingestion_run_id)
        if (
            payload is None
            and (not retained_feed or restore_feed)
            and not (member_adapter and has_members)
            and isinstance(self.store, BinaryArtifactStore)
        ):
            raw_binary = self.store.load_binary_artifact(state.ingestion_run_id)
            if raw_binary is not None:
                payload = adapter.restore_raw_payload(definition, raw_binary)
        if (
            payload is None
            and (not retained_feed or restore_feed)
            and not (member_adapter and has_members)
            and isinstance(self.store, RawArtifactStore)
        ):
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
                if retention is not None and checkpoint.stage is not Stage.ACQUIRE and restore_feed:
                    retention.require_run(state.ingestion_run_id)
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
                    if recovered_acquisition is not None:
                        checkpoint.artifact_id = recovered_acquisition["artifact_id"]
                        checkpoint.artifact_sha256 = recovered_acquisition["artifact_sha256"]
                        checkpoint.detail = recovered_acquisition
                    elif state.dry_run and self.fixture_dir is None:
                        checkpoint.detail = {
                            "planned": True,
                            "endpoint": definition.endpoint_template,
                        }
                        checkpoint.artifact_sha256 = "dry-run"
                    else:
                        acquired = adapter.acquire(definition, fixture_dir=self.fixture_dir)
                        payload = acquired.payload
                        source_members = _acquisition_artifacts(
                            acquired, definition.endpoint_template
                        )
                        artifact = effects.register_artifact(definition, state, acquired)
                        if isinstance(payload, dict):
                            payload["_acquisition_lineage"] = {
                                "ingestion_run_id": state.ingestion_run_id,
                                "artifact_id": artifact["artifact_id"],
                                "retrieved_at": datetime.now(UTC).isoformat(),
                            }
                        if retention is not None:
                            retention.bind(state.ingestion_run_id, payload)
                            retention.register_buffer(
                                self._raw_namespace + "/" + state.ingestion_run_id,
                                lambda: (
                                    self._payloads.pop(state.ingestion_run_id, None) is not None
                                ),
                            )
                            with retention.copy_access(
                                state.ingestion_run_id,
                                "process_payload",
                                self._raw_namespace + "/" + state.ingestion_run_id,
                                write=True,
                            ):
                                self._payloads[state.ingestion_run_id] = payload
                            restore_feed = True
                        else:
                            self._payloads[state.ingestion_run_id] = payload
                        if len(source_members) > 1 and isinstance(self.store, ArtifactMemberWriter):
                            metadata = validate_members(
                                ArtifactMember.from_dict(item) for item in artifact["artifacts"]
                            )
                            by_name = {item.name: item for item in source_members}
                            for member in metadata:
                                self.store.save_artifact_member(
                                    member, by_name[member.name].payload
                                )
                        elif (
                            len(source_members) > 1
                            and member_adapter
                            and not isinstance(self.store, ArtifactMemberStore)
                        ):
                            raise TypeError("Named replay requires an artifact member store")
                        if isinstance(payload, bytes) and len(source_members) == 1:
                            if isinstance(self.store, BinaryArtifactStore):
                                self.store.save_binary_artifact(
                                    state.ingestion_run_id, payload, acquired.artifact_sha256
                                )
                            elif not isinstance(self.store, RawArtifactStore):
                                raise TypeError(
                                    "Binary replay requires an artifact checkpoint store"
                                )
                        elif isinstance(self.store, PayloadStore) and not (
                            member_adapter and len(source_members) > 1
                        ):
                            self.store.save_payload(state.ingestion_run_id, payload)
                        checkpoint.artifact_id = str(artifact["artifact_id"])
                        checkpoint.artifact_sha256 = str(artifact["artifact_sha256"])
                        checkpoint.detail = {
                            "row_count": acquired.row_count,
                            "media_type": acquired.media_type,
                            **(acquired.detail or {}),
                            **artifact,
                        }
                        if member_adapter and len(source_members) > 1:
                            has_members = True
                            payload = None
                            self._payloads.pop(state.ingestion_run_id, None)
                elif checkpoint.stage is Stage.VALIDATE:
                    if member_adapter and has_members:
                        payload = self._restore_member_payload(adapter, definition, state)
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
                    if payload is None and member_adapter and has_members:
                        payload = self._restore_member_payload(adapter, definition, state)
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
                                pending: list[NormalizedPartition] = []
                                for part in partition_records(streamed.records):
                                    if isinstance(self.store, SnowflakeCheckpointStore):
                                        pending.append(part)
                                        if len(pending) == 64:
                                            self._save_partition_batch(
                                                state.ingestion_run_id, pending
                                            )
                                            pending = []
                                    else:
                                        self.store.save_partition(state.ingestion_run_id, part)
                                    count += 1
                                self._save_partition_batch(state.ingestion_run_id, pending)
                                self._validate_partition_identities(
                                    definition, state.ingestion_run_id
                                )
                                self.store.complete_partitions(state.ingestion_run_id, count)
                            partition_count = 0
                            record_count = 0
                            pending_records: list[list[dict[str, Any]]] = []
                            for part in self.store.iter_partitions(state.ingestion_run_id):
                                pending_records.append(list(part.records))
                                partition_count += 1
                                record_count += len(part.records)
                                if len(pending_records) == 64:
                                    self._materialize_batch(
                                        effects, definition, state, pending_records
                                    )
                                    pending_records = []
                            self._materialize_batch(effects, definition, state, pending_records)
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
                        pending_records = []
                        for part in self.store.iter_partitions(state.ingestion_run_id):
                            pending_records.append(list(part.records))
                            loaded += len(part.records)
                            if len(pending_records) == 64:
                                self._load_batch(effects, definition, state, pending_records)
                                pending_records = []
                        self._load_batch(effects, definition, state, pending_records)
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
                if isinstance(error, PermissionError) and str(error).startswith(
                    "INTELLIGENCE_RAW_"
                ):
                    return self._raw_failure(state, error)
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

    def _save_partition_batch(self, run_id: str, partitions: list[NormalizedPartition]) -> None:
        if not partitions:
            return
        if isinstance(self.store, SnowflakeCheckpointStore):
            self.store.save_bulk_partition_batch(run_id, partitions)
        else:
            for part in partitions:
                cast(PartitionStore, self.store).save_partition(run_id, part)

    @staticmethod
    def _materialize_batch(
        effects: StageEffects,
        definition: SourceDefinition,
        state: RunState,
        partitions: list[list[dict[str, Any]]],
    ) -> None:
        if isinstance(effects, SnowflakeStageEffects):
            if partitions:
                effects.materialize_bulk_batch(definition, state, partitions)
        else:
            for records in partitions:
                effects.materialize_normalized(definition, state, records)

    @staticmethod
    def _load_batch(
        effects: StageEffects,
        definition: SourceDefinition,
        state: RunState,
        partitions: list[list[dict[str, Any]]],
    ) -> None:
        if isinstance(effects, SnowflakeStageEffects):
            if partitions:
                effects.load_bulk_batch(definition, state, partitions)
        else:
            for records in partitions:
                effects.load(definition, state, records)

    def _effects(self, state: RunState) -> StageEffects:
        if self._effects_override is not None:
            return self._effects_override
        if state.tier in {Tier.B, Tier.C} and not state.dry_run:
            return SnowflakeStageEffects()
        return NoopStageEffects()

    def _restore_member_payload(
        self, adapter: SourceAdapter, definition: SourceDefinition, state: RunState
    ) -> Any:
        if not isinstance(adapter, RetainedArtifactSourceAdapter):
            raise TypeError("Adapter does not support retained artifact members")
        if not isinstance(self.store, ArtifactMemberStore):
            raise TypeError("Named replay requires an artifact member store")
        checkpoint = state.checkpoint(Stage.ACQUIRE)
        if checkpoint is None:
            raise ValueError("ACQUIRE checkpoint is missing")
        expected = validate_members(
            ArtifactMember.from_dict(item) for item in checkpoint.detail["artifacts"]
        )
        observed = self.store.list_artifact_members(state.ingestion_run_id)
        if expected != observed:
            raise ValueError("Retained artifact member set mismatch")
        for member in expected:
            self.store.load_artifact_member(state.ingestion_run_id, name=member.name)
        return adapter.restore_artifacts(definition, state.ingestion_run_id, self.store)

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
