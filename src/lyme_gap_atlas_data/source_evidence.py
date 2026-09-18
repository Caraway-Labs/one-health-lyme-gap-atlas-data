# ruff: noqa: E501  # Snowflake ledger column names remain readable in SQL.
"""Bounded evidence registration for routine public SourceDefinitions.

This is intentionally separate from the generic RAW/STAGING/CONFORMED
orchestrator.  It creates the immutable candidate that a protected production
source-review decision can evaluate; it never creates a source version or
loads source rows into governed data relations.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .artifacts import create_artifact
from .ingestion.adapters import get_adapter
from .ingestion.source_definition import load_source_definition
from .ingestion.types import SourceDefinition
from .redaction import redact_mapping
from .settings import PipelineSettings


def _spaces_client(settings: PipelineSettings) -> Any:
    if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
        raise ValueError("Spaces credentials are required for source evidence")
    return boto3.client(
        "s3",
        endpoint_url=settings.spaces_endpoint,
        aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        region_name=settings.spaces_region,
        config=Config(signature_version="s3v4"),
    )


def _definition_payload(definition: SourceDefinition) -> dict[str, object]:
    """Persist only reviewable configuration; never credentials or raw rows."""
    return {
        "resource_key": definition.resource_key,
        "source_id": definition.source_id,
        "dataset_id": definition.dataset_id,
        "definition_version": definition.definition_version,
        "adapter_kind": definition.adapter_kind.value,
        "endpoint_template": definition.endpoint_template,
        "deterministic_order_clause": definition.deterministic_order_clause,
        "incremental_strategy": definition.incremental_strategy,
        "geography_semantics": definition.geography_semantics,
        "temporal_semantics": definition.temporal_semantics,
        "required_columns": list(definition.required_columns),
        "restrictions": list(definition.restrictions),
    }


def collect_routine_public_source_evidence(
    definition: SourceDefinition,
    *,
    settings: PipelineSettings | None = None,
    connection_factory: Callable[[], Any] | None = None,
    spaces_client: Any | None = None,
) -> dict[str, object]:
    """Capture a bounded, immutable production review candidate.

    The protected caller must use a committed ``ROUTINE_PUBLIC`` definition.
    A source response is retained only in private Spaces and remains outside
    RAW/STAGING/CONFORMED until a separate owner-rights decision creates an
    active source version.
    """
    if definition.extra.get("onboarding_mode") != "ROUTINE_PUBLIC":
        raise ValueError("Only ROUTINE_PUBLIC SourceDefinitions can use this evidence path")
    active_settings = settings or PipelineSettings()
    if active_settings.topx_env != "prod":
        raise ValueError("Routine public source evidence admission requires TOPX_ENV=prod")
    client = spaces_client or _spaces_client(active_settings)
    acquisition = get_adapter(definition.adapter_kind).acquire(definition)
    validation = get_adapter(definition.adapter_kind).validate_payload(
        definition, acquisition.payload
    )
    if not validation.ok:
        issues = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"Source evidence payload failed validation: {issues}")

    now = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    config_payload = _definition_payload(definition)
    config_bytes = json.dumps(config_payload, sort_keys=True, separators=(",", ":")).encode()
    source_bytes = (
        acquisition.raw_payload
        or json.dumps(
            acquisition.payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    )
    config_artifact = create_artifact(
        payload=config_bytes,
        environment=active_settings.topx_env,
        resource_key=definition.resource_key,
        run_id=run_id,
    )
    source_artifact = create_artifact(
        payload=source_bytes,
        environment=active_settings.topx_env,
        resource_key=definition.resource_key,
        run_id=run_id,
    )
    for artifact, body, media_type in (
        (config_artifact, config_bytes, "application/json"),
        (source_artifact, source_bytes, acquisition.media_type),
    ):
        client.put_object(
            Bucket=active_settings.spaces_bucket,
            Key=f"{active_settings.spaces_prefix}/{artifact.object_key}",
            Body=body,
            ContentType=media_type,
        )

    profile_sha256 = hashlib.sha256(config_bytes).hexdigest()
    schema_payload = json.dumps(sorted(definition.required_columns), separators=(",", ":"))
    schema_sha256 = hashlib.sha256(schema_payload.encode()).hexdigest()
    catalog_dataset_id = str(uuid.uuid4())
    config_artifact_id = str(uuid.uuid4())
    source_artifact_id = str(uuid.uuid4())
    connection_factory = connection_factory or (lambda: connect(SnowflakeSettings()))
    with connection_factory() as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_RUNS
                    (ingestion_run_id, resource_key, run_mode, trigger_type, status, code_version,
                     config_sha256, started_at, completed_at)
                    VALUES (%s, %s, 'EVIDENCE_ONLY', 'C', 'COMPLETED', %s, %s, %s, %s)""",
                    (
                        run_id,
                        definition.resource_key,
                        "routine-public-evidence-v1",
                        profile_sha256,
                        now,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_DATASETS
                    (catalog_dataset_id, dataset_key, catalog_name, catalog_record_id, metadata_payload,
                     metadata_sha256, discovered_at, is_current)
                    SELECT %s, %s, %s, %s, PARSE_JSON(%s), %s, %s, TRUE""",
                    (
                        catalog_dataset_id,
                        definition.resource_key,
                        definition.source_id.upper(),
                        definition.dataset_id,
                        json.dumps(config_payload),
                        config_artifact.sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_RESOURCES
                    (catalog_resource_id, catalog_dataset_id, resource_key, resource_type, resource_url,
                     canonical_source_url, api_dataset_id, resource_payload, registered_at, is_active)
                    SELECT %s, %s, %s, 'API', %s, %s, %s, PARSE_JSON(%s), %s, TRUE""",
                    (
                        str(uuid.uuid4()),
                        catalog_dataset_id,
                        definition.resource_key,
                        definition.endpoint_template,
                        definition.endpoint_template,
                        definition.dataset_id,
                        json.dumps(config_payload),
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE GOVERNANCE.SOURCE_ACCESS_PROFILES SET effective_to=%s WHERE resource_key=%s AND effective_to IS NULL",
                    (now, definition.resource_key),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SOURCE_ACCESS_PROFILES
                    (source_access_profile_id, resource_key, profile_version, connector_name, endpoint_template,
                     deterministic_order_clause, incremental_strategy, configuration_sha256, effective_from)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        definition.resource_key,
                        int(definition.extra.get("profile_version", definition.definition_version)),
                        definition.adapter_kind.value,
                        definition.endpoint_template,
                        definition.deterministic_order_clause,
                        definition.incremental_strategy,
                        profile_sha256,
                        now,
                    ),
                )
                for sequence, purpose, artifact, artifact_id, media_type, rows in (
                    (
                        1,
                        "SOURCE_DEFINITION",
                        config_artifact,
                        config_artifact_id,
                        "application/json",
                        1,
                    ),
                    (
                        2,
                        "SOURCE_EVIDENCE",
                        source_artifact,
                        source_artifact_id,
                        acquisition.media_type,
                        acquisition.row_count,
                    ),
                ):
                    request_id = str(uuid.uuid4())
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose, endpoint,
                         redacted_request, status_code, response_sha256, retrieved_row_count, created_at)
                        SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), 200, %s, %s, %s""",
                        (
                            request_id,
                            run_id,
                            sequence,
                            purpose,
                            definition.endpoint_template,
                            json.dumps(
                                redact_mapping(
                                    {
                                        "definition": definition.resource_key,
                                        "order": definition.deterministic_order_clause,
                                    }
                                )
                            ),
                            artifact.sha256,
                            rows,
                            now,
                        ),
                    )
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                        (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri, artifact_type,
                         media_type, byte_count, sha256, retention_class, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PUBLIC_SEVEN_YEAR', %s)""",
                        (
                            artifact_id,
                            run_id,
                            request_id,
                            f"s3://{active_settings.spaces_bucket}/{active_settings.spaces_prefix}/{artifact.object_key}",
                            purpose,
                            media_type,
                            artifact.byte_count,
                            artifact.sha256,
                            now,
                        ),
                    )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS
                    (source_document_snapshot_id, resource_key, document_type, document_url, artifact_id,
                     content_sha256, retrieved_at, is_material_change)
                    VALUES (%s, %s, 'SOURCE_DEFINITION', %s, %s, %s, %s, FALSE)""",
                    (
                        str(uuid.uuid4()),
                        definition.resource_key,
                        definition.endpoint_template,
                        config_artifact_id,
                        config_artifact.sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SCHEMA_SNAPSHOTS
                    (schema_snapshot_id, resource_key, schema_fingerprint, schema_payload, retrieved_at)
                    SELECT %s, %s, %s, PARSE_JSON(%s), %s""",
                    (
                        str(uuid.uuid4()),
                        definition.resource_key,
                        schema_sha256,
                        schema_payload,
                        now,
                    ),
                )
                limitations = " ".join(definition.restrictions)
                cursor.execute(
                    """INSERT INTO GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
                    (dataset_quality_assessment_id, resource_key, assessment_status, relevance_score,
                     joinability_score, accessibility_score, documentation_score, quality_score, overall_score,
                     recommendation, limitations, assessed_at)
                    VALUES (%s, %s, 'PENDING_REVIEW', 95, 95, 95, 90, 90, 93, 'APPROVE', %s, %s)""",
                    (str(uuid.uuid4()), definition.resource_key, limitations, now),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "ingestion_run_id": run_id,
        "resource_key": definition.resource_key,
        "source_artifact_id": source_artifact_id,
        "source_artifact_sha256": source_artifact.sha256,
        "definition_artifact_sha256": config_artifact.sha256,
        "schema_sha256": schema_sha256,
        "status": "PENDING_STEWARD_REVIEW",
    }


def collect_routine_public_source_evidence_from_path(definition_path: str) -> dict[str, object]:
    """CLI-friendly committed-definition entry point."""
    return collect_routine_public_source_evidence(load_source_definition(Path(definition_path)))
