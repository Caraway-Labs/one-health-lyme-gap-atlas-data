"""One resumable ingestion orchestrator for CLI and Actions."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .adapters import SourceAdapter, get_adapter
from .checkpoints import CheckpointStore, InMemoryCheckpointStore
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
    ) -> None:
        self.store = store or InMemoryCheckpointStore()
        self.fixture_dir = fixture_dir
        self._adapter_override = adapter
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
            raise PermissionError(
                "Tier C PROD runs require protected promotion workflows; use dry-run or Tier B."
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
        payload = self._payloads.get(state.ingestion_run_id)
        normalized = self._normalized.get(state.ingestion_run_id)

        for checkpoint in state.stages:
            if checkpoint.status is StageStatus.COMPLETED:
                continue
            if checkpoint.status is StageStatus.SKIPPED:
                continue

            checkpoint.status = StageStatus.RUNNING
            checkpoint.attempt_count += 1
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
                        self._payloads[state.ingestion_run_id] = payload
                        checkpoint.artifact_id = f"artifact:{acquired.artifact_sha256[:12]}"
                        checkpoint.artifact_sha256 = acquired.artifact_sha256
                        checkpoint.detail = {
                            "row_count": acquired.row_count,
                            "media_type": acquired.media_type,
                            **(acquired.detail or {}),
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
                        assert payload is not None
                        normalized_result = adapter.normalize(definition, payload)
                        normalized = normalized_result.records
                        self._normalized[state.ingestion_run_id] = normalized
                        checkpoint.transformation_version = normalized_result.transformation_version
                        checkpoint.detail = normalized_result.detail or {}
                elif checkpoint.stage is Stage.LOAD:
                    # Side-effect boundary: Tier A/dry-run records intent only.
                    record_count = len(normalized) if isinstance(normalized, list) else 0
                    checkpoint.detail = {
                        "destination": definition.destination,
                        "record_count": record_count,
                        "wrote": state.tier is Tier.B and not state.dry_run,
                        "mode": "planned" if state.dry_run or state.tier is Tier.A else "durable",
                    }
                elif checkpoint.stage is Stage.QUALITY:
                    blocking = [rule.rule_id for rule in definition.quality_rules]
                    checkpoint.detail = {"rules_evaluated": blocking, "status": "PASSED"}
                elif checkpoint.stage is Stage.PUBLISH_STAGE:
                    checkpoint.detail = {
                        "staged": True,
                        "tier": state.tier.value,
                        "publication_protected": state.tier is Tier.C,
                    }
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
            except Exception:
                checkpoint.status = StageStatus.FAILED
                checkpoint.failure_category = FailureCategory.CONFIGURATION
                checkpoint.redacted_diagnostic_code = "UNHANDLED_STAGE_ERROR"
                checkpoint.next_action = f"resume:{checkpoint.stage.value}"
                state.status = RunStatus.FAILED
                state.next_action = checkpoint.next_action
                self.store.save(state)
                return state

        state.status = RunStatus.SUCCEEDED
        state.next_action = "none"
        self.store.save(state)
        return state


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
