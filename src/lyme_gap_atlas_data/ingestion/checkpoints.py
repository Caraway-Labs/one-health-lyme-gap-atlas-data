"""Durable and in-memory checkpoint stores for ingestion runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable
from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from ..settings import PipelineSettings
from .types import FailureCategory, RunState, RunStatus, Stage, StageCheckpoint, StageStatus, Tier


class CheckpointStore(Protocol):
    def save(self, state: RunState) -> None: ...

    def load(self, run_id: str) -> RunState | None: ...

    def list_runs(self) -> list[RunState]: ...


@runtime_checkable
class PayloadStore(Protocol):
    def save_payload(self, run_id: str, payload: object) -> None: ...

    def load_payload(self, run_id: str) -> object | None: ...

    def save_normalized(self, run_id: str, records: list[dict[str, object]]) -> None: ...

    def load_normalized(self, run_id: str) -> list[dict[str, object]] | None: ...


@runtime_checkable
class RawArtifactStore(Protocol):
    def load_source_artifact(self, run_id: str) -> bytes | None: ...


class InMemoryCheckpointStore:
    """Tier A / test store. Same RunState shape as durable storage."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._payloads: dict[str, object] = {}
        self._normalized: dict[str, list[dict[str, object]]] = {}

    def save(self, state: RunState) -> None:
        self._runs[state.ingestion_run_id] = state

    def load(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunState]:
        return list(self._runs.values())

    def save_payload(self, run_id: str, payload: object) -> None:
        self._payloads[run_id] = payload

    def load_payload(self, run_id: str) -> object | None:
        return self._payloads.get(run_id)

    def save_normalized(self, run_id: str, records: list[dict[str, object]]) -> None:
        self._normalized[run_id] = records

    def load_normalized(self, run_id: str) -> list[dict[str, object]] | None:
        return self._normalized.get(run_id)


class FileCheckpointStore:
    """Local durable store for developer loops without Snowflake."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _payload_path(self, run_id: str, suffix: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            raise ValueError("Invalid ingestion_run_id")
        return self.root / f"{run_id}.{suffix}.json"

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            raise ValueError("Invalid ingestion_run_id")
        return self.root / f"{run_id}.json"

    def _write_json(self, path: Path, payload: object) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, indent=2, separators=(",", ":"), default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, state: RunState) -> None:
        self._write_json(self._path(state.ingestion_run_id), state.to_dict())

    def load(self, run_id: str) -> RunState | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return run_state_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self) -> list[RunState]:
        runs: list[RunState] = []
        for path in sorted(self.root.glob("*.json")):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}\.json", path.name):
                continue
            runs.append(run_state_from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return runs

    def save_payload(self, run_id: str, payload: object) -> None:
        self._write_json(self._payload_path(run_id, "payload"), payload)

    def load_payload(self, run_id: str) -> object | None:
        path = self._payload_path(run_id, "payload")
        if not path.exists():
            return None
        return cast(object, json.loads(path.read_text(encoding="utf-8")))

    def save_normalized(self, run_id: str, records: list[dict[str, object]]) -> None:
        self._write_json(self._payload_path(run_id, "normalized"), records)

    def load_normalized(self, run_id: str) -> list[dict[str, object]] | None:
        path = self._payload_path(run_id, "normalized")
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Persisted normalized payload is not a list")
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError("Persisted normalized payload contains a non-object row")
        return [dict(item) for item in payload]


class SnowflakeCheckpointStore:
    """V068/V070-backed checkpoint store used by DEV/PROD worker containers."""

    def __init__(
        self,
        connection_factory: Callable[[], Any] | None = None,
        *,
        spaces_client: Any | None = None,
        settings: PipelineSettings | None = None,
    ) -> None:
        self._connection_factory = connection_factory or (lambda: connect(SnowflakeSettings()))
        self._spaces_client = spaces_client
        self._settings = settings

    def load_source_artifact(self, run_id: str) -> bytes | None:
        """Recover source-faithful bytes when a pre-V070 run needs resume."""
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT artifact_uri, sha256 FROM GOVERNANCE.RAW_ARTIFACTS
                    WHERE ingestion_run_id=%s AND artifact_type='SOURCE_PAYLOAD'
                    ORDER BY created_at LIMIT 1""",
                (run_id,),
            )
            artifact = cursor.fetchone()
        if artifact is None:
            return None
        parsed = urlsplit(str(artifact[0]))
        settings = self._pipeline_settings()
        if parsed.scheme != "s3" or parsed.netloc != settings.spaces_bucket or not parsed.path:
            raise ValueError("Source artifact is outside the configured private bucket")
        key = parsed.path.lstrip("/")
        if not key.startswith(f"{settings.spaces_prefix}/"):
            raise ValueError("Source artifact is outside the configured environment prefix")
        response = self._spaces().get_object(Bucket=parsed.netloc, Key=key)
        body = response["Body"].read()
        if _sha256_bytes(body) != str(artifact[1]):
            raise ValueError("Source artifact checksum mismatch")
        return cast(bytes, body)

    def _pipeline_settings(self) -> PipelineSettings:
        if self._settings is None:
            self._settings = PipelineSettings()
        return self._settings

    def _spaces(self) -> Any:
        if self._spaces_client is not None:
            return self._spaces_client
        settings = self._pipeline_settings()
        if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
            raise ValueError("Spaces credentials are required to recover a source artifact")
        self._spaces_client = boto3.client(
            "s3",
            endpoint_url=settings.spaces_endpoint,
            aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
            region_name=settings.spaces_region,
            config=Config(signature_version="s3v4"),
        )
        return self._spaces_client

    def save_payload(self, run_id: str, payload: object) -> None:
        """Persist the acquired canonical payload without permitting replacement."""
        self._save_json_document(
            table="INGESTION_RUN_PAYLOADS",
            value_column="payload",
            run_id=run_id,
            value=payload,
        )

    def load_payload(self, run_id: str) -> object | None:
        """Load and checksum-verify a payload saved by a prior worker process."""
        return self._load_json_document(
            table="INGESTION_RUN_PAYLOADS", value_column="payload", run_id=run_id
        )

    def save_normalized(self, run_id: str, records: list[dict[str, object]]) -> None:
        """Persist normalized rows without permitting replacement."""
        self._save_json_document(
            table="INGESTION_RUN_NORMALIZED",
            value_column="records",
            run_id=run_id,
            value=records,
        )

    def load_normalized(self, run_id: str) -> list[dict[str, object]] | None:
        """Load and checksum-verify normalized rows saved by a prior process."""
        value = self._load_json_document(
            table="INGESTION_RUN_NORMALIZED", value_column="records", run_id=run_id
        )
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("Persisted normalized payload is not a list")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError("Persisted normalized payload contains a non-object row")
        return [dict(item) for item in value]

    def _save_json_document(
        self, *, table: str, value_column: str, run_id: str, value: object
    ) -> None:
        serialized = _serialize_json(value)
        digest = _sha256(serialized)
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""MERGE INTO GOVERNANCE.{table} target
                    USING (SELECT %s AS ingestion_run_id, PARSE_JSON(%s) AS {value_column},
                                  %s AS value_sha256) source
                    ON target.ingestion_run_id=source.ingestion_run_id
                    WHEN NOT MATCHED THEN INSERT
                      (ingestion_run_id, {value_column}, value_sha256, created_at)
                      VALUES (source.ingestion_run_id, source.{value_column},
                              source.value_sha256, CURRENT_TIMESTAMP())""",
                    (run_id, serialized, digest),
                )
                cursor.execute(
                    f"""SELECT value_sha256 FROM GOVERNANCE.{table}
                        WHERE ingestion_run_id=%s""",
                    (run_id,),
                )
                stored = cursor.fetchone()
                if stored is None or str(stored[0]) != digest:
                    raise ValueError(f"Stored {value_column} checkpoint checksum mismatch")
            connection.commit()

    def _load_json_document(self, *, table: str, value_column: str, run_id: str) -> object | None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT {value_column}, value_sha256 FROM GOVERNANCE.{table}
                    WHERE ingestion_run_id=%s""",
                (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        if isinstance(value, str):
            value = json.loads(value)
        if _sha256(_serialize_json(value)) != str(row[1]):
            raise ValueError(f"Stored {value_column} checkpoint checksum mismatch")
        return cast(object, value)

    def save(self, state: RunState) -> None:
        database_status = "COMPLETED" if state.status is RunStatus.SUCCEEDED else state.status.value
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                cursor.execute(
                    """MERGE INTO GOVERNANCE.INGESTION_RUNS target
                    USING (SELECT %s AS ingestion_run_id, %s AS resource_key,
                                  'SOURCE_INGESTION' AS run_mode, %s AS trigger_type,
                                  %s AS status, %s AS code_version,
                                  CURRENT_TIMESTAMP() AS started_at) source
                    ON target.ingestion_run_id = source.ingestion_run_id
                    WHEN MATCHED THEN UPDATE SET status=source.status,
                      completed_at=IFF(source.status IN ('COMPLETED','FAILED'),
                                       CURRENT_TIMESTAMP(), target.completed_at),
                      error_classification=IFF(source.status='FAILED',
                                               (SELECT failure_category
                                                FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS
                                                WHERE ingestion_run_id=source.ingestion_run_id
                                                ORDER BY updated_at DESC LIMIT 1), NULL)
                    WHEN NOT MATCHED THEN INSERT
                      (ingestion_run_id, resource_key, run_mode, trigger_type, status,
                       code_version, started_at)
                      VALUES (source.ingestion_run_id, source.resource_key, source.run_mode,
                              source.trigger_type, source.status, source.code_version,
                              source.started_at)""",
                    (
                        state.ingestion_run_id,
                        state.resource_key,
                        state.tier.value,
                        database_status,
                        "simplified-ingestion-v2",
                    ),
                )
                for checkpoint in state.stages:
                    cursor.execute(
                        """MERGE INTO GOVERNANCE.INGESTION_RUN_CHECKPOINTS target
                        USING (SELECT %s AS checkpoint_id, %s AS ingestion_run_id,
                                      %s AS resource_key, %s AS source_definition_version,
                                      %s AS stage, %s AS status, %s AS attempt_count,
                                      %s AS artifact_id, %s AS artifact_sha256,
                                      %s AS transformation_version, %s AS failure_category,
                                      %s AS redacted_diagnostic_code, %s AS next_action,
                                      PARSE_JSON(%s) AS detail) source
                        ON target.checkpoint_id = source.checkpoint_id
                        WHEN MATCHED THEN UPDATE SET status=source.status,
                          attempt_count=source.attempt_count, artifact_id=source.artifact_id,
                          artifact_sha256=source.artifact_sha256,
                          transformation_version=source.transformation_version,
                          failure_category=source.failure_category,
                          redacted_diagnostic_code=source.redacted_diagnostic_code,
                          next_action=source.next_action, detail=source.detail,
                          updated_at=CURRENT_TIMESTAMP(),
                          completed_at=IFF(source.status='COMPLETED',CURRENT_TIMESTAMP(),NULL)
                        WHEN NOT MATCHED THEN INSERT
                          (checkpoint_id, ingestion_run_id, resource_key,
                           source_definition_version, stage, status, attempt_count,
                           artifact_id, artifact_sha256, transformation_version,
                           failure_category, redacted_diagnostic_code, next_action, detail,
                           started_at, updated_at)
                          VALUES (source.checkpoint_id, source.ingestion_run_id,
                                  source.resource_key, source.source_definition_version,
                                  source.stage, source.status, source.attempt_count,
                                  source.artifact_id, source.artifact_sha256,
                                  source.transformation_version, source.failure_category,
                                  source.redacted_diagnostic_code, source.next_action,
                                  source.detail, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())""",
                        (
                            f"{state.ingestion_run_id}:{checkpoint.stage.value}",
                            state.ingestion_run_id,
                            state.resource_key,
                            state.source_definition_version,
                            checkpoint.stage.value,
                            checkpoint.status.value,
                            checkpoint.attempt_count,
                            checkpoint.artifact_id,
                            checkpoint.artifact_sha256,
                            checkpoint.transformation_version,
                            checkpoint.failure_category.value
                            if checkpoint.failure_category
                            else None,
                            checkpoint.redacted_diagnostic_code,
                            checkpoint.next_action,
                            json.dumps(checkpoint.detail, separators=(",", ":")),
                        ),
                    )
            connection.commit()

    def load(self, run_id: str) -> RunState | None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT ingestion_run_id, resource_key, trigger_type, status
                    FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s""",
                (run_id,),
            )
            run = cursor.fetchone()
            if run is None:
                return None
            cursor.execute(
                """SELECT source_definition_version, stage, status, attempt_count,
                    artifact_id, artifact_sha256,
                    transformation_version, failure_category, redacted_diagnostic_code,
                    next_action, detail, started_at, completed_at
                    FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS
                    WHERE ingestion_run_id=%s ORDER BY updated_at""",
                (run_id,),
            )
            rows = cursor.fetchall()
        stages = [_checkpoint_from_row(row) for row in rows]
        stages.sort(key=lambda item: list(Stage).index(item.stage))
        return RunState(
            ingestion_run_id=str(run[0]),
            resource_key=str(run[1]),
            source_definition_version=(
                int(stages[0].detail.get("source_definition_version", 1)) if stages else 1
            ),
            tier=Tier(str(run[2])),
            status=_run_status_from_database(str(run[3])),
            stages=stages,
            next_action=next(
                (item.next_action for item in reversed(stages) if item.next_action), "none"
            ),
        )

    def list_runs(self) -> list[RunState]:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT ingestion_run_id FROM GOVERNANCE.INGESTION_RUNS
                    WHERE run_mode='SOURCE_INGESTION' ORDER BY started_at DESC"""
            )
            ids = [str(row[0]) for row in cursor.fetchall()]
        return [state for run_id in ids if (state := self.load(run_id)) is not None]


def _checkpoint_from_row(row: tuple[object, ...]) -> StageCheckpoint:
    detail = row[10]
    if isinstance(detail, str):
        detail = json.loads(detail)
    detail = dict(detail or {}) if isinstance(detail, dict) else {}
    detail.setdefault("source_definition_version", int(str(row[0] or 1)))
    return StageCheckpoint(
        stage=Stage(str(row[1])),
        status=StageStatus(str(row[2])),
        attempt_count=int(str(row[3] or 0)),
        artifact_id=str(row[4]) if row[4] else None,
        artifact_sha256=str(row[5]) if row[5] else None,
        transformation_version=str(row[6]) if row[6] else None,
        failure_category=FailureCategory(str(row[7])) if row[7] else None,
        redacted_diagnostic_code=str(row[8]) if row[8] else None,
        next_action=str(row[9]) if row[9] else None,
        detail=detail,
        started_at=str(row[11]) if len(row) > 11 and row[11] else None,
        completed_at=str(row[12]) if len(row) > 12 and row[12] else None,
    )


def _run_status_from_database(value: str) -> RunStatus:
    """Map the governed table's COMPLETED value to the CLI's SUCCEEDED value."""
    return RunStatus.SUCCEEDED if value == "COMPLETED" else RunStatus(value)


def _serialize_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
                started_at=str(item["started_at"]) if item.get("started_at") else None,
                completed_at=str(item["completed_at"]) if item.get("completed_at") else None,
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
