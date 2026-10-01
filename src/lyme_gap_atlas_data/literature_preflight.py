"""Read-only readiness checks for a bounded literature operation."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable
from typing import Any

import boto3  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from neo4j import GraphDatabase
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .literature_tracing import trace_fields
from .settings import PipelineSettings

_TRACER = trace.get_tracer("one-health-lyme-gap-atlas-data.literature-preflight")
_READABLE_TABLES = (
    "KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS",
    "KNOWLEDGE_GRAPH.PAPERS",
    "KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES",
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS",
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS",
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS",
    "KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS",
    "KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS",
    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS",
    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS",
)
_COLUMNS = {
    "KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS": (
        "DISCOVERY_RUN_ID, REQUEST_EVIDENCE, NEXT_RETSTART, STATUS"
    ),
    "KNOWLEDGE_GRAPH.PAPERS": "PMID, PMCID, STATE, FINAL_REVIEW_DECISION_ID",
    "KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES": "PMID, QUERY_MATCH_ID, DISCOVERY_RUN_ID",
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS": "EXTRACTION_ATTEMPT_ID, PMID, ATTEMPT_NUMBER, STATUS",
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS": "EXTRACTION_ATTEMPT_ID, CLASSIFICATION",
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS": (
        "EXTRACTION_ATTEMPT_ID, DIAGNOSTIC_TYPE, DETAILS"
    ),
    "KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS": "PMID, ARTIFACT_ID, OBJECT_KEY",
    "KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS": "PMID, EXTRACTION_ATTEMPT_ID",
    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS": "BUILD_ID, STATUS",
    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS": "PMID, BUILD_ID",
    "KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS": "PMID, REASON, CORRELATION_ID",
    "GOVERNANCE.RAW_ARTIFACTS": "ARTIFACT_ID, INGESTION_RUN_ID, SHA256",
    "GOVERNANCE.INGESTION_REQUESTS": "INGESTION_RUN_ID, REQUEST_PURPOSE, REDACTED_REQUEST",
}
_WRITE_PRIVILEGES = {
    "discover": (
        ("KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS", "INSERT"),
        ("KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS", "UPDATE"),
        ("KNOWLEDGE_GRAPH.PAPERS", "INSERT"),
        ("KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES", "INSERT"),
        ("GOVERNANCE.RAW_ARTIFACTS", "INSERT"),
        ("GOVERNANCE.INGESTION_REQUESTS", "INSERT"),
    ),
    "extract": (
        ("KNOWLEDGE_GRAPH.PAPERS", "UPDATE"),
        ("KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS", "INSERT"),
        ("GOVERNANCE.RAW_ARTIFACTS", "INSERT"),
        ("KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS", "INSERT"),
        ("KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS", "INSERT"),
        ("KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS", "UPDATE"),
        ("KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS", "INSERT"),
        ("KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS", "INSERT"),
        ("KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS", "INSERT"),
    ),
    "build-corpus": (
        ("KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS", "INSERT"),
        ("KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS", "UPDATE"),
        ("KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS", "INSERT"),
        ("KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS", "DELETE"),
    ),
}
_WRITE_COLUMNS = {
    "KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS": (
        "PMID, PMCID, ARTIFACT_ID, OBJECT_KEY, LICENSE_URL, JATS_SHA256, TEXT_SHA256"
    ),
    "KNOWLEDGE_GRAPH.PAPERS": (
        "PMID, PMCID, TITLE, JOURNAL, PUBLICATION_DATE, PUBLICATION_TYPES, LANGUAGE, "
        "ABSTRACT, STATE, FINAL_REVIEW_DECISION_ID, ACCESS_STATUS, "
        "CONFIGURATION_VERSION, UPDATED_AT"
    ),
    "KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES": (
        "QUERY_MATCH_ID, PMID, FAMILY, QUERY_SHA256, DISCOVERY_RUN_ID"
    ),
    "KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS": (
        "DISCOVERY_RUN_ID, FAMILY, QUERY_TEXT, QUERY_SHA256, WEBENV, QUERY_KEY, RESULT_COUNT, "
        "NEXT_RETSTART, BATCH_SIZE, STATUS, REQUEST_EVIDENCE, RAW_ARTIFACT_ID, "
        "STARTED_AT, FINISHED_AT"
    ),
    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS": (
        "BUILD_ID, DISCOVERY_RUN_ID, CORPUS_RULES_VERSION, RULES_SHA256, STATUS, "
        "PAPERS_CONSIDERED, PAPERS_ADMITTED, PAPERS_EXCLUDED_UNAPPROVED, CHUNKS_WRITTEN, "
        "EMPTY_CHUNK_REJECTIONS, DUPLICATE_CHUNK_REJECTIONS, MISSING_PROVENANCE_REJECTIONS, "
        "CORPUS_CONTENT_SHA256, REDACTED_ERROR, STARTED_AT, FINISHED_AT"
    ),
    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS": (
        "UNIT_ID, CORPUS_RULES_VERSION, BUILD_ID, PMID, PMCID, ARTIFACT_ID, OBJECT_KEY, "
        "JATS_SHA256, TEXT_SHA256, CONTRIBUTION_SHA256, CHUNK_INDEX, CHAR_START, CHAR_END, "
        "SECTION_LABEL, UNIT_TEXT, UNIT_TEXT_SHA256"
    ),
    "KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS": (
        "GRAPH_RECEIPT_ID, PMID, CONTRIBUTION_SHA256, NEO4J_TRANSACTION_ID, NODE_COUNT, "
        "PASSAGE_COUNT, EDGE_COUNT, EXTRACTION_ATTEMPT_ID, ARTIFACT_ID, PUBLISHED_AT"
    ),
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS": (
        "EXTRACTION_ATTEMPT_ID, PMID, ATTEMPT_NUMBER, PROVIDER_ROUTE, MODEL_IDENTIFIER, "
        "ESTIMATED_INPUT_TOKENS, REQUEST_SHA256, STATUS, LEASE_EXPIRES_AT, METHOD_VERSION, "
        "ERROR_CLASS, STARTED_AT, FINISHED_AT"
    ),
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS": (
        "DIAGNOSTIC_ID, EXTRACTION_ATTEMPT_ID, PMID, DIAGNOSTIC_TYPE, DETAILS"
    ),
    "KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS": (
        "CLASSIFICATION_ID, EXTRACTION_ATTEMPT_ID, PMID, CLASSIFICATION, RATIONALE, CORRELATION_ID"
    ),
    "KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS": (
        "PAPER_STATE_EVENT_ID, PMID, FROM_STATE, TO_STATE, REASON, CORRELATION_ID, ACTOR"
    ),
    "GOVERNANCE.RAW_ARTIFACTS": (
        "ARTIFACT_ID, INGESTION_RUN_ID, INGESTION_REQUEST_ID, ARTIFACT_URI, ARTIFACT_TYPE, "
        "MEDIA_TYPE, BYTE_COUNT, SHA256, CREATED_AT"
    ),
    "GOVERNANCE.INGESTION_REQUESTS": (
        "INGESTION_REQUEST_ID, INGESTION_RUN_ID, REQUEST_SEQUENCE, REQUEST_PURPOSE, "
        "ENDPOINT, REDACTED_REQUEST, STATUS_CODE, CREATED_AT"
    ),
}
_COLUMNS.update(
    {table: columns for table, columns in _WRITE_COLUMNS.items() if table in _READABLE_TABLES}
)


def _effective_grants(cursor: Any, role: str) -> list[tuple[str, str, str]]:
    """Include grants on roles inherited by the actual session's runtime role."""
    pending = [role]
    visited: set[str] = set()
    grants: list[tuple[str, str, str]] = []
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        if len(visited) >= 16 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", current):
            raise ValueError("runtime role hierarchy cannot be verified")
        visited.add(current)
        cursor.execute("SHOW GRANTS TO ROLE " + current)
        for row in cursor.fetchall():
            privilege, granted_on, name = (
                str(row[1]).upper(),
                str(row[2]).upper(),
                str(row[3]).upper(),
            )
            if granted_on == "ROLE":
                pending.append(name)
            else:
                grants.append((privilege, granted_on, name))
    return grants


def _identity(value: str | None, kind: str) -> str:
    patterns = {
        "code_sha": r"[0-9a-f]{40}",
        "image_sha": r"sha256:[0-9a-f]{64}",
        "workflow_run_id": r"[0-9]{1,20}",
    }
    return value if value and re.fullmatch(patterns[kind], value) else "unknown"


def _classification_contract_supported(clause: str) -> bool:
    """Recognize only positive membership on the worker's classification column."""
    clause = clause.strip()
    while clause.startswith("(") and clause.endswith(")"):
        clause = clause[1:-1].strip()
    membership = re.fullmatch(
        r'(?:(?i:CLASSIFICATION)|"CLASSIFICATION")\s+(?i:IN)\s*'
        r"\(\s*('[A-Za-z_]+'(?:\s*,\s*'[A-Za-z_]+')*)\s*\)",
        clause,
    )
    if membership is None:
        return False
    return {"provider_rejected_pre_inference", "contract_remediation_reopen"}.issubset(
        set(re.findall(r"'([^']+)'", membership.group(1)))
    )


def _snowflake_contract(settings: PipelineSettings, operation: str) -> dict[str, object]:
    """Exercise SELECT capabilities under the same role that will claim work."""
    missing: list[str] = []
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", settings.snowflake_role):
        raise ValueError("invalid runtime role identifier")
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE()")
        row = cursor.fetchone()
        if (
            row is None
            or row[0] != settings.snowflake_role
            or row[1] != settings.snowflake_database
        ):
            raise RuntimeError("runtime_identity_mismatch")
        tables: tuple[str, ...]
        if operation == "discover":
            tables = _READABLE_TABLES[:3]
        elif operation == "build-corpus":
            tables = (
                _READABLE_TABLES[0],
                _READABLE_TABLES[1],
                _READABLE_TABLES[2],
                _READABLE_TABLES[6],
                _READABLE_TABLES[7],
                _READABLE_TABLES[8],
                _READABLE_TABLES[9],
            )
        else:
            tables = _READABLE_TABLES[:8]
        for table in tables:
            try:
                cursor.execute(f"SELECT {_COLUMNS[table]} FROM {table} LIMIT 0")
            except Exception:
                missing.append(table)
        # Some audit tables are intentionally write only for the runtime role.
        # Inspect their schema without requesting a broader SELECT grant.
        for table in sorted({name for name, _ in _WRITE_PRIVILEGES[operation]}):
            schema, name = table.split(".")
            cursor.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (schema, name),
            )
            columns = {str(row[0]).upper() for row in cursor.fetchall()}
            required = _WRITE_COLUMNS.get(table, _COLUMNS[table])
            if not set(required.split(", ")).issubset(columns):
                missing.append(f"{table}:COLUMNS")
        grants = _effective_grants(cursor, settings.snowflake_role)
        for table, privilege in _WRITE_PRIVILEGES[operation]:
            qualified = f"{settings.snowflake_database}.{table}".upper()
            if not any(
                granted_on == "TABLE" and name == qualified and right in {privilege, "OWNERSHIP"}
                for right, granted_on, name in grants
            ):
                missing.append(f"{table}:{privilege}")
        # The budget procedure is not invoked: it reserves spend. Inspect the
        # current role's grant instead, keeping preflight free of mutation.
        if operation == "extract":
            cursor.execute(
                "SELECT CHECK_CLAUSE FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = 'KNOWLEDGE_GRAPH' "
                "AND CONSTRAINT_NAME = 'CK_PMC_ATTEMPT_CLASSIFICATION' "
                "AND CONSTRAINT_TABLE = 'EXTRACTION_ATTEMPT_CLASSIFICATIONS'"
            )
            classification_clauses = cursor.fetchall()
            if not any(
                _classification_contract_supported(str(item[0])) for item in classification_clauses
            ):
                missing.append("PMC_ATTEMPT_CLASSIFICATION_CONTRACT")
            cursor.execute(
                "SELECT CHECK_CLAUSE FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = 'KNOWLEDGE_GRAPH' "
                "AND CONSTRAINT_NAME = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE'"
            )
            clauses = cursor.fetchall()
            if not any(
                "STAGE_FAILURE" in str(item[0]).upper()
                and "ATTEMPT_CONTEXT" in str(item[0]).upper()
                for item in clauses
            ):
                missing.append("DATA528_ATTEMPT_DIAGNOSTIC_CONTRACT")
            for procedure in ("SP_RESERVE_KG_LLM_BUDGET", "SP_FINALIZE_KG_LLM_BUDGET"):
                if not any(
                    right in {"USAGE", "OWNERSHIP"}
                    and granted_on == "PROCEDURE"
                    and name.split("(", 1)[0].strip()
                    == f"{settings.snowflake_database}.GOVERNANCE.{procedure}".upper()
                    for right, granted_on, name in grants
                ):
                    missing.append(f"GOVERNANCE.{procedure}:USAGE")
    return {"role": settings.snowflake_role, "missing_capabilities": missing}


def _spaces_access(settings: PipelineSettings) -> None:
    assert settings.spaces_access_key_id is not None
    assert settings.spaces_secret_access_key is not None
    client = boto3.client(
        "s3",
        endpoint_url=settings.spaces_endpoint,
        aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        region_name=settings.spaces_region,
    )
    client.head_bucket(Bucket=settings.spaces_bucket)


def _neo4j_access(settings: PipelineSettings) -> None:
    assert settings.neo4j_runtime_password is not None
    with GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_runtime_user, settings.neo4j_runtime_password.get_secret_value()),
    ) as driver:
        driver.verify_connectivity()


def literature_preflight(
    settings: PipelineSettings,
    *,
    operation: str,
    snowflake_probe: Callable[[PipelineSettings, str], dict[str, object]] = _snowflake_contract,
    spaces_probe: Callable[[PipelineSettings], None] = _spaces_access,
    neo4j_probe: Callable[[PipelineSettings], None] = _neo4j_access,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Collect every known blocker before mutation, exposing names only for secrets."""
    run_id = run_id or str(uuid.uuid4())
    if operation == "all":
        checks = [
            literature_preflight(
                settings,
                operation=stage,
                snowflake_probe=snowflake_probe,
                spaces_probe=spaces_probe,
                neo4j_probe=neo4j_probe,
                run_id=run_id,
            )
            for stage in ("discover", "extract", "build-corpus")
        ]
        combined_blockers = [blocker for check in checks for blocker in check["blockers"]]
        return {
            **trace_fields(),
            "run_id": run_id,
            "operation": "all",
            "environment": settings.topx_env,
            "code_sha": checks[0]["code_sha"],
            "image_sha": checks[0]["image_sha"],
            "workflow_run_id": checks[0]["workflow_run_id"],
            "status": "BLOCKED" if combined_blockers else "READY",
            "blockers": combined_blockers,
        }
    if operation not in {"discover", "extract", "build-corpus"}:
        raise ValueError("unsupported literature operation")
    identity = {
        **trace_fields(),
        "run_id": run_id,
        "environment": settings.topx_env,
        "code_sha": _identity(os.getenv("SOURCE_COMMIT") or os.getenv("GITHUB_SHA"), "code_sha"),
        "image_sha": _identity(os.getenv("IMAGE_DIGEST"), "image_sha"),
        "workflow_run_id": _identity(os.getenv("GITHUB_RUN_ID"), "workflow_run_id"),
    }
    blockers: list[dict[str, object]] = []

    def blocked(stage: str, category: str, action: str, capability: str) -> None:
        blockers.append(
            {
                "stage": stage,
                "failure_category": category,
                "retryable": False,
                "next_action": action,
                "capability": capability,
            }
        )

    with _TRACER.start_as_current_span(
        "literature.preflight", record_exception=False, set_status_on_exception=False
    ) as span:
        for key, value in identity.items():
            span.set_attribute(f"atlas.{key}", value)
        if settings.topx_env == "prod":
            for key in ("code_sha", "image_sha", "workflow_run_id"):
                if identity[key] == "unknown":
                    blocked(
                        operation,
                        "preflight_configuration",
                        "verify_deployed_image_and_workflow",
                        key,
                    )
        requirements = {
            "discover": (("NCBI_EMAIL", bool(settings.ncbi_email)),),
            "extract": (
                ("GROQ_API_KEY", settings.groq_api_key is not None),
                ("OPENAI_API_KEY", settings.openai_api_key is not None),
                ("NEO4J_URI", bool(settings.neo4j_uri)),
                ("NEO4J_RUNTIME_PASSWORD", settings.neo4j_runtime_password is not None),
            ),
            "build-corpus": (),
        }
        for name, present in requirements[operation]:
            if not present:
                blocked(operation, "preflight_configuration", "configure_runtime_secret", name)
        if operation in {"discover", "extract", "build-corpus"}:
            for name, present in (
                ("SPACES_ENDPOINT", bool(settings.spaces_endpoint)),
                ("SPACES_ACCESS_KEY_ID", settings.spaces_access_key_id is not None),
                ("SPACES_SECRET_ACCESS_KEY", settings.spaces_secret_access_key is not None),
            ):
                if not present:
                    blocked(operation, "preflight_configuration", "configure_artifact_store", name)
        try:
            contract = snowflake_probe(settings, operation)
            capabilities = contract["missing_capabilities"]
            if not isinstance(capabilities, list):
                raise ValueError("invalid capability probe result")
            for capability in capabilities:
                blocked(
                    operation, "runtime_contract", "apply_schema_or_runtime_grant", str(capability)
                )
        except Exception:
            blocked(
                operation,
                "runtime_contract",
                "repair_runtime_connection_or_grant",
                "SNOWFLAKE_RUNTIME",
            )
        if (
            operation in {"discover", "extract", "build-corpus"}
            and all(
                getattr(settings, name) is not None
                for name in ("spaces_access_key_id", "spaces_secret_access_key")
            )
            and settings.spaces_endpoint
        ):
            try:
                spaces_probe(settings)
            except Exception:
                blocked(
                    operation, "artifact_transport", "repair_artifact_store_access", "SPACES_BUCKET"
                )
        if operation == "extract" and settings.neo4j_uri and settings.neo4j_runtime_password:
            try:
                neo4j_probe(settings)
            except Exception:
                blocked(
                    "graph_publish",
                    "graph_publication",
                    "repair_private_network_or_graph_access",
                    "NEO4J",
                )
        span.set_attribute("atlas.outcome", "blocked" if blockers else "ready")
        span.set_attribute("atlas.blocker_count", len(blockers))
        if blockers:
            span.set_status(Status(StatusCode.ERROR, "preflight_blocked"))
    return {
        **identity,
        "operation": operation,
        "status": "BLOCKED" if blockers else "READY",
        "blockers": blockers,
    }
