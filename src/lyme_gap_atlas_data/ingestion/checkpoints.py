"""Durable and in-memory checkpoint stores for ingestion runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .types import FailureCategory, RunState, RunStatus, Stage, StageCheckpoint, StageStatus, Tier


class CheckpointStore(Protocol):
    def save(self, state: RunState) -> None: ...

    def load(self, run_id: str) -> RunState | None: ...

    def list_runs(self) -> list[RunState]: ...


class InMemoryCheckpointStore:
    """Tier A / test store. Same RunState shape as durable storage."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def save(self, state: RunState) -> None:
        self._runs[state.ingestion_run_id] = state

    def load(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunState]:
        return list(self._runs.values())


class FileCheckpointStore:
    """Local durable store for developer loops without Snowflake."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.root / f"{run_id}.json"

    def save(self, state: RunState) -> None:
        self._path(state.ingestion_run_id).write_text(
            json.dumps(state.to_dict(), indent=2), encoding="utf-8"
        )

    def load(self, run_id: str) -> RunState | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return run_state_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self) -> list[RunState]:
        runs: list[RunState] = []
        for path in sorted(self.root.glob("*.json")):
            runs.append(run_state_from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return runs


def run_state_from_dict(payload: dict[str, object]) -> RunState:
    stages_raw = payload.get("stages") or []
    assert isinstance(stages_raw, list)
    stages: list[StageCheckpoint] = []
    for item in stages_raw:
        assert isinstance(item, dict)
        category = item.get("failure_category")
        stages.append(
            StageCheckpoint(
                stage=Stage(str(item["stage"])),
                status=StageStatus(str(item["status"])),
                attempt_count=int(item.get("attempt_count") or 0),
                artifact_id=str(item["artifact_id"]) if item.get("artifact_id") else None,
                artifact_sha256=(
                    str(item["artifact_sha256"]) if item.get("artifact_sha256") else None
                ),
                transformation_version=(
                    str(item["transformation_version"])
                    if item.get("transformation_version")
                    else None
                ),
                failure_category=FailureCategory(str(category)) if category else None,
                redacted_diagnostic_code=(
                    str(item["redacted_diagnostic_code"])
                    if item.get("redacted_diagnostic_code")
                    else None
                ),
                next_action=str(item["next_action"]) if item.get("next_action") else None,
                detail=dict(item.get("detail") or {}),
            )
        )
    return RunState(
        ingestion_run_id=str(payload["ingestion_run_id"]),
        resource_key=str(payload["resource_key"]),
        source_definition_version=int(str(payload["source_definition_version"])),
        tier=Tier(str(payload["tier"])),
        status=RunStatus(str(payload["status"])),
        stages=stages,
        next_action=str(payload["next_action"]) if payload.get("next_action") else None,
        dry_run=bool(payload.get("dry_run", False)),
    )
