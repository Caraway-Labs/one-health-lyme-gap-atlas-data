"""Side effects for the shared ingestion state machine.

The orchestrator owns stage ordering and retry semantics.  This module owns the
environment-specific writes, which keeps Tier A tests deterministic while the
same application service can perform real DEV work in the worker container.
"""

from __future__ import annotations

import hashlib
import json
import re
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
from .artifact_replay import ArtifactMember, validate_names
from .bulk_stage import remove_transport, stage_json_rows
from .identity import deterministic_record_id, publisher_record_id, source_row_hash
from .types import AdapterKind, RunState, SourceDefinition, Stage


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

    def quality_partitioned(
        self, definition: SourceDefinition, state: RunState, records: Iterable[dict[str, Any]]
    ) -> dict[str, Any]: ...

    def publish(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    def publish_partitioned(
        self, definition: SourceDefinition, state: RunState, record_count: int
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
        primary = _primary_artifact(acquired, artifacts)
        return {
            "artifact_id": _planned_artifact_id(
                definition.resource_key, state.ingestion_run_id, primary, len(artifacts)
            ),
            "artifact_sha256": acquired.artifact_sha256,
            "artifact_uri": None,
            "artifacts": [
                ArtifactMember(
                    state.ingestion_run_id,
                    item.name,
                    item.request_purpose,
                    _planned_artifact_id(
                        definition.resource_key, state.ingestion_run_id, item, len(artifacts)
                    ),
                    item.source_uri,
                    item.media_type,
                    item.sha256,
                    len(item.payload),
                    row_count=item.row_count,
                ).to_dict()
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
        return self._quality_result(results)

    def quality_partitioned(
        self, definition: SourceDefinition, state: RunState, records: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        return self._quality_result(evaluate_quality_rules_streaming(definition, records))

    def _quality_result(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        failed = [result for result in results if result["status"] == "FAILED"]
        if failed:
            raise QualityFailure(str(failed[0]["rule_id"]), failed[0])
        return {"rules_evaluated": results, "wrote": False}

    def publish(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.publish_partitioned(definition, state, len(records))

    def publish_partitioned(
        self, definition: SourceDefinition, state: RunState, record_count: int
    ) -> dict[str, Any]:
        return {
            "status": "STAGED",
            "record_count": record_count,
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
        if definition.adapter_kind is AdapterKind.RSS_ATOM:
            raise PermissionError("INTELLIGENCE_STORAGE_EFFECTS_REQUIRED")
        return self._register_artifact(definition, state, acquired)

    def _register_artifact(
        self,
        definition: SourceDefinition,
        state: RunState,
        acquired: AcquireResult,
        *,
        capture_identity: str | None = None,
    ) -> dict[str, Any]:
        """Explicit intelligence composition calls only after source/retention checks."""
        artifacts = _acquisition_artifacts(acquired, definition.endpoint_template)
        if capture_identity is not None and (
            definition.adapter_kind is not AdapterKind.RSS_ATOM
            or len(artifacts) != 1
            or re.fullmatch(r"[a-f0-9]{64}", capture_identity) is None
        ):
            raise PermissionError("INTELLIGENCE_CAPTURE_IDENTITY_INVALID")
        primary_source = _primary_artifact(acquired, artifacts)
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
                    request_id = (
                        f"{state.ingestion_run_id}:ACQUIRE:{sequence}"
                        if len(artifacts) == 1
                        else f"{state.ingestion_run_id}:ACQUIRE:"
                        f"{hashlib.sha256(source_artifact.name.encode()).hexdigest()[:32]}"
                    )
                    if capture_identity is not None:
                        request_id = f"{state.ingestion_run_id}:ACQUIRE:{capture_identity}"
                    # Each capture has its own immutable run/artifact link.
                    # The full SHA-256 remains the stable cross-run content identity.
                    artifact_id = _member_artifact_id(
                        definition.resource_key,
                        state.ingestion_run_id,
                        source_artifact,
                        len(artifacts),
                    )
                    if capture_identity is not None:
                        captured_key = (
                            f"{definition.resource_key}:{state.ingestion_run_id}:{capture_identity}"
                        )
                        artifact_id = f"intelligence-capture:{_stable_id(captured_key)}"
                    cursor.execute(
                        """MERGE INTO GOVERNANCE.INGESTION_REQUESTS target
                    USING (SELECT %s AS ingestion_request_id, %s AS ingestion_run_id,
                                  %s AS request_sequence, %s AS request_purpose,
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
                                  %s AS artifact_type, %s AS media_type,
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
                        ArtifactMember(
                            state.ingestion_run_id,
                            source_artifact.name,
                            source_artifact.request_purpose,
                            artifact_id,
                            source_artifact.source_uri,
                            source_artifact.media_type,
                            artifact.sha256,
                            artifact.byte_count,
                            f"s3://{self.settings.spaces_bucket}/{key}",
                            source_artifact.row_count,
                        ).to_dict()
                    )
            connection.commit()
        primary = next(item for item in retained if item["name"] == primary_source.name)
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

    def materialize_partition_batch(
        self,
        definition: SourceDefinition,
        state: RunState,
        partitions: list[list[dict[str, Any]]],
    ) -> None:
        """Reuse one transaction for a bounded set of projection partitions."""
        if len(partitions) > 8:
            raise ValueError("Projection batch exceeds eight partitions")
        if not partitions:
            return
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                for records in partitions:
                    rows = _lineage_rows(definition, state, records)
                    _execute_upsert_batches(
                        cursor, "STAGING.GOVERNED_SOURCE_RECORDS", "normalized_at", rows
                    )
                    _execute_upsert_batches(
                        cursor, "CONFORMED.GOVERNED_SOURCE_RECORDS", "conformed_at", rows
                    )
            connection.commit()

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
                artifact = state.checkpoint(Stage.ACQUIRE)
                if artifact is not None and artifact.artifact_id and artifact.artifact_sha256:
                    normalization = state.checkpoint(Stage.NORMALIZE)
                    _insert_revisions(
                        cursor,
                        rows,
                        artifact.artifact_id,
                        artifact.artifact_sha256,
                        normalization.transformation_version if normalization else None,
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

    def load_partition_batch(
        self,
        definition: SourceDefinition,
        state: RunState,
        partitions: list[list[dict[str, Any]]],
    ) -> None:
        """Commit RAW and immutable revisions together for bounded partitions."""
        if len(partitions) > 8:
            raise ValueError("Load batch exceeds eight partitions")
        if not partitions:
            return
        artifact = state.checkpoint(Stage.ACQUIRE)
        normalization = state.checkpoint(Stage.NORMALIZE)
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                for records in partitions:
                    rows = _lineage_rows(definition, state, records)
                    _execute_upsert_batches(
                        cursor, "RAW.GOVERNED_SOURCE_RECORDS", "loaded_at", rows
                    )
                    if artifact is not None and artifact.artifact_id and artifact.artifact_sha256:
                        _insert_revisions(
                            cursor,
                            rows,
                            artifact.artifact_id,
                            artifact.artifact_sha256,
                            normalization.transformation_version if normalization else None,
                        )
            connection.commit()

    def materialize_bulk_batch(
        self,
        definition: SourceDefinition,
        state: RunState,
        partitions: list[list[dict[str, Any]]],
    ) -> None:
        """Apply one staged set to both first-write projections."""
        documents = _bulk_lineage_documents(definition, state, partitions)
        if not documents:
            return
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                source = stage_json_rows(
                    cursor, run_id=state.ingestion_run_id, kind="records", rows=documents
                )
                _verify_bulk_source(cursor, source, len(documents))
                _merge_bulk_projection(
                    cursor, "STAGING.GOVERNED_SOURCE_RECORDS", "normalized_at", source
                )
                _merge_bulk_projection(
                    cursor, "CONFORMED.GOVERNED_SOURCE_RECORDS", "conformed_at", source
                )
            connection.commit()
            with connection.cursor() as cursor:
                remove_transport(cursor, source)

    def load_bulk_batch(
        self,
        definition: SourceDefinition,
        state: RunState,
        partitions: list[list[dict[str, Any]]],
    ) -> None:
        """Commit RAW and immutable captures from one bounded staged set."""
        documents = _bulk_lineage_documents(definition, state, partitions)
        if not documents:
            return
        artifact = state.checkpoint(Stage.ACQUIRE)
        normalization = state.checkpoint(Stage.NORMALIZE)
        with self._connection_factory() as connection:
            connection.autocommit(False)
            with connection.cursor() as cursor:
                source = stage_json_rows(
                    cursor, run_id=state.ingestion_run_id, kind="records", rows=documents
                )
                _verify_bulk_source(cursor, source, len(documents))
                if artifact is not None and artifact.artifact_id and artifact.artifact_sha256:
                    _check_bulk_revision_conflicts(
                        cursor,
                        source,
                        artifact.artifact_sha256,
                        normalization.transformation_version if normalization else None,
                    )
                _merge_bulk_projection(cursor, "RAW.GOVERNED_SOURCE_RECORDS", "loaded_at", source)
                if artifact is not None and artifact.artifact_id and artifact.artifact_sha256:
                    _merge_bulk_revisions(
                        cursor,
                        source,
                        artifact.artifact_id,
                        artifact.artifact_sha256,
                        normalization.transformation_version if normalization else None,
                    )
            connection.commit()
            with connection.cursor() as cursor:
                remove_transport(cursor, source)

    def quality(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        results = evaluate_quality_rules(definition, records)
        return self._quality_result(state, results)

    def quality_partitioned(
        self, definition: SourceDefinition, state: RunState, records: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        return self._quality_result(state, evaluate_quality_rules_streaming(definition, records))

    def _quality_result(self, state: RunState, results: list[dict[str, Any]]) -> dict[str, Any]:
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
        return self.publish_partitioned(definition, state, len(records))

    def publish_partitioned(
        self, definition: SourceDefinition, state: RunState, record_count: int
    ) -> dict[str, Any]:
        publication_id = _stable_id(f"publication:{state.ingestion_run_id}")
        if definition.adapter_kind is AdapterKind.RSS_ATOM:
            raise PermissionError("INTELLIGENCE_STORAGE_EFFECTS_REQUIRED")
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
                        record_count,
                        json.dumps(lineage, separators=(",", ":")),
                    ),
                )
            connection.commit()
        return {
            "status": "STAGED",
            "publication_id": publication_id,
            "target_relation": definition.destination,
            "record_count": record_count,
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


def evaluate_quality_rules_streaming(
    definition: SourceDefinition, records: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Evaluate the declared vocabulary in one pass without retaining rows."""
    total = 0
    source_count = 0
    missing_geography = 0
    invalid_year_count = 0
    invalid_year_examples: list[object] = []
    missing_columns: set[str] = set()
    geography_keys = ("fips", "FIPS", "FIPSCode", "county_fips", "geography", "STCNTY", "GEOID")
    minimum = definition.extra.get("minimum_year")
    maximum = definition.extra.get("maximum_year")
    for normalized in records:
        total += 1
        row = normalized.get("record")
        if not isinstance(row, dict):
            continue
        source_count += 1
        if not any(row.get(key) not in (None, "") for key in geography_keys):
            missing_geography += 1
        missing_columns.update(
            column for column in definition.required_columns if column not in row
        )
        if minimum is not None and maximum is not None:
            try:
                year = int(str(row.get("year")))
            except (TypeError, ValueError):
                year = None
            if year is None or not int(minimum) <= year <= int(maximum):
                invalid_year_count += 1
                if len(invalid_year_examples) < 20:
                    invalid_year_examples.append(row.get("year"))
    results: list[dict[str, Any]] = []
    for rule in definition.quality_rules:
        rule_id = rule.rule_id.casefold()
        observed: Any = source_count
        expected: Any = "at_least_one_record"
        passed = source_count > 0
        if "geography" in rule_id:
            observed = {"record_count": source_count, "missing_geography": missing_geography}
            expected = {"missing_geography": 0}
            passed = source_count > 0 and missing_geography == 0
        elif "value_state" in rule_id or "preservation" in rule_id:
            observed = {"record_count": source_count, "raw_rows_preserved": source_count == total}
            expected = {"raw_rows_preserved": True}
            passed = source_count > 0 and source_count == total
        elif "era" in rule_id and minimum is not None:
            observed = {
                "invalid_year_count": invalid_year_count,
                "invalid_year_examples": invalid_year_examples,
            }
            expected = {"invalid_year_count": 0}
            passed = source_count > 0 and invalid_year_count == 0
        elif "required" in rule_id and definition.required_columns:
            observed = {"missing_columns": sorted(missing_columns)}
            expected = {"missing_columns": []}
            passed = source_count > 0 and not missing_columns
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
        validate_names(acquired.artifacts)
        return acquired.artifacts
    raw = acquired.raw_payload
    if raw is None and isinstance(acquired.payload, bytes):
        raw = acquired.payload
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


def _primary_artifact(
    acquired: AcquireResult, artifacts: tuple[AcquisitionArtifact, ...]
) -> AcquisitionArtifact:
    raw = acquired.raw_payload
    if raw is None and isinstance(acquired.payload, bytes):
        raw = acquired.payload
    matches = [
        item
        for item in artifacts
        if item.sha256 == acquired.artifact_sha256
        and item.media_type == acquired.media_type
        and (raw is None or item.payload == raw)
    ]
    if len(matches) != 1:
        raise ValueError("Acquisition primary artifact is missing or ambiguous")
    return matches[0]


def _member_artifact_id(
    resource_key: str, run_id: str, artifact: AcquisitionArtifact, count: int
) -> str:
    if count == 1:
        return f"{resource_key}:{run_id}:1:{artifact.sha256[:32]}"
    member_id = hashlib.sha256(artifact.name.encode("utf-8")).hexdigest()
    return f"{resource_key}:{run_id}:{member_id[:32]}"


def _planned_artifact_id(
    resource_key: str, run_id: str, artifact: AcquisitionArtifact, count: int
) -> str:
    if count == 1:
        return f"planned:{run_id}:{artifact.sha256[:32]}"
    return _member_artifact_id(resource_key, run_id, artifact, count)


def _lineage_rows(
    definition: SourceDefinition, state: RunState, records: Iterable[dict[str, Any]]
) -> list[tuple[Any, ...]]:
    if definition.adapter_kind is AdapterKind.RSS_ATOM:
        raise PermissionError("INTELLIGENCE_STORAGE_EFFECTS_REQUIRED")
    rows: list[tuple[Any, ...]] = []
    acquisition = state.checkpoint(Stage.ACQUIRE)
    retrieved_at = (
        datetime.fromisoformat(acquisition.completed_at)
        if acquisition is not None and acquisition.completed_at
        else datetime.now(UTC)
    )
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
                retrieved_at,
            )
        )
    return rows


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bulk_lineage_documents(
    definition: SourceDefinition,
    state: RunState,
    partitions: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if len(partitions) > 64:
        raise ValueError("Bulk projection batch exceeds 64 partitions")
    rows = _lineage_rows(definition, state, (row for part in partitions for row in part))
    identities = [str(row[0]) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate logical record in bulk projection")
    keys = (
        "record_id",
        "source_id",
        "dataset_id",
        "resource_key",
        "source_definition_version",
        "ingestion_run_id",
        "source_record_id",
        "source_row_hash",
        "payload",
        "retrieved_at",
    )
    documents = [dict(zip(keys, row, strict=True)) for row in rows]
    for document in documents:
        retrieved_at = document["retrieved_at"]
        if not isinstance(retrieved_at, datetime):
            raise ValueError("Invalid retrieval timestamp in bulk projection")
        document["retrieved_at"] = retrieved_at.isoformat()
        document["payload_sha256"] = hashlib.sha256(str(document["payload"]).encode()).hexdigest()
    return documents


def _verify_bulk_source(cursor: Any, source: str, expected_count: int) -> None:
    """Fail before any projection write if upload lost or changed a row."""
    cursor.execute(
        f"""SELECT COUNT(*), COUNT(DISTINCT $1:record_id::VARCHAR),
                   COUNT_IF(SHA2($1:payload::VARCHAR, 256)
                            <> $1:payload_sha256::VARCHAR)
            FROM {source}"""
    )
    observed = cursor.fetchone()
    if observed is None or (int(observed[0]), int(observed[1]), int(observed[2] or 0)) != (
        expected_count,
        expected_count,
        0,
    ):
        raise ValueError("Bulk transport row count or payload checksum mismatch")


def _bulk_record_source(source: str) -> str:
    return f"""SELECT $1:record_id::VARCHAR AS record_id,
                     $1:source_id::VARCHAR AS source_id,
                     $1:dataset_id::VARCHAR AS dataset_id,
                     $1:resource_key::VARCHAR AS resource_key,
                     $1:source_definition_version::NUMBER AS source_definition_version,
                     $1:ingestion_run_id::VARCHAR AS ingestion_run_id,
                     AS_VARCHAR($1:source_record_id) AS source_record_id,
                     $1:source_row_hash::VARCHAR AS source_row_hash,
                     PARSE_JSON($1:payload::VARCHAR) AS payload,
                     $1:payload::VARCHAR AS payload_text,
                     TO_TIMESTAMP_LTZ($1:retrieved_at::VARCHAR) AS retrieved_at
              FROM {source}"""


def _merge_bulk_projection(cursor: Any, relation: str, timestamp_column: str, source: str) -> None:
    cursor.execute(
        f"""MERGE INTO {relation} target
        USING ({_bulk_record_source(source)}) source
        ON target.record_id=source.record_id
        WHEN NOT MATCHED THEN INSERT
          (record_id, source_id, dataset_id, resource_key, source_definition_version,
           ingestion_run_id, source_record_id, source_row_hash, payload, retrieved_at,
           {timestamp_column})
          VALUES (source.record_id, source.source_id, source.dataset_id,
                  source.resource_key, source.source_definition_version,
                  source.ingestion_run_id, source.source_record_id,
                  source.source_row_hash, source.payload, source.retrieved_at,
                  CURRENT_TIMESTAMP())"""
    )


def _check_bulk_revision_conflicts(
    cursor: Any, source: str, artifact_sha256: str, transformation_version: str | None
) -> None:
    """Reject a reused artifact/record key with changed normalized content."""
    cursor.execute(
        f"""SELECT COUNT(*) FROM ({_bulk_record_source(source)}) source
        JOIN GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS prior
          ON prior.artifact_sha256=%s
         AND prior.transformation_version=%s
         AND prior.record_id=source.record_id
        WHERE prior.source_row_hash<>source.source_row_hash
           OR prior.normalized_sha256<>SHA2(source.payload_text, 256)""",
        (artifact_sha256, transformation_version or "unspecified"),
    )
    result = cursor.fetchone()
    if result is None or int(result[0]) != 0:
        raise ValueError("Conflicting logical record in one source artifact")


def _merge_bulk_revisions(
    cursor: Any,
    source: str,
    artifact_id: str,
    artifact_sha256: str,
    transformation_version: str | None,
) -> None:
    """Insert captures for this run; deterministic physical revisions remain stable."""
    version = transformation_version or "unspecified"
    cursor.execute(
        f"""MERGE INTO GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS target
        USING (SELECT SHA2('capture:' || source.ingestion_run_id || ':' ||
                           source.record_id, 256) AS capture_record_id,
                      SHA2('record-revision:' || source.record_id || ':' || %s || ':' ||
                           source.source_row_hash || ':' ||
                           SHA2(source.payload_text, 256) || ':' || %s, 256)
                           AS record_revision,
                      source.record_id, source.source_id, source.dataset_id,
                      source.resource_key, source.source_definition_version,
                      source.ingestion_run_id, source.source_record_id,
                      %s AS artifact_id, %s AS artifact_sha256,
                      source.source_row_hash,
                      SHA2(source.payload_text, 256) AS normalized_sha256,
                      %s AS transformation_version, source.payload,
                      source.retrieved_at
               FROM ({_bulk_record_source(source)}) source) source
        ON target.capture_record_id=source.capture_record_id
        WHEN NOT MATCHED THEN INSERT
          (capture_record_id, record_revision, record_id, source_id, dataset_id,
           resource_key, source_definition_version, ingestion_run_id,
           source_record_id, artifact_id, artifact_sha256, source_row_hash,
           normalized_sha256, transformation_version, payload, retrieved_at,
           observed_at)
          VALUES (source.capture_record_id, source.record_revision,
                  source.record_id, source.source_id, source.dataset_id,
                  source.resource_key, source.source_definition_version,
                  source.ingestion_run_id, source.source_record_id,
                  source.artifact_id, source.artifact_sha256, source.source_row_hash,
                  source.normalized_sha256, source.transformation_version,
                  source.payload, source.retrieved_at, CURRENT_TIMESTAMP())""",
        (artifact_sha256, version, artifact_id, artifact_sha256, version),
    )


def _upsert_sql(relation: str, timestamp_column: str) -> str:
    """Build a parameterized one-or-more-row MERGE for a known relation."""
    values = ",\n    ".join("(" + ", ".join(["%s"] * 10) + ")" for _ in range(1))
    return _upsert_sql_for_values(relation, timestamp_column, values)


def _upsert_sql_for_values(relation: str, timestamp_column: str, values: str) -> str:
    """Insert the first projection only; later revisions live in the ledger."""
    return f"""MERGE INTO {relation} target
USING (SELECT column1 AS record_id, column2 AS source_id, column3 AS dataset_id,
              column4 AS resource_key, column5 AS source_definition_version,
              column6 AS ingestion_run_id, column7 AS source_record_id,
              column8 AS source_row_hash, PARSE_JSON(column9) AS payload,
              column10 AS retrieved_at
       FROM VALUES
    {values}) source
ON target.record_id=source.record_id
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


def _insert_revisions(
    cursor: Any,
    rows: list[tuple[Any, ...]],
    artifact_id: str,
    artifact_sha256: str,
    transformation_version: str | None,
) -> None:
    """Retain an immutable run capture and stable physical content revision."""
    for start in range(0, len(rows), _UPSERT_BATCH_SIZE):
        batch = rows[start : start + _UPSERT_BATCH_SIZE]
        identities = [str(row[0]) for row in batch]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate logical record in normalized partition")
        placeholders = ", ".join("%s" for _ in identities)
        cursor.execute(
            "SELECT record_id, source_row_hash, normalized_sha256 FROM "
            "GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS "
            f"WHERE artifact_sha256=%s AND transformation_version=%s "
            f"AND record_id IN ({placeholders})",
            (artifact_sha256, transformation_version or "unspecified", *identities),
        )
        prior = {
            str(record_id): (str(source_digest), str(normalized_digest))
            for record_id, source_digest, normalized_digest in cursor.fetchall()
        }
        for row in batch:
            normalized_digest = hashlib.sha256(str(row[8]).encode("utf-8")).hexdigest()
            if str(row[0]) in prior and prior[str(row[0])] != (
                str(row[7]),
                normalized_digest,
            ):
                raise ValueError("Conflicting logical record in one source artifact")
        values = ",\n    ".join("(" + ", ".join(["%s"] * 17) + ")" for _ in batch)
        projected = []
        for row in batch:
            normalized_digest = hashlib.sha256(str(row[8]).encode("utf-8")).hexdigest()
            record_revision = _stable_id(
                f"record-revision:{row[0]}:{artifact_sha256}:{row[7]}:"
                f"{normalized_digest}:{transformation_version or 'unspecified'}"
            )
            projected.append(
                (
                    _stable_id(f"capture:{row[5]}:{row[0]}"),
                    record_revision,
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    artifact_id,
                    artifact_sha256,
                    row[7],
                    normalized_digest,
                    transformation_version or "unspecified",
                    row[8],
                    row[9],
                    datetime.now(UTC),
                )
            )
        cursor.execute(
            """MERGE INTO GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS target
            USING (SELECT column1 AS capture_record_id,
                          column2 AS record_revision, column3 AS record_id,
                          column4 AS source_id, column5 AS dataset_id,
                          column6 AS resource_key, column7 AS source_definition_version,
                          column8 AS ingestion_run_id, column9 AS source_record_id,
                          column10 AS artifact_id, column11 AS artifact_sha256,
                          column12 AS source_row_hash, column13 AS normalized_sha256,
                          column14 AS transformation_version,
                          PARSE_JSON(column15) AS payload, column16 AS retrieved_at,
                          column17 AS observed_at
                   FROM VALUES
    """
            + values
            + """ ) source
            ON target.capture_record_id=source.capture_record_id
            WHEN NOT MATCHED THEN INSERT
              (capture_record_id, record_revision, record_id, source_id, dataset_id,
               resource_key, source_definition_version, ingestion_run_id,
               source_record_id, artifact_id,
               artifact_sha256, source_row_hash, normalized_sha256,
               transformation_version, payload, retrieved_at, observed_at)
              VALUES (source.capture_record_id, source.record_revision,
                      source.record_id, source.source_id, source.dataset_id,
                      source.resource_key,
                      source.source_definition_version, source.ingestion_run_id,
                      source.source_record_id, source.artifact_id, source.artifact_sha256,
                      source.source_row_hash, source.normalized_sha256,
                      source.transformation_version, source.payload,
                      source.retrieved_at, source.observed_at)""",
            tuple(value for item in projected for value in item),
        )
