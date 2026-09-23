"""Side effects for the shared ingestion state machine.

The orchestrator owns stage ordering and retry semantics.  This module owns the
environment-specific writes, which keeps Tier A tests deterministic while the
same application service can perform real DEV work in the worker container.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from ..artifacts import create_artifact
from ..redaction import redact_mapping
from ..settings import PipelineSettings
from .adapters import AcquireResult, AcquisitionArtifact
from .identity import deterministic_record_id, publisher_record_id, source_row_hash
from .types import RunState, SourceDefinition


class StageEffects(Protocol):
    def register_artifact(
        self, definition: SourceDefinition, state: RunState, acquired: AcquireResult
    ) -> dict[str, Any]: ...

    def materialize_normalized(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    def load(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    def quality(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    def publish(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class QualityFailure(RuntimeError):
    """A declared blocking quality rule failed."""

    def __init__(self, code: str, detail: dict[str, Any]) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


class NoopStageEffects:
    """Tier A and dry-run effects; no external or warehouse writes occur."""

    def register_artifact(
        self, definition: SourceDefinition, state: RunState, acquired: AcquireResult
    ) -> dict[str, Any]:
        artifacts = _acquisition_artifacts(acquired, definition.endpoint_template)
        primary = artifacts[0]
        return {
            "artifact_id": f"planned:{acquired.artifact_sha256[:32]}",
            "artifact_sha256": acquired.artifact_sha256,
            "artifact_uri": None,
            "artifacts": [
                {
                    "name": item.name,
                    "sha256": item.sha256,
                    "byte_count": len(item.payload),
                    "media_type": item.media_type,
                    "source_uri": item.source_uri,
                }
                for item in artifacts
            ],
            "primary_artifact_name": primary.name,
            "wrote": False,
        }

    def materialize_normalized(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {"record_count": len(records), "wrote": False, "mode": "planned"}

    def load(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "destination": definition.destination,
            "record_count": len(records),
            "rows_inserted": 0,
            "wrote": False,
            "mode": "planned",
        }

    def quality(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        results = evaluate_quality_rules(definition, records)
        failed = [result for result in results if result["status"] == "FAILED"]
        if failed:
            raise QualityFailure(str(failed[0]["rule_id"]), failed[0])
        return {"rules_evaluated": results, "wrote": False}

    def publish(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "status": "STAGED",
            "record_count": len(records),
            "target_relation": definition.destination,
            "wrote": False,
            "publication_protected": state.tier.value == "C",
        }


class SnowflakeStageEffects:
    """Private artifact plus V069 generic RAW/STAGING/CONFORMED writes."""

    def __init__(
        self,
        settings: PipelineSettings | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
        spaces_client: Any | None = None,
    ) -> None:
        self.settings = settings or PipelineSettings()
        self._connection_factory = connection_factory or (lambda: connect(SnowflakeSettings()))
        self._spaces_client = spaces_client

    def register_artifact(
        self, definition: SourceDefinition, state: RunState, acquired: AcquireResult
    ) -> dict[str, Any]:
        artifacts = _acquisition_artifacts(acquired, definition.endpoint_template)
        if artifacts[0].sha256 != acquired.artifact_sha256:
            raise ValueError("acquisition package checksum does not match primary artifact bytes")
        now = datetime.now(UTC)
        retained: list[dict[str, Any]] = []
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                for sequence, source_artifact in enumerate(artifacts, start=1):
                    artifact = create_artifact(
                        payload=source_artifact.payload,
                        environment=self.settings.topx_env,
                        resource_key=definition.resource_key,
                        run_id=state.ingestion_run_id,
                    )
                    key = f"{self.settings.spaces_prefix}/{artifact.object_key}"
                    self._spaces().put_object(
                        Bucket=self.settings.spaces_bucket,
                        Key=key,
                        Body=source_artifact.payload,
                        ContentType=source_artifact.media_type,
                    )
                    artifact_id = f"{definition.resource_key}:{artifact.sha256[:32]}"
                    request_id = f"{state.ingestion_run_id}:ACQUIRE:{sequence}"
                    cursor.execute(
                        """MERGE INTO GOVERNANCE.INGESTION_REQUESTS target
                    USING (SELECT %s AS ingestion_request_id, %s AS ingestion_run_id,
                                  1 AS request_sequence, 'SOURCE_ACQUIRE' AS request_purpose,
                                  %s AS endpoint, PARSE_JSON(%s) AS redacted_request,
                                  200 AS status_code, %s AS response_sha256,
                                  %s AS retrieved_row_count, %s AS created_at) source
                    ON target.ingestion_request_id=source.ingestion_request_id
                    WHEN NOT MATCHED THEN INSERT
                      (ingestion_request_id, ingestion_run_id, request_sequence,
                       request_purpose, endpoint, redacted_request, status_code,
                       response_sha256, retrieved_row_count, created_at)
                      VALUES (source.ingestion_request_id, source.ingestion_run_id,
                              source.request_sequence, source.request_purpose,
                              source.endpoint, source.redacted_request, source.status_code,
                              source.response_sha256, source.retrieved_row_count,
                              source.created_at)""",
                        (
                            request_id,
                            state.ingestion_run_id,
                            sequence,
                            source_artifact.request_purpose,
                            source_artifact.source_uri,
                            json.dumps(
                                redact_mapping(
                                    {
                                        "order": definition.deterministic_order_clause,
                                        "page_size": definition.page_size,
                                    }
                                )
                            ),
                            artifact.sha256,
                            source_artifact.row_count,
                            now,
                        ),
                    )
                    cursor.execute(
                        """MERGE INTO GOVERNANCE.RAW_ARTIFACTS target
                    USING (SELECT %s AS artifact_id, %s AS ingestion_run_id,
                                  %s AS ingestion_request_id, %s AS artifact_uri,
                                  'SOURCE_PAYLOAD' AS artifact_type, %s AS media_type,
                                  %s AS byte_count, %s AS sha256, %s AS retention_class,
                                  %s AS created_at) source
                    ON target.artifact_id=source.artifact_id
                    WHEN NOT MATCHED THEN INSERT
                      (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri,
                       artifact_type, media_type, byte_count, sha256, retention_class, created_at)
                      VALUES (source.artifact_id, source.ingestion_run_id,
                              source.ingestion_request_id, source.artifact_uri,
                              source.artifact_type, source.media_type, source.byte_count,
                              source.sha256, source.retention_class, source.created_at)""",
                        (
                            artifact_id,
                            state.ingestion_run_id,
                            request_id,
                            f"s3://{self.settings.spaces_bucket}/{key}",
                            "SOURCE_PACKAGE_MEMBER" if len(artifacts) > 1 else "SOURCE_PAYLOAD",
                            source_artifact.media_type,
                            artifact.byte_count,
                            artifact.sha256,
                            definition.artifact_policy,
                            now,
                        ),
                    )
                    retained.append(
                        {
                            "name": source_artifact.name,
                            "artifact_id": artifact_id,
                            "sha256": artifact.sha256,
                            "byte_count": artifact.byte_count,
                            "media_type": source_artifact.media_type,
                            "source_uri": source_artifact.source_uri,
                            "artifact_uri": f"s3://{self.settings.spaces_bucket}/{key}",
                        }
                    )
            connection.commit()
        primary = retained[0]
        return {
            "artifact_id": primary["artifact_id"],
            "artifact_sha256": primary["sha256"],
            "artifact_uri": primary["artifact_uri"],
            "byte_count": primary["byte_count"],
            "artifacts": retained,
            "primary_artifact_name": primary["name"],
            "wrote": True,
        }

    def materialize_normalized(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        rows = _lineage_rows(definition, state, records)
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                staging_batches = _execute_upsert_batches(
                    cursor, "STAGING.GOVERNED_SOURCE_RECORDS", "normalized_at", rows
                )
                conformed_batches = _execute_upsert_batches(
                    cursor, "CONFORMED.GOVERNED_SOURCE_RECORDS", "conformed_at", rows
                )
            connection.commit()
        return {
            "record_count": len(rows),
            "rows_inserted": len(rows),
            "batches": staging_batches + conformed_batches,
            "wrote": True,
        }

    def load(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        rows = _lineage_rows(definition, state, records)
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                batches = _execute_upsert_batches(
                    cursor, "RAW.GOVERNED_SOURCE_RECORDS", "loaded_at", rows
                )
            connection.commit()
        return {
            "destination": definition.destination,
            "record_count": len(rows),
            "rows_inserted": len(rows),
            "batches": batches,
            "physical_relation": "RAW.GOVERNED_SOURCE_RECORDS",
            "wrote": True,
        }

    def quality(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        results = evaluate_quality_rules(definition, records)
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                for result in results:
                    result_id = _stable_id(f"quality:{state.ingestion_run_id}:{result['rule_id']}")
                    cursor.execute(
                        """MERGE INTO GOVERNANCE.DATA_QUALITY_RESULTS target
                        USING (SELECT %s AS data_quality_result_id, %s AS ingestion_run_id,
                                      %s AS rule_id, %s AS severity, %s AS status,
                                      PARSE_JSON(%s) AS expected_value,
                                      PARSE_JSON(%s) AS observed_value,
                                      CURRENT_TIMESTAMP() AS created_at) source
                        ON target.data_quality_result_id=source.data_quality_result_id
                        WHEN NOT MATCHED THEN INSERT
                          (data_quality_result_id, ingestion_run_id, rule_id, severity,
                           status, expected_value, observed_value, created_at)
                          VALUES (source.data_quality_result_id, source.ingestion_run_id,
                                  source.rule_id, source.severity, source.status,
                                  source.expected_value, source.observed_value,
                                  source.created_at)""",
                        (
                            result_id,
                            state.ingestion_run_id,
                            result["rule_id"],
                            result["severity"],
                            result["status"],
                            json.dumps(result.get("expected")),
                            json.dumps(result.get("observed")),
                        ),
                    )
            connection.commit()
        failed = [result for result in results if result["status"] == "FAILED"]
        if failed:
            raise QualityFailure(str(failed[0]["rule_id"]), failed[0])
        return {"rules_evaluated": results, "wrote": True}

    def publish(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        publication_id = _stable_id(f"publication:{state.ingestion_run_id}")
        lineage = {
            "source_id": definition.source_id,
            "dataset_id": definition.dataset_id,
            "source_definition_version": definition.definition_version,
            "ingestion_run_id": state.ingestion_run_id,
            "transformation_version": "adapter-normalization-v2",
        }
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                cursor.execute(
                    """MERGE INTO GOVERNANCE.INGESTION_PUBLICATIONS target
                    USING (SELECT %s AS publication_id, %s AS resource_key,
                                  %s AS ingestion_run_id, %s AS source_definition_version,
                                  'STAGED' AS status, %s AS target_relation,
                                  %s AS record_count, PARSE_JSON(%s) AS lineage,
                                  CURRENT_TIMESTAMP() AS published_at) source
                    ON target.publication_id=source.publication_id
                    WHEN NOT MATCHED THEN INSERT
                      (publication_id, resource_key, ingestion_run_id,
                       source_definition_version, status, target_relation,
                       record_count, lineage, published_at)
                      VALUES (source.publication_id, source.resource_key,
                              source.ingestion_run_id, source.source_definition_version,
                              source.status, source.target_relation, source.record_count,
                              source.lineage, source.published_at)""",
                    (
                        publication_id,
                        definition.resource_key,
                        state.ingestion_run_id,
                        definition.definition_version,
                        definition.destination,
                        len(records),
                        json.dumps(lineage, separators=(",", ":")),
                    ),
                )
            connection.commit()
        return {
            "status": "STAGED",
            "publication_id": publication_id,
            "target_relation": definition.destination,
            "record_count": len(records),
            "wrote": True,
        }

    def _spaces(self) -> Any:
        if self._spaces_client is not None:
            return self._spaces_client
        if (
            self.settings.spaces_access_key_id is None
            or self.settings.spaces_secret_access_key is None
        ):
            raise ValueError("Spaces credentials are required")
        self._spaces_client = boto3.client(
            "s3",
            endpoint_url=self.settings.spaces_endpoint,
            aws_access_key_id=self.settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=self.settings.spaces_secret_access_key.get_secret_value(),
            region_name=self.settings.spaces_region,
            config=Config(signature_version="s3v4"),
        )
        return self._spaces_client


def evaluate_quality_rules(
    definition: SourceDefinition, records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Evaluate the small rule vocabulary used by the committed definitions."""
    results: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for row in records:
        source_row = row.get("record")
        if isinstance(source_row, dict):
            source_rows.append(source_row)
    for rule in definition.quality_rules:
        rule_id = rule.rule_id.casefold()
        observed: Any = len(source_rows)
        passed = bool(source_rows)
        expected: Any = "at_least_one_record"
        if "geography" in rule_id:
            keys = (
                "fips",
                "FIPS",
                "FIPSCode",
                "county_fips",
                "geography",
                "STCNTY",
                "GEOID",
            )
            missing_geography = sum(
                not any(row.get(key) not in (None, "") for key in keys) for row in source_rows
            )
            observed = {
                "record_count": len(source_rows),
                "missing_geography": missing_geography,
            }
            expected = {"missing_geography": 0}
            passed = bool(source_rows) and missing_geography == 0
        elif "value_state" in rule_id or "preservation" in rule_id:
            observed = {
                "record_count": len(source_rows),
                "raw_rows_preserved": len(source_rows) == len(records),
            }
            expected = {"raw_rows_preserved": True}
            passed = len(source_rows) == len(records) and bool(records)
        elif "era" in rule_id and definition.extra.get("minimum_year") is not None:
            minimum = int(definition.extra["minimum_year"])
            maximum = int(definition.extra["maximum_year"])
            invalid_years = []
            for row in source_rows:
                try:
                    year = int(str(row.get("year")))
                except (TypeError, ValueError):
                    invalid_years.append(row.get("year"))
                    continue
                if not minimum <= year <= maximum:
                    invalid_years.append(year)
            observed = {"invalid_years": invalid_years}
            expected = {"invalid_years": []}
            passed = not invalid_years and bool(source_rows)
        elif "required" in rule_id and definition.required_columns:
            missing_columns = [
                column
                for column in definition.required_columns
                if not all(column in row for row in source_rows)
            ]
            observed = {"missing_columns": missing_columns}
            expected = {"missing_columns": []}
            passed = not missing_columns and bool(source_rows)
        elif "geometry" in rule_id:
            invalid_geometry = []
            for index, row in enumerate(source_rows):
                geometry = row.get("geometry")
                if not isinstance(geometry, dict) or geometry.get("type") not in {
                    "Polygon",
                    "MultiPolygon",
                }:
                    invalid_geometry.append(index)
            observed = {"invalid_geometry": len(invalid_geometry)}
            expected = {"invalid_geometry": 0}
            passed = bool(source_rows) and not invalid_geometry
        results.append(
            {
                "rule_id": rule.rule_id,
                "severity": rule.severity,
                "status": "PASSED" if passed else "FAILED",
                "expected": expected,
                "observed": observed,
            }
        )
    return results


def _acquisition_artifacts(
    acquired: AcquireResult, default_source_uri: str
) -> tuple[AcquisitionArtifact, ...]:
    """Return a backward-compatible, source-faithful acquisition artifact set.

    Adapters that acquire one response continue to use the synthetic single
    member. Package adapters supply every immutable member explicitly, with
    their package manifest first so checkpoints have one stable primary ID.
    """
    if acquired.artifacts:
        return acquired.artifacts
    raw = acquired.raw_payload
    if raw is None:
        raw = json.dumps(
            acquired.payload, separators=(",", ":"), sort_keys=True, default=str
        ).encode()
    item = AcquisitionArtifact(
        name="source-payload",
        payload=raw,
        media_type=acquired.media_type,
        source_uri=default_source_uri,
        row_count=acquired.row_count,
    )
    if item.sha256 != acquired.artifact_sha256:
        raise ValueError("acquisition checksum does not match retained artifact bytes")
    return (item,)


def _lineage_rows(
    definition: SourceDefinition, state: RunState, records: Iterable[dict[str, Any]]
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for normalized in records:
        source_row = normalized.get("record")
        if not isinstance(source_row, dict):
            continue
        serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
        source_hash = source_row_hash(source_row)
        source_record_id = publisher_record_id(source_row)
        record_id = deterministic_record_id(
            definition.resource_key, definition.definition_version, source_row
        )
        rows.append(
            (
                record_id,
                definition.source_id,
                definition.dataset_id,
                definition.resource_key,
                definition.definition_version,
                state.ingestion_run_id,
                str(source_record_id) if source_record_id is not None else None,
                source_hash,
                serialized,
                datetime.now(UTC),
            )
        )
    return rows


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _upsert_sql(relation: str, timestamp_column: str) -> str:
    """Build a parameterized one-or-more-row MERGE for a known relation."""
    values = ",\n    ".join("(" + ", ".join(["%s"] * 10) + ")" for _ in range(1))
    return _upsert_sql_for_values(relation, timestamp_column, values)


def _upsert_sql_for_values(relation: str, timestamp_column: str, values: str) -> str:
    """Build the shared row projection MERGE for a set of bound VALUES rows."""
    return f"""MERGE INTO {relation} target
USING (SELECT column1 AS record_id, column2 AS source_id, column3 AS dataset_id,
              column4 AS resource_key, column5 AS source_definition_version,
              column6 AS ingestion_run_id, column7 AS source_record_id,
              column8 AS source_row_hash, PARSE_JSON(column9) AS payload,
              column10 AS retrieved_at
       FROM VALUES
    {values}) source
ON target.record_id=source.record_id
WHEN MATCHED THEN UPDATE SET
  source_id=source.source_id, dataset_id=source.dataset_id,
  resource_key=source.resource_key,
  source_definition_version=source.source_definition_version,
  ingestion_run_id=source.ingestion_run_id, source_record_id=source.source_record_id,
  source_row_hash=source.source_row_hash, payload=source.payload,
  retrieved_at=source.retrieved_at, {timestamp_column}=CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (record_id, source_id, dataset_id, resource_key, source_definition_version,
   ingestion_run_id, source_record_id, source_row_hash, payload, retrieved_at,
   {timestamp_column})
  VALUES (source.record_id, source.source_id, source.dataset_id, source.resource_key,
          source.source_definition_version, source.ingestion_run_id,
           source.source_record_id, source.source_row_hash, source.payload,
           source.retrieved_at, CURRENT_TIMESTAMP())"""


_UPSERT_BATCH_SIZE = 250


def _execute_upsert_batches(
    cursor: Any,
    relation: str,
    timestamp_column: str,
    rows: list[tuple[Any, ...]],
) -> int:
    """Execute bounded multi-row MERGEs instead of one statement per source row."""
    batch_count = 0
    for start in range(0, len(rows), _UPSERT_BATCH_SIZE):
        batch = rows[start : start + _UPSERT_BATCH_SIZE]
        values = ",\n    ".join("(" + ", ".join(["%s"] * 10) + ")" for _ in batch)
        params = tuple(value for row in batch for value in row)
        cursor.execute(_upsert_sql_for_values(relation, timestamp_column, values), params)
        batch_count += 1
    return batch_count


_UPSERT_RAW_SQL = _upsert_sql("RAW.GOVERNED_SOURCE_RECORDS", "loaded_at")
_UPSERT_STAGING_SQL = _upsert_sql("STAGING.GOVERNED_SOURCE_RECORDS", "normalized_at")
_UPSERT_CONFORMED_SQL = _upsert_sql("CONFORMED.GOVERNED_SOURCE_RECORDS", "conformed_at")
