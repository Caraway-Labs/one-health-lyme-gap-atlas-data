"""Build and publish an immutable governed semantic release.

The release builder is deliberately a protected migration-identity operation.
It reads source-native records, proves their approval and lineage anchors, and
inserts a candidate release without ever reading or mutating the Alpha POC
database.  The API-facing views are created separately by V072.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

SEMANTIC_SCHEMA = "atlas-governed-semantic-release/v1"
SEMANTIC_SCHEMA_VERSION = "1.0.0"
SEMANTIC_TRANSFORMATION = "semantic_county_assembly_v1"
EXPECTED_COUNTIES = 3_144
EXPECTED_OBSERVATIONS_PER_COUNTY = 14
REQUIRED_SOURCE_KEYS = {"human", "context_svi", "context_rucc", "tick", "pathogen"}
REQUIRED_SCORE_DEFAULT_KEYS = {
    "ecological_share",
    "community_share",
    "low_incidence_breakpoint_per_100k",
    "missing_human_signal_weakness",
    "ecological_mix",
    "community_mix",
}
_FIPS = re.compile(r"^\d{5}$")
_PLACEHOLDER = re.compile(r"^REPLACE_WITH_")


class SemanticReleaseBlocked(ValueError):
    """Raised when a governed release gate is not satisfied."""


@dataclass(frozen=True)
class SemanticSource:
    source_key: str
    resource_key: str
    source_id: str
    dataset_id: str
    label: str
    vintage: str
    source_url: str
    note: str
    data_source_version_id: str
    ingestion_run_id: str
    artifact_id: str
    artifact_sha256: str
    definition_version: int
    field_map: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class SemanticManifest:
    release_id: str
    schema_version: str
    methodology_version: str
    generated_at: str
    scope: str
    score_defaults: dict[str, Any]
    limitations: str
    sources: tuple[SemanticSource, ...]
    raw: dict[str, Any]

    def source(self, source_key: str) -> SemanticSource:
        for source in self.sources:
            if source.source_key == source_key:
                return source
        raise SemanticReleaseBlocked(f"Manifest is missing source slot {source_key}")


@dataclass(frozen=True)
class SourceGate:
    source: SemanticSource
    retrieved_at: Any


@dataclass(frozen=True)
class PathogenParityClassification:
    classification_id: str
    unresolved_county_count: int
    approved_at: Any


@dataclass(frozen=True)
class EvidenceOnlyCoverageClassification:
    classification_id: str
    unresolved_county_count: int
    approved_at: Any


@dataclass(frozen=True)
class TickParityClassification:
    """Owner-approved PROD classification for omitted tick counties."""

    classification_id: str
    unresolved_county_count: int
    approved_at: Any


@dataclass(frozen=True)
class CountyRow:
    values: tuple[Any, ...]
    lineage: dict[str, Any]


def load_manifest(path: Path | str) -> SemanticManifest:
    """Load and validate a source-pinned manifest before opening Snowflake."""
    manifest_path = Path(path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SemanticReleaseBlocked("Semantic release manifest must be a JSON object")
    if document.get("manifest_schema") != SEMANTIC_SCHEMA:
        raise SemanticReleaseBlocked("Unsupported semantic release manifest schema")

    release_id = _required_text(document, "release_id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", release_id):
        raise SemanticReleaseBlocked("release_id must be a stable lowercase identifier")
    schema_version = _required_text(document, "schema_version")
    methodology_version = _required_text(document, "methodology_version")
    generated_at = _required_text(document, "generated_at")
    scope = _required_text(document, "scope")
    limitations = _required_text(document, "limitations")
    score_defaults = document.get("score_defaults")
    if not isinstance(score_defaults, dict) or set(score_defaults) != REQUIRED_SCORE_DEFAULT_KEYS:
        raise SemanticReleaseBlocked(
            "Manifest score_defaults do not match the frozen score contract"
        )

    raw_sources = document.get("sources")
    if not isinstance(raw_sources, list):
        raise SemanticReleaseBlocked("Manifest sources must be a list")
    sources = tuple(_source_from_mapping(item) for item in raw_sources)
    keys = {source.source_key for source in sources}
    if len(keys) != len(sources):
        raise SemanticReleaseBlocked("Manifest source_key values must be unique")
    missing = REQUIRED_SOURCE_KEYS - keys
    if missing:
        raise SemanticReleaseBlocked(
            "Manifest is missing source slots: " + ", ".join(sorted(missing))
        )
    sources_by_key = {source.source_key: source for source in sources}
    if sources_by_key["tick"].resource_key == sources_by_key["pathogen"].resource_key:
        raise SemanticReleaseBlocked("Tick and pathogen must be distinct source resources")

    return SemanticManifest(
        release_id=release_id,
        schema_version=schema_version,
        methodology_version=methodology_version,
        generated_at=generated_at,
        scope=scope,
        score_defaults=dict(score_defaults),
        limitations=limitations,
        sources=sources,
        raw=document,
    )


def build_semantic_release(
    settings: SnowflakeSettings, manifest_path: Path | str
) -> dict[str, Any]:
    """Build one immutable CANDIDATE release from pinned governed inputs."""
    manifest = load_manifest(manifest_path)
    with connect(settings) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                _assert_release_absent(cursor, manifest.release_id)
                use_dev_tick_evidence_exception = (
                    settings.snowflake_database == "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
                )
                use_prod_tick_parity = (
                    settings.snowflake_database == "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
                )
                gates = {
                    source.source_key: _verify_source_gate(
                        cursor,
                        source,
                        allow_dev_tick_evidence_exception=use_dev_tick_evidence_exception,
                    )
                    for source in manifest.sources
                }
                source_rows = {
                    source.source_key: _read_source_rows(cursor, source)
                    for source in manifest.sources
                }
                pathogen_parity = _verify_pathogen_parity_classification(
                    cursor, manifest.source("pathogen"), source_rows["pathogen"]
                )
                tick_coverage = _verify_evidence_only_coverage_classification(
                    cursor,
                    manifest.source("tick"),
                    enabled=use_dev_tick_evidence_exception,
                )
                tick_parity = _verify_tick_parity_classification(
                    cursor,
                    manifest.source("tick"),
                    enabled=use_prod_tick_parity,
                )
                counties, observations = _assemble_counties(
                    manifest,
                    source_rows,
                    gates,
                    pathogen_parity=pathogen_parity,
                    tick_coverage=tick_coverage,
                    tick_parity=tick_parity,
                )
                if len(counties) != EXPECTED_COUNTIES:
                    raise SemanticReleaseBlocked(
                        f"Semantic release requires {EXPECTED_COUNTIES} counties; "
                        f"found {len(counties)}"
                    )
                bundle_sha256 = _bundle_sha256(manifest, counties)
                _insert_release(cursor, manifest, bundle_sha256)
                _insert_hierarchy(cursor, manifest)
                _insert_sources(cursor, manifest)
                _insert_counties(cursor, manifest.release_id, counties)
                _insert_observations(cursor, manifest.release_id, observations)
                cursor.execute(
                    """INSERT INTO PRESENTATION.SEMANTIC_RELEASE_EVENTS
                    (event_id, release_id, event_type, actor, reason)
                    VALUES (%s, %s, 'BUILD_CANDIDATE', CURRENT_USER(), %s)""",
                    (
                        _stable_id(f"semantic-event:{manifest.release_id}:BUILD_CANDIDATE"),
                        manifest.release_id,
                        "Source-pinned semantic release candidate assembled by protected builder",
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "release_id": manifest.release_id,
        "status": "CANDIDATE",
        "bundle_sha256": bundle_sha256,
        "county_count": len(counties),
        "observation_count": len(observations),
        "source_keys": sorted(source_rows),
    }


def publish_semantic_release(
    settings: SnowflakeSettings,
    release_id: str,
    *,
    reason: str,
    approver: str | None = None,
) -> dict[str, Any]:
    """Atomically move a candidate into the current-release pointer."""
    if not reason.strip():
        raise ValueError("A publication reason is required")
    with connect(settings) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT status, bundle_sha256 FROM PRESENTATION.SEMANTIC_RELEASES
                    WHERE release_id=%s""",
                    (release_id,),
                )
                release = cursor.fetchone()
                if release is None or str(release[0]) != "CANDIDATE":
                    raise SemanticReleaseBlocked(
                        "Only an existing CANDIDATE semantic release may be published"
                    )
                cursor.execute(
                    """SELECT COUNT(*), COUNT(DISTINCT fips),
                              (SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_OBSERVATIONS
                               WHERE release_id=%s)
                    FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS
                    WHERE release_id=%s""",
                    (release_id, release_id),
                )
                counts = cursor.fetchone()
                if (
                    counts is None
                    or int(counts[0]) != EXPECTED_COUNTIES
                    or int(counts[1]) != EXPECTED_COUNTIES
                    or int(counts[2]) != EXPECTED_COUNTIES * EXPECTED_OBSERVATIONS_PER_COUNTY
                ):
                    raise SemanticReleaseBlocked(
                        "Candidate does not satisfy the frozen county and observation counts"
                    )
                cursor.execute("SELECT CURRENT_DATABASE()")
                database_row = cursor.fetchone()
                if database_row and str(database_row[0]) == "ONE_HEALTH_LYME_GAP_ATLAS_PROD":
                    _verify_restricted_final_copy_attestations(cursor, release_id)
                cursor.execute(
                    "SELECT current_release_id FROM PRESENTATION.SEMANTIC_RELEASE_POINTER "
                    "WHERE pointer_key='ATLAS'"
                )
                previous = cursor.fetchone()
                previous_id = str(previous[0]) if previous else None
                if previous_id == release_id:
                    raise SemanticReleaseBlocked("Release is already the current pointer")
                cursor.execute(
                    """UPDATE PRESENTATION.SEMANTIC_RELEASES
                    SET status='RETIRED' WHERE status='PUBLISHED' AND release_id<>%s""",
                    (release_id,),
                )
                cursor.execute(
                    """UPDATE PRESENTATION.SEMANTIC_RELEASES
                    SET status='PUBLISHED', approved_by=COALESCE(%s, CURRENT_USER()),
                        approved_at=CURRENT_TIMESTAMP()
                    WHERE release_id=%s AND status='CANDIDATE'""",
                    (approver, release_id),
                )
                cursor.execute(
                    """MERGE INTO PRESENTATION.SEMANTIC_RELEASE_POINTER target
                    USING (SELECT 'ATLAS' AS pointer_key, %s AS current_release_id,
                                  CURRENT_USER() AS updated_by) source
                    ON target.pointer_key=source.pointer_key
                    WHEN MATCHED THEN UPDATE SET current_release_id=source.current_release_id,
                      updated_by=source.updated_by, updated_at=CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (pointer_key, current_release_id, updated_by)
                      VALUES (source.pointer_key, source.current_release_id, source.updated_by)""",
                    (release_id,),
                )
                cursor.execute(
                    """INSERT INTO PRESENTATION.SEMANTIC_RELEASE_EVENTS
                    (event_id, release_id, event_type, previous_release_id, actor, reason)
                    VALUES (%s, %s, 'PUBLISH', %s, CURRENT_USER(), %s)""",
                    (
                        _stable_id(f"semantic-event:{release_id}:PUBLISH:{previous_id or 'none'}"),
                        release_id,
                        previous_id,
                        reason,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"release_id": release_id, "status": "PUBLISHED", "previous_release_id": previous_id}


def rollback_semantic_release(
    settings: SnowflakeSettings, release_id: str, *, reason: str
) -> dict[str, Any]:
    """Move the API pointer to a retained previously published release."""
    if not reason.strip():
        raise ValueError("A rollback reason is required")
    with connect(settings) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=%s",
                    (release_id,),
                )
                target = cursor.fetchone()
                if target is None or str(target[0]) not in {"PUBLISHED", "RETIRED"}:
                    raise SemanticReleaseBlocked(
                        "Rollback target must be a retained published release"
                    )
                cursor.execute(
                    "SELECT current_release_id FROM PRESENTATION.SEMANTIC_RELEASE_POINTER "
                    "WHERE pointer_key='ATLAS'"
                )
                current = cursor.fetchone()
                previous_id = str(current[0]) if current else None
                if previous_id is None:
                    raise SemanticReleaseBlocked("Cannot roll back before a current release exists")
                if previous_id == release_id:
                    raise SemanticReleaseBlocked("Rollback target is already current")
                cursor.execute(
                    "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status='RETIRED' "
                    "WHERE status='PUBLISHED'"
                )
                cursor.execute(
                    "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status='PUBLISHED' "
                    "WHERE release_id=%s",
                    (release_id,),
                )
                cursor.execute(
                    """UPDATE PRESENTATION.SEMANTIC_RELEASE_POINTER
                    SET current_release_id=%s, updated_by=CURRENT_USER(),
                        updated_at=CURRENT_TIMESTAMP()
                    WHERE pointer_key='ATLAS'""",
                    (release_id,),
                )
                cursor.execute(
                    """INSERT INTO PRESENTATION.SEMANTIC_RELEASE_EVENTS
                    (event_id, release_id, event_type, previous_release_id, actor, reason)
                    VALUES (%s, %s, 'ROLLBACK', %s, CURRENT_USER(), %s)""",
                    (
                        _stable_id(f"semantic-event:{release_id}:ROLLBACK:{previous_id or 'none'}"),
                        release_id,
                        previous_id,
                        reason,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"release_id": release_id, "status": "PUBLISHED", "previous_release_id": previous_id}


def _source_from_mapping(value: Any) -> SemanticSource:
    if not isinstance(value, dict):
        raise SemanticReleaseBlocked("Each manifest source must be an object")
    text_fields = (
        "source_key",
        "resource_key",
        "source_id",
        "dataset_id",
        "label",
        "vintage",
        "source_url",
        "note",
        "data_source_version_id",
        "ingestion_run_id",
        "artifact_id",
        "artifact_sha256",
    )
    values = {field: _required_text(value, field) for field in text_fields}
    if any(_PLACEHOLDER.match(str(values[field])) for field in text_fields):
        raise SemanticReleaseBlocked(
            f"Source {values['source_key']} still contains a placeholder lineage value"
        )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(values["artifact_sha256"])):
        raise SemanticReleaseBlocked(
            f"Source {values['source_key']} artifact_sha256 must be a 64-character hex digest"
        )
    try:
        definition_version = int(value.get("definition_version", 1))
    except (TypeError, ValueError) as error:
        raise SemanticReleaseBlocked("definition_version must be a positive integer") from error
    if definition_version < 1:
        raise SemanticReleaseBlocked("definition_version must be a positive integer")
    if not str(values["source_url"]).startswith("https://"):
        raise SemanticReleaseBlocked("Semantic source URLs must use HTTPS")
    field_map_value = value.get("field_map") or {}
    if not isinstance(field_map_value, dict):
        raise SemanticReleaseBlocked("field_map must be an object when supplied")
    field_map: dict[str, tuple[str, ...]] = {}
    for key, names in field_map_value.items():
        if isinstance(names, str):
            field_map[str(key)] = (names,)
        elif isinstance(names, list) and names and all(isinstance(name, str) for name in names):
            field_map[str(key)] = tuple(names)
        else:
            raise SemanticReleaseBlocked(f"field_map.{key} must contain field names")
    return SemanticSource(
        source_key=str(values["source_key"]),
        resource_key=str(values["resource_key"]),
        source_id=str(values["source_id"]),
        dataset_id=str(values["dataset_id"]),
        label=str(values["label"]),
        vintage=str(values["vintage"]),
        source_url=str(values["source_url"]),
        note=str(values["note"]),
        data_source_version_id=str(values["data_source_version_id"]),
        ingestion_run_id=str(values["ingestion_run_id"]),
        artifact_id=str(values["artifact_id"]),
        artifact_sha256=str(values["artifact_sha256"]),
        definition_version=definition_version,
        field_map=field_map,
    )


def _verify_source_gate(
    cursor: Any, source: SemanticSource, *, allow_dev_tick_evidence_exception: bool = False
) -> SourceGate:
    cursor.execute(
        """SELECT status, approved_decision_id, retired_at
        FROM GOVERNANCE.DATA_SOURCE_VERSIONS
        WHERE data_source_version_id=%s AND resource_key=%s""",
        (source.data_source_version_id, source.resource_key),
    )
    version = cursor.fetchone()
    if version is None or str(version[0]) not in {"APPROVED", "CONDITIONAL"}:
        raise SemanticReleaseBlocked(f"Source {source.source_key} is not approved")
    if version[1] is None or version[2] is not None:
        raise SemanticReleaseBlocked(f"Source {source.source_key} has no active approval decision")

    cursor.execute(
        """SELECT status FROM GOVERNANCE.INGESTION_RUNS
        WHERE ingestion_run_id=%s AND resource_key=%s""",
        (source.ingestion_run_id, source.resource_key),
    )
    run = cursor.fetchone()
    if run is None or str(run[0]) not in {"COMPLETED", "SUCCEEDED"}:
        raise SemanticReleaseBlocked(f"Source {source.source_key} lacks a completed ingestion run")

    if source.source_key in {"tick", "pathogen"}:
        # The restricted derivation run references a private, prior evidence run.
        # Do not require that artifact to be copied into the derivative run.
        cursor.execute(
            """SELECT a.sha256 FROM GOVERNANCE.RAW_ARTIFACTS a
            WHERE a.artifact_id=%s AND a.sha256=%s
              AND EXISTS (
                SELECT 1 FROM CONFORMED.RESTRICTED_CDC_"""
            + ("TICK" if source.source_key == "tick" else "PATHOGEN")
            + """_COUNTY_STATUS
                WHERE ingestion_run_id=%s AND evidence_run_id=a.ingestion_run_id
              )""",
            (source.artifact_id, source.artifact_sha256, source.ingestion_run_id),
        )
    else:
        cursor.execute(
            """SELECT sha256 FROM GOVERNANCE.RAW_ARTIFACTS
            WHERE artifact_id=%s AND ingestion_run_id=%s AND sha256=%s""",
            (source.artifact_id, source.ingestion_run_id, source.artifact_sha256),
        )
    artifact = cursor.fetchone()
    if artifact is None:
        raise SemanticReleaseBlocked(
            f"Source {source.source_key} artifact checksum is not retained"
        )

    evidence_only_coverage = _verify_evidence_only_coverage_classification(
        cursor, source, enabled=allow_dev_tick_evidence_exception
    )
    if evidence_only_coverage is not None:
        return SourceGate(source=source, retrieved_at=evidence_only_coverage.approved_at)

    cursor.execute(
        """SELECT COUNT(*), COUNT_IF(severity='BLOCKING' AND status='FAILED')
        FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=%s""",
        (source.ingestion_run_id,),
    )
    quality = cursor.fetchone()
    if quality is None or int(quality[0]) == 0 or int(quality[1]) != 0:
        raise SemanticReleaseBlocked(
            f"Source {source.source_key} lacks passing blocking quality evidence"
        )

    if source.source_key == "human":
        cursor.execute(
            """SELECT MAX(published_at) FROM GOVERNANCE.CDC_PUBLICATIONS
            WHERE data_source_version_id=%s AND ingestion_run_id=%s
              AND published_at IS NOT NULL""",
            (source.data_source_version_id, source.ingestion_run_id),
        )
    else:
        cursor.execute(
            """SELECT MAX(published_at) FROM GOVERNANCE.INGESTION_PUBLICATIONS
            WHERE resource_key=%s AND ingestion_run_id=%s AND status='STAGED'""",
            (source.resource_key, source.ingestion_run_id),
        )
    publication = cursor.fetchone()
    if publication is None or publication[0] is None:
        raise SemanticReleaseBlocked(
            f"Source {source.source_key} lacks staged publication evidence"
        )

    if source.source_key in {"tick", "pathogen"}:
        cursor.execute(
            """SELECT MAX(created_at) FROM GOVERNANCE.INGESTION_REQUESTS
            WHERE ingestion_run_id=%s
              AND (status_code BETWEEN 200 AND 299
                   OR request_purpose='PRIVATE_OPERATOR_VERIFIED_WORKBOOK')""",
            (source.ingestion_run_id,),
        )
    else:
        cursor.execute(
            """SELECT MAX(created_at) FROM GOVERNANCE.INGESTION_REQUESTS
            WHERE ingestion_run_id=%s AND status_code BETWEEN 200 AND 299""",
            (source.ingestion_run_id,),
        )
    retrieved = cursor.fetchone()
    if retrieved is None or retrieved[0] is None:
        raise SemanticReleaseBlocked(f"Source {source.source_key} lacks retrieval evidence")
    return SourceGate(source=source, retrieved_at=retrieved[0])


def _verify_evidence_only_coverage_classification(
    cursor: Any, source: SemanticSource, *, enabled: bool = True
) -> EvidenceOnlyCoverageClassification | None:
    """Return the approved all-unknown exception for the Tier D tick evidence path."""
    if source.source_key != "tick" or not enabled:
        return None
    cursor.execute(
        """SELECT classification_id, canonical_count, reported_county_count,
                  unresolved_county_count, approved_at
        FROM GOVERNANCE.EVIDENCE_ONLY_SOURCE_COVERAGE_CLASSIFICATIONS
        WHERE resource_key=%s AND data_source_version_id=%s AND ingestion_run_id=%s
          AND classification='UNKNOWN_SOURCE_COVERAGE'
        QUALIFY ROW_NUMBER() OVER (ORDER BY approved_at DESC) = 1""",
        (source.resource_key, source.data_source_version_id, source.ingestion_run_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    classification = EvidenceOnlyCoverageClassification(str(row[0]), int(row[3]), row[4])
    if int(row[1]) != EXPECTED_COUNTIES or int(row[2]) != 0:
        raise SemanticReleaseBlocked(
            "Evidence-only tick coverage classification is not all-unknown"
        )
    if classification.unresolved_county_count != EXPECTED_COUNTIES:
        raise SemanticReleaseBlocked(
            "Evidence-only tick coverage classification is not county-complete"
        )
    return classification


def _verify_tick_parity_classification(
    cursor: Any, source: SemanticSource, *, enabled: bool
) -> TickParityClassification | None:
    """Return the approved PROD missing-county classification for tick rows."""
    if source.source_key != "tick" or not enabled:
        return None
    cursor.execute(
        """SELECT classification_id, unresolved_county_count, approved_at
        FROM GOVERNANCE.RESTRICTED_TICK_PARITY_CLASSIFICATIONS
        WHERE resource_key=%s AND data_source_version_id=%s AND ingestion_run_id=%s
          AND classification='UNKNOWN_SOURCE_COVERAGE'
        QUALIFY ROW_NUMBER() OVER (ORDER BY approved_at DESC) = 1""",
        (source.resource_key, source.data_source_version_id, source.ingestion_run_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return TickParityClassification(str(row[0]), int(row[1]), row[2])


def _verify_pathogen_parity_classification(
    cursor: Any, source: SemanticSource, source_rows: Sequence[dict[str, Any]]
) -> PathogenParityClassification | None:
    cursor.execute(
        """SELECT classification_id, unresolved_county_count, approved_at
        FROM GOVERNANCE.RESTRICTED_PATHOGEN_PARITY_CLASSIFICATIONS
        WHERE resource_key=%s AND data_source_version_id=%s AND ingestion_run_id=%s
          AND classification='UNKNOWN_SOURCE_COVERAGE'
        QUALIFY ROW_NUMBER() OVER (ORDER BY approved_at DESC) = 1""",
        (source.resource_key, source.data_source_version_id, source.ingestion_run_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    classification = PathogenParityClassification(str(row[0]), int(row[1]), row[2])
    del source_rows
    return classification


def _read_source_rows(cursor: Any, source: SemanticSource) -> list[dict[str, Any]]:
    columns: tuple[str, ...]
    if source.source_key == "human":
        cursor.execute(
            """SELECT county_fips, report_year, case_status, frequency, payload,
                    source_record_id, data_source_version_id, ingestion_run_id, retrieved_at
            FROM CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP
            WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
            (source.data_source_version_id, source.ingestion_run_id),
        )
        columns = (
            "county_fips",
            "report_year",
            "case_status",
            "frequency",
            "payload",
            "source_record_id",
            "data_source_version_id",
            "ingestion_run_id",
            "retrieved_at",
        )
    elif source.source_key in {"tick", "pathogen"}:
        status_object_fields = (
            "'Ixodes_scapularis_County_Status', scapularis_status, "
            "'Ixodes_pacificus_county_status', pacificus_status"
            if source.source_key == "tick"
            else "'burgdorferi_status', burgdorferi_status"
        )
        table_name = (
            "CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS"
            if source.source_key == "tick"
            else "CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS"
        )
        cursor.execute(
            """SELECT conformed_record_id, resource_key, resource_key, resource_key,
                    source_definition_version, ingestion_run_id, source_record_id,
                    source_row_hash,
                    OBJECT_CONSTRUCT('FIPSCode', county_fips, """
            + status_object_fields
            + """, 'coverage_state', coverage_state), retrieved_at
            FROM """
            + table_name
            + """
            WHERE resource_key=%s AND ingestion_run_id=%s AND source_definition_version=%s""",
            (source.resource_key, source.ingestion_run_id, source.definition_version),
        )
        columns = (
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
    else:
        cursor.execute(
            """SELECT record_id, source_id, dataset_id, resource_key,
                    source_definition_version, ingestion_run_id, source_record_id,
                    source_row_hash, payload, retrieved_at
            FROM CONFORMED.GOVERNED_SOURCE_RECORDS
            WHERE resource_key=%s AND ingestion_run_id=%s AND source_definition_version=%s""",
            (source.resource_key, source.ingestion_run_id, source.definition_version),
        )
        columns = (
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
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _verify_restricted_final_copy_attestations(cursor: Any, release_id: str) -> None:
    """Require owner-recorded CDC final-copy delivery before PROD publication."""
    cursor.execute(
        """SELECT COUNT(DISTINCT resource_key)
        FROM PRESENTATION.SEMANTIC_DATA_SOURCES
        WHERE release_id=%s
          AND resource_key IN ('cdc_tick_ixodes_county_status',
                               'cdc_tick_ixodes_pathogen_status')""",
        (release_id,),
    )
    required = cursor.fetchone()
    if required is None or int(required[0]) == 0:
        return
    cursor.execute(
        """SELECT COUNT(DISTINCT a.resource_key)
        FROM GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS a
        JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
          ON s.release_id=a.semantic_release_id
         AND s.resource_key=a.resource_key
         AND s.source_version_id=a.data_source_version_id
        WHERE a.semantic_release_id=%s
          AND a.resource_key IN ('cdc_tick_ixodes_county_status',
                                 'cdc_tick_ixodes_pathogen_status')""",
        (release_id,),
    )
    attested = cursor.fetchone()
    if attested is None or int(attested[0]) != int(required[0]):
        raise SemanticReleaseBlocked(
            "PROD publication requires a final-copy delivery attestation for every "
            "restricted CDC source"
        )


def _assemble_counties(
    manifest: SemanticManifest,
    source_rows: Mapping[str, list[dict[str, Any]]],
    gates: Mapping[str, SourceGate],
    *,
    pathogen_parity: PathogenParityClassification | None = None,
    tick_coverage: EvidenceOnlyCoverageClassification | None = None,
    tick_parity: TickParityClassification | None = None,
) -> tuple[list[CountyRow], list[tuple[Any, ...]]]:
    identity_source = manifest.source("context_svi")
    identity: dict[str, dict[str, Any]] = {}
    for row in source_rows["context_svi"]:
        record = _record(row.get("payload"))
        fips = _first(record, ("STCNTY", "fips", "FIPS"))
        if not isinstance(fips, str) or not _FIPS.fullmatch(fips):
            raise SemanticReleaseBlocked("SVI identity contains an invalid county FIPS")
        if fips in identity:
            raise SemanticReleaseBlocked(f"SVI identity contains duplicate county FIPS {fips}")
        geometry = record.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "Polygon",
            "MultiPolygon",
        }:
            raise SemanticReleaseBlocked(f"SVI geometry for {fips} is not a county polygon")
        state = _text_or(record.get("ST_ABBR"), "").upper()
        state_name = _text_or(record.get("STATE"), "")
        if not re.fullmatch(r"[A-Z]{2}", state) or not state_name:
            raise SemanticReleaseBlocked(f"SVI identity for {fips} lacks a valid state")
        identity[fips] = {
            "fips": fips,
            "county": _text_or(record.get("COUNTY"), fips),
            "state": state,
            "state_name": state_name,
            "population": _number(record.get("E_TOTPOP")),
            "svi_percentile": _number(record.get("RPL_THEMES")),
            "uninsured_percentile": _number(record.get("EPL_UNINSUR")),
            "uninsured_percent": _number(record.get("EP_UNINSUR")),
            "geometry": geometry,
            "identity_row": row,
        }
    if len(identity) != EXPECTED_COUNTIES:
        raise SemanticReleaseBlocked(
            f"SVI identity coverage is {len(identity)}, not {EXPECTED_COUNTIES}"
        )

    rucc: dict[str, int] = {}
    rucc_rows: dict[str, dict[str, Any]] = {}
    rucc_source = manifest.source("context_rucc")
    for row in source_rows["context_rucc"]:
        record = _record(row.get("payload"))
        if str(_first(record, ("Attribute", "attribute")) or "") != "RUCC_2023":
            continue
        fips = _text_or(_first(record, ("FIPS", "fips")), "")
        value = _number(_first(record, ("Value", "value")))
        if not _FIPS.fullmatch(fips) or value is None or int(value) != value:
            raise SemanticReleaseBlocked("RUCC contains an invalid 2023 county code")
        if fips in rucc:
            raise SemanticReleaseBlocked(f"RUCC contains duplicate county FIPS {fips}")
        rucc[fips] = int(value)
        rucc_rows[fips] = row
    missing_rucc = set(identity) - set(rucc)
    if missing_rucc:
        raise SemanticReleaseBlocked("RUCC does not cover every SVI county identity")

    human = _human_values(source_rows["human"], identity)
    tick = _surveillance_values(
        source_rows["tick"],
        manifest.source("tick"),
        identity,
        kind="tick",
        evidence_only_coverage=tick_coverage,
        tick_parity=tick_parity,
    )
    pathogen = _surveillance_values(
        source_rows["pathogen"],
        manifest.source("pathogen"),
        identity,
        kind="pathogen",
        pathogen_parity=pathogen_parity,
    )
    counties: list[CountyRow] = []
    observations: list[tuple[Any, ...]] = []
    for fips in sorted(identity):
        item = identity[fips]
        human_item = human[fips]
        tick_item = tick[fips]
        pathogen_item = pathogen[fips]
        tick_status = _tick_status(tick_item["scapularis_status"], tick_item["pacificus_status"])
        evidence = _evidence_completeness(
            human_item["human_status"],
            tick_status,
            pathogen_item["burgdorferi_status"],
            item,
            rucc[fips],
        )
        lineage = {
            "human": _lineage(manifest.source("human"), human_item["rows"] or [None]),
            "tick": _lineage(manifest.source("tick"), tick_item["rows"] or [None]),
            "pathogen": _lineage(manifest.source("pathogen"), pathogen_item["rows"] or [None]),
            "context_svi": _lineage(identity_source, [item["identity_row"]]),
            "context_rucc": _lineage(rucc_source, [rucc_rows[fips]]),
        }
        if pathogen_item.get("parity_classification_id"):
            lineage["pathogen"]["parity_classification_id"] = pathogen_item[
                "parity_classification_id"
            ]
        if tick_item.get("coverage_classification_id"):
            lineage["tick"]["coverage_classification_id"] = tick_item["coverage_classification_id"]
        counties.append(
            CountyRow(
                values=(
                    manifest.release_id,
                    fips,
                    item["county"],
                    item["state"],
                    item["state_name"],
                    item["population"],
                    item["state"] not in {"AK", "HI"},
                    human_item["human_status"],
                    human_item["case_count"],
                    human_item["incidence"],
                    human_item["state_unallocated"],
                    tick_status,
                    tick_item["scapularis_status"],
                    tick_item["pacificus_status"],
                    pathogen_item["burgdorferi_status"],
                    item["svi_percentile"],
                    item["uninsured_percentile"],
                    item["uninsured_percent"],
                    rucc[fips],
                    evidence,
                    json.dumps(item["geometry"], separators=(",", ":")),
                    json.dumps(lineage, separators=(",", ":")),
                ),
                lineage=lineage,
            )
        )
        observations.extend(
            _county_observations(
                manifest,
                gates,
                fips,
                item,
                human_item,
                tick_item,
                pathogen_item,
                rucc[fips],
                rucc_rows[fips],
            )
        )
    return counties, observations


def _human_values(
    rows: Iterable[dict[str, Any]], identity: Mapping[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {
        fips: {
            "case_count": None,
            "incidence": None,
            "human_status": "no_county_linked_record",
            "state_unallocated": 0,
            "rows": [],
        }
        for fips in identity
    }
    state_unallocated: defaultdict[str, int] = defaultdict(int)
    state_unallocated_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        year = _number(row.get("report_year"))
        if year != 2023:
            continue
        payload = _record(row.get("payload"))
        fips = _text_or(row.get("county_fips"), "")
        frequency = _number(row.get("frequency"))
        status = str(row.get("case_status") or "").casefold()
        if frequency is None:
            raise SemanticReleaseBlocked("Human surveillance contains a non-numeric frequency")
        if status in {"confirmed", "probable"} and _FIPS.fullmatch(fips):
            if fips not in grouped:
                raise SemanticReleaseBlocked(f"Human surveillance references unknown county {fips}")
            grouped[fips]["case_count"] = int(grouped[fips]["case_count"] or 0) + int(frequency)
            grouped[fips]["rows"].append(row)
        elif fips.casefold() in {"unknown", "suppressed", "not reported"}:
            state = _state_code(payload.get("state"))
            if state is None:
                if str(payload.get("state") or "").strip().casefold() in {
                    "unknown",
                    "suppressed",
                }:
                    # The source explicitly withholds geography for these rows.
                    # They remain in the immutable source artifact but cannot be
                    # allocated to a state or county presentation record.
                    continue
                raise SemanticReleaseBlocked(
                    "Human surveillance has a state-unallocated row without a valid state"
                )
            state_unallocated[state] += int(frequency)
            state_unallocated_rows[state].append(row)
    for fips, value in grouped.items():
        if value["case_count"] is not None:
            value["human_status"] = "published_count_floor"
            population = identity[fips]["population"]
            value["incidence"] = (
                round(value["case_count"] / population * 100_000, 2) if population else None
            )
        value["state_unallocated"] = state_unallocated.get(identity[fips]["state"], 0)
        value["state_unallocated_rows"] = state_unallocated_rows.get(identity[fips]["state"], [])
    return grouped


def _surveillance_values(
    rows: Iterable[dict[str, Any]],
    source: SemanticSource,
    identity: Mapping[str, dict[str, Any]],
    *,
    kind: str,
    pathogen_parity: PathogenParityClassification | None = None,
    evidence_only_coverage: EvidenceOnlyCoverageClassification | None = None,
    tick_parity: TickParityClassification | None = None,
) -> dict[str, dict[str, Any]]:
    source_rows = list(rows)
    output: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        record = _record(row.get("payload"))
        fips = _text_or(_mapped(record, source, "fips"), "")
        if not _FIPS.fullmatch(fips):
            raise SemanticReleaseBlocked(f"{source.source_key} contains an unknown county identity")
        if fips not in identity:
            if kind in {"pathogen", "tick"}:
                continue
            raise SemanticReleaseBlocked(f"{source.source_key} contains an unknown county identity")
        if fips in output:
            raise SemanticReleaseBlocked(f"{source.source_key} contains duplicate county rows")
        if kind == "tick":
            scapularis = _required_status(record, source, "scapularis_status")
            pacificus = _required_status(record, source, "pacificus_status")
            output[fips] = {
                "scapularis_status": scapularis,
                "pacificus_status": pacificus,
                "rows": [row],
            }
        else:
            pathogen = _required_status(record, source, "burgdorferi_status")
            output[fips] = {"burgdorferi_status": pathogen, "rows": [row]}
    missing = set(identity) - set(output)
    if missing and kind == "pathogen" and pathogen_parity is not None:
        if len(output) + pathogen_parity.unresolved_county_count != len(identity):
            raise SemanticReleaseBlocked(
                "Pathogen parity classification count does not match coverage"
            )
        for fips in missing:
            output[fips] = {
                "burgdorferi_status": "Unknown",
                "rows": [
                    {
                        "source_record_id": pathogen_parity.classification_id,
                        "retrieved_at": pathogen_parity.approved_at,
                    }
                ],
                "parity_classification_id": pathogen_parity.classification_id,
            }
    if missing and kind == "tick" and evidence_only_coverage is not None:
        if len(source_rows) + evidence_only_coverage.unresolved_county_count != len(identity):
            raise SemanticReleaseBlocked(
                "Evidence-only tick coverage classification count does not match coverage"
            )
        for fips in missing:
            output[fips] = {
                "scapularis_status": "Unknown",
                "pacificus_status": "Unknown",
                "rows": [
                    {
                        "source_record_id": evidence_only_coverage.classification_id,
                        "retrieved_at": evidence_only_coverage.approved_at,
                    }
                ],
                "coverage_classification_id": evidence_only_coverage.classification_id,
            }
    if missing and kind == "tick" and tick_parity is not None:
        if len(output) + tick_parity.unresolved_county_count != len(identity):
            raise SemanticReleaseBlocked("Tick parity classification count does not match coverage")
        for fips in missing:
            output[fips] = {
                "scapularis_status": "Unknown",
                "pacificus_status": "Unknown",
                "rows": [
                    {
                        "source_record_id": tick_parity.classification_id,
                        "retrieved_at": tick_parity.approved_at,
                    }
                ],
                "parity_classification_id": tick_parity.classification_id,
            }
    if set(output) != set(identity):
        raise SemanticReleaseBlocked(
            f"{source.source_key} does not provide explicit county coverage"
        )
    return output


def _county_observations(
    manifest: SemanticManifest,
    gates: Mapping[str, SourceGate],
    fips: str,
    identity: Mapping[str, Any],
    human: Mapping[str, Any],
    tick: Mapping[str, Any],
    pathogen: Mapping[str, Any],
    rucc: int,
    rucc_row: Mapping[str, Any],
) -> list[tuple[Any, ...]]:
    definitions = (
        (
            "county_reference",
            "county_fips",
            fips,
            "OBSERVED",
            "context_svi",
            identity["identity_row"],
        ),
        (
            "county_geometry",
            "geometry",
            identity["geometry"],
            "OBSERVED",
            "context_svi",
            identity["identity_row"],
        ),
        (
            "human_disease_burden",
            "human_status",
            human["human_status"],
            _value_state(human["human_status"]),
            "human",
            human["rows"][0] if human["rows"] else None,
        ),
        (
            "human_disease_burden",
            "case_count_floor_2023",
            human["case_count"],
            _value_state(human["case_count"]),
            "human",
            human["rows"][0] if human["rows"] else None,
        ),
        (
            "human_disease_burden",
            "incidence_floor_2023",
            human["incidence"],
            _value_state(human["incidence"]),
            "human",
            human["rows"][0] if human["rows"] else None,
        ),
        (
            "human_disease_burden",
            "state_unallocated_records_2023",
            human["state_unallocated"],
            _value_state(human["state_unallocated"]),
            "human",
            human["state_unallocated_rows"][0] if human["state_unallocated_rows"] else None,
        ),
        (
            "tick_surveillance",
            "scapularis_status",
            tick["scapularis_status"],
            _value_state(tick["scapularis_status"]),
            "tick",
            tick["rows"][0],
        ),
        (
            "tick_surveillance",
            "pacificus_status",
            tick["pacificus_status"],
            _value_state(tick["pacificus_status"]),
            "tick",
            tick["rows"][0],
        ),
        (
            "pathogen_surveillance",
            "burgdorferi_status",
            pathogen["burgdorferi_status"],
            _value_state(pathogen["burgdorferi_status"]),
            "pathogen",
            pathogen["rows"][0],
        ),
        (
            "population_context",
            "population_2022",
            identity["population"],
            _value_state(identity["population"]),
            "context_svi",
            identity["identity_row"],
        ),
        (
            "population_context",
            "svi_percentile_2022",
            identity["svi_percentile"],
            _value_state(identity["svi_percentile"]),
            "context_svi",
            identity["identity_row"],
        ),
        (
            "population_context",
            "uninsured_percentile_2022",
            identity["uninsured_percentile"],
            _value_state(identity["uninsured_percentile"]),
            "context_svi",
            identity["identity_row"],
        ),
        (
            "population_context",
            "uninsured_percent_2022",
            identity["uninsured_percent"],
            _value_state(identity["uninsured_percent"]),
            "context_svi",
            identity["identity_row"],
        ),
        (
            "rurality_context",
            "rucc_2023",
            rucc,
            _value_state(rucc),
            "context_rucc",
            rucc_row,
        ),
    )
    rows: list[tuple[Any, ...]] = []
    for _indicator_id, measure_id, value, state, source_key, source_row in definitions:
        source = manifest.source(source_key)
        gate = gates[source_key]
        rows.append(
            (
                _stable_id(f"observation:{manifest.release_id}:{measure_id}:{fips}"),
                manifest.release_id,
                measure_id,
                fips,
                source_key,
                source.data_source_version_id,
                source.ingestion_run_id,
                source.artifact_id,
                _source_record_id(source_row),
                _source_hash(source_row),
                json.dumps(value, separators=(",", ":"), default=str)
                if value is not None
                else None,
                state,
                _row_retrieved_at(source_row, gate.retrieved_at),
                "COUNTY_FIPS_5",
                "2023" if source_key == "human" else source.vintage,
                SEMANTIC_TRANSFORMATION,
                "PASSED",
                _measure_limitation(measure_id),
            )
        )
    return rows


def _insert_release(cursor: Any, manifest: SemanticManifest, bundle_sha256: str) -> None:
    cursor.execute(
        """INSERT INTO PRESENTATION.SEMANTIC_RELEASES
        (release_id, schema_version, generated_at, scope, bundle_sha256,
         score_defaults, methodology_version, limitations, status, source_manifest, created_by)
        SELECT %s, %s, TO_TIMESTAMP_LTZ(%s), %s, %s, PARSE_JSON(%s), %s, %s,
               'CANDIDATE', PARSE_JSON(%s), CURRENT_USER()""",
        (
            manifest.release_id,
            manifest.schema_version,
            manifest.generated_at,
            manifest.scope,
            bundle_sha256,
            json.dumps(manifest.score_defaults, separators=(",", ":")),
            manifest.methodology_version,
            manifest.limitations,
            json.dumps(manifest.raw, separators=(",", ":")),
        ),
    )


def _insert_sources(cursor: Any, manifest: SemanticManifest) -> None:
    rows = [
        (
            manifest.release_id,
            source.source_key,
            source.resource_key,
            source.source_id,
            source.dataset_id,
            source.label,
            source.vintage,
            source.source_url,
            source.note,
            source.data_source_version_id,
            source.ingestion_run_id,
            source.artifact_id,
        )
        for source in manifest.sources
    ]
    cursor.executemany(
        """INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES
        (release_id, source_key, resource_key, source_id, dataset_id, label, vintage,
         source_url, note, source_version_id, ingestion_run_id, artifact_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        rows,
    )


def _insert_hierarchy(cursor: Any, manifest: SemanticManifest) -> None:
    datasets = {
        source.dataset_id: (
            manifest.release_id,
            source.dataset_id,
            source.source_key,
            source.label,
            "COUNTY_FIPS_5",
            source.vintage,
            source.note,
        )
        for source in manifest.sources
    }
    cursor.executemany(
        """INSERT INTO PRESENTATION.SEMANTIC_DATASETS
        (release_id, dataset_id, source_key, dataset_name, geography_semantics,
         temporal_semantics, limitations) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        list(datasets.values()),
    )
    indicators = [
        (
            manifest.release_id,
            "county_reference",
            "County identity and geometry",
            "Stable FIPS join identity and display geometry.",
            "Display geometry is not a causal or risk surface.",
        ),
        (
            manifest.release_id,
            "human_disease_burden",
            "Human Lyme surveillance",
            "Published county-linked surveillance values and safe missingness states.",
            "Published values are privacy-protected floors, not complete incidence.",
        ),
        (
            manifest.release_id,
            "tick_surveillance",
            "Tick surveillance",
            "County tick status by species.",
            "No records is not absence; status is not abundance or individual risk.",
        ),
        (
            manifest.release_id,
            "pathogen_surveillance",
            "Tickborne pathogen surveillance",
            "Distinct pathogen status observations.",
            "Pathogen status is not individual infection risk or diagnosis.",
        ),
        (
            manifest.release_id,
            "population_context",
            "Population and vulnerability context",
            "SVI and population context.",
            "Contextual measures are not causal drivers or individual risk measures.",
        ),
        (
            manifest.release_id,
            "rurality_context",
            "Rurality context",
            "USDA ERS county rurality classification.",
            "RUCC is a contextual category and vintage-specific.",
        ),
    ]
    cursor.executemany(
        """INSERT INTO PRESENTATION.SEMANTIC_INDICATORS
        (release_id, indicator_id, label, description, limitation)
        VALUES (%s,%s,%s,%s,%s)""",
        indicators,
    )
    measures = [
        (
            "county_reference",
            "county_fips",
            "County FIPS",
            "string",
            "identifier",
            "COUNTY_FIPS_5",
            "snapshot",
            "Stable five-digit FIPS is identity; labels are display values.",
            "semantic identity mapping",
            "Labels do not define identity.",
        ),
        (
            "county_reference",
            "county_geometry",
            "County geometry",
            "object",
            "GeoJSON",
            "COUNTY_FIPS_5",
            "snapshot",
            "Missing geometry blocks release.",
            "SVI geometry contract",
            "Geometry is a display boundary.",
        ),
        (
            "human_disease_burden",
            "human_status",
            "Human surveillance status",
            "string",
            "status",
            "COUNTY_FIPS_5",
            "2023",
            "No county-linked record is not zero.",
            "source-native status mapping",
            "Published floors are not complete incidence.",
        ),
        (
            "human_disease_burden",
            "case_count_floor_2023",
            "Published case-count floor",
            "integer",
            "cases",
            "COUNTY_FIPS_5",
            "2023",
            "Null means no county-linked published value.",
            "x5j9 confirmed plus probable",
            "Privacy-protected floor.",
        ),
        (
            "human_disease_burden",
            "incidence_floor_2023",
            "Published incidence floor",
            "number",
            "per 100,000",
            "COUNTY_FIPS_5",
            "2023",
            "Null means no county-linked published value.",
            "case floor divided by population",
            "Not complete incidence.",
        ),
        (
            "human_disease_burden",
            "state_unallocated_records_2023",
            "State-unallocated records",
            "integer",
            "records",
            "STATE",
            "2023",
            "Retained separately from county-linked values.",
            "source-native aggregation",
            "Not assignable to a county.",
        ),
        (
            "tick_surveillance",
            "scapularis_status",
            "Ixodes scapularis status",
            "string",
            "status",
            "COUNTY_FIPS_5",
            "as published",
            "No records is not absence.",
            "source-native status mapping",
            "Not abundance or individual risk.",
        ),
        (
            "tick_surveillance",
            "pacificus_status",
            "Ixodes pacificus status",
            "string",
            "status",
            "COUNTY_FIPS_5",
            "as published",
            "No records is not absence.",
            "source-native status mapping",
            "Not abundance or individual risk.",
        ),
        (
            "pathogen_surveillance",
            "burgdorferi_status",
            "Borrelia burgdorferi status",
            "string",
            "status",
            "COUNTY_FIPS_5",
            "as published",
            "No records is not absence.",
            "distinct pathogen mapping",
            "Not individual infection risk.",
        ),
        (
            "population_context",
            "population_2022",
            "SVI population estimate",
            "integer",
            "people",
            "COUNTY_FIPS_5",
            "2018-2022 ACS",
            "Source-provided population estimate.",
            "SVI source mapping",
            "Context, not individual exposure.",
        ),
        (
            "population_context",
            "svi_percentile_2022",
            "SVI percentile",
            "number",
            "percentile",
            "COUNTY_FIPS_5",
            "2018-2022 ACS",
            "National percentile.",
            "SVI source mapping",
            "Not causal.",
        ),
        (
            "population_context",
            "uninsured_percentile_2022",
            "Uninsured percentile",
            "number",
            "percentile",
            "COUNTY_FIPS_5",
            "2018-2022 ACS",
            "National percentile.",
            "SVI source mapping",
            "Not causal.",
        ),
        (
            "population_context",
            "uninsured_percent_2022",
            "Uninsured percent",
            "number",
            "percent",
            "COUNTY_FIPS_5",
            "2018-2022 ACS",
            "Source-provided percent.",
            "SVI source mapping",
            "Not causal.",
        ),
        (
            "rurality_context",
            "rucc_2023",
            "RUCC 2023",
            "integer",
            "code",
            "COUNTY_FIPS_5",
            "2023",
            "Vintage-specific code.",
            "RUCC_2023 attribute mapping",
            "Not causal.",
        ),
    ]
    cursor.executemany(
        """INSERT INTO PRESENTATION.SEMANTIC_MEASURES
        (release_id, measure_id, indicator_id, label, data_type, unit, geography_semantics,
         temporal_resolution, missingness_semantics, methodology, limitation)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [(manifest.release_id, *measure) for measure in measures],
    )


def _insert_counties(cursor: Any, release_id: str, counties: Sequence[CountyRow]) -> None:
    _execute_bound_value_batches(
        cursor,
        """INSERT INTO PRESENTATION.SEMANTIC_COUNTY_ATLAS
        (release_id, fips, county, state, state_name, population, in_contiguous_tick_scope,
         human_status, case_count_floor_2023, incidence_floor_2023,
         state_unallocated_records_2023, tick_status, scapularis_status, pacificus_status,
         burgdorferi_status, svi_percentile, uninsured_percentile, uninsured_percent,
         rucc_2023, evidence_completeness, geometry_json, lineage)
        SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
               PARSE_JSON($21),PARSE_JSON($22)
        FROM VALUES""",
        [row.values for row in counties],
        row_width=22,
        batch_size=50,
    )


def _insert_observations(
    cursor: Any, release_id: str, observations: Sequence[tuple[Any, ...]]
) -> None:
    _execute_bound_value_batches(
        cursor,
        """INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS
        (observation_id, release_id, measure_id, fips, source_key, source_version_id,
         ingestion_run_id, artifact_id, source_record_id, source_row_hash, value, value_state,
         retrieved_at, geography_semantics, temporal_window, transformation_version,
         quality_state, limitations)
        SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,PARSE_JSON($11),$12,$13,$14,$15,$16,$17,$18
        FROM VALUES""",
        [(row[0], release_id, *row[2:]) for row in observations],
        row_width=18,
        batch_size=500,
    )


def _execute_bound_value_batches(
    cursor: Any,
    statement_prefix: str,
    rows: Sequence[tuple[Any, ...]],
    *,
    row_width: int,
    batch_size: int,
) -> None:
    """Execute bounded, client-bound VALUES batches without driver SQL rewriting."""
    if not rows:
        return
    if any(len(row) != row_width for row in rows):
        raise ValueError("Semantic bulk-insert row width does not match its statement")
    placeholder_row = f"({','.join('%s' for _ in range(row_width))})"
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        parameters = tuple(value for row in batch for value in row)
        cursor.execute(f"{statement_prefix} {','.join(placeholder_row for _ in batch)}", parameters)


def _assert_release_absent(cursor: Any, release_id: str) -> None:
    cursor.execute(
        "SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=%s", (release_id,)
    )
    row = cursor.fetchone()
    if row and int(row[0]) != 0:
        raise SemanticReleaseBlocked(f"Release {release_id} already exists and is immutable")


def _bundle_sha256(manifest: SemanticManifest, counties: Sequence[CountyRow]) -> str:
    payload = {
        "manifest": manifest.raw,
        "release_id": manifest.release_id,
        "schema_version": manifest.schema_version,
        "methodology_version": manifest.methodology_version,
        "counties": [{"values": list(row.values[1:]), "lineage": row.lineage} for row in counties],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _record(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise SemanticReleaseBlocked("A conformed payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise SemanticReleaseBlocked("A conformed payload is not an object")
    record = payload.get("record")
    return record if isinstance(record, dict) else payload


def _mapped(record: Mapping[str, Any], source: SemanticSource, field: str) -> Any:
    names = source.field_map.get(field, ())
    return _first(record, names)


def _required_status(record: Mapping[str, Any], source: SemanticSource, field: str) -> str:
    value = _mapped(record, source, field)
    if value in (None, ""):
        raise SemanticReleaseBlocked(
            f"{source.source_key} is missing an explicit {field}; use 'No records' when applicable"
        )
    return _text_or(value, "No records")


def _first(record: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise SemanticReleaseBlocked(f"Expected numeric value, received {value!r}") from error


def _text_or(value: Any, default: str) -> str:
    return str(value).strip() if value not in (None, "") else default


def _state_code(value: Any) -> str | None:
    text = _text_or(value, "").upper()
    if len(text) == 2 and text.isalpha():
        return text
    return {
        "ALABAMA": "AL",
        "ALASKA": "AK",
        "ARIZONA": "AZ",
        "ARKANSAS": "AR",
        "CALIFORNIA": "CA",
        "COLORADO": "CO",
        "CONNECTICUT": "CT",
        "DELAWARE": "DE",
        "FLORIDA": "FL",
        "GEORGIA": "GA",
        "HAWAII": "HI",
        "IDAHO": "ID",
        "ILLINOIS": "IL",
        "INDIANA": "IN",
        "IOWA": "IA",
        "KANSAS": "KS",
        "KENTUCKY": "KY",
        "LOUISIANA": "LA",
        "MAINE": "ME",
        "MARYLAND": "MD",
        "MASSACHUSETTS": "MA",
        "MICHIGAN": "MI",
        "MINNESOTA": "MN",
        "MISSISSIPPI": "MS",
        "MISSOURI": "MO",
        "MONTANA": "MT",
        "NEBRASKA": "NE",
        "NEVADA": "NV",
        "NEW HAMPSHIRE": "NH",
        "NEW JERSEY": "NJ",
        "NEW MEXICO": "NM",
        "NEW YORK": "NY",
        "NORTH CAROLINA": "NC",
        "NORTH DAKOTA": "ND",
        "OHIO": "OH",
        "OKLAHOMA": "OK",
        "OREGON": "OR",
        "PENNSYLVANIA": "PA",
        "RHODE ISLAND": "RI",
        "SOUTH CAROLINA": "SC",
        "SOUTH DAKOTA": "SD",
        "TENNESSEE": "TN",
        "TEXAS": "TX",
        "UTAH": "UT",
        "VERMONT": "VT",
        "VIRGINIA": "VA",
        "WASHINGTON": "WA",
        "WEST VIRGINIA": "WV",
        "WISCONSIN": "WI",
        "WYOMING": "WY",
        "DISTRICT OF COLUMBIA": "DC",
    }.get(text)


def _tick_status(scapularis: str, pacificus: str) -> str:
    values = {scapularis.casefold(), pacificus.casefold()}
    if "established" in values:
        return "Established"
    if "reported" in values:
        return "Reported"
    # An accepted evidence-only coverage classification deliberately has no
    # source-native county rows.  It must remain distinct from the publisher's
    # affirmative "No records" value in the product-facing rollup.
    if "unknown" in values:
        return "Unknown"
    return "No records"


def _evidence_completeness(
    human_status: str, tick: str, pathogen: str, identity: Mapping[str, Any], rucc: int
) -> int:
    available = sum(
        (
            human_status == "published_count_floor",
            tick in {"Established", "Reported"},
            pathogen == "Present",
            identity["svi_percentile"] is not None,
            identity["uninsured_percentile"] is not None,
            rucc is not None,
        )
    )
    return int(round(available / 6 * 100))


def _lineage(source: SemanticSource, rows: Iterable[dict[str, Any] | None]) -> dict[str, Any]:
    retained = [row for row in rows if isinstance(row, dict)]
    return {
        "source_key": source.source_key,
        "resource_key": source.resource_key,
        "source_version_id": source.data_source_version_id,
        "ingestion_run_id": source.ingestion_run_id,
        "artifact_id": source.artifact_id,
        "source_record_ids": [_source_record_id(row) for row in retained],
        "source_row_hashes": [_source_hash(row) for row in retained],
    }


def _source_record_id(row: Mapping[str, Any] | None) -> str | None:
    if row is None:
        return None
    value = row.get("source_record_id") or row.get("record_id")
    return str(value) if value is not None else None


def _source_hash(row: Mapping[str, Any] | None) -> str | None:
    if row is None:
        return None
    value = row.get("source_row_hash")
    return str(value) if value is not None else None


def _row_retrieved_at(row: Mapping[str, Any] | None, fallback: Any) -> Any:
    return row.get("retrieved_at") if row and row.get("retrieved_at") is not None else fallback


def _value_state(value: Any) -> str:
    if value is None:
        return "MISSING"
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized == "no records":
            return "NO_RECORDS"
        if normalized == "no_county_linked_record":
            return "NO_COUNTY_LINKED_RECORD"
        if normalized in {"unknown", "suppressed", "not reported"}:
            return normalized.upper().replace(" ", "_")
    if value == 0 or value == 0.0:
        return "ZERO"
    return "OBSERVED"


def _measure_limitation(measure_id: str) -> str:
    if (
        measure_id.startswith("human")
        or measure_id.startswith("case")
        or measure_id.startswith("incidence")
    ):
        return (
            "Published surveillance values are privacy-protected floors, "
            "not complete incidence estimates."
        )
    if "status" in measure_id or measure_id == "burgdorferi_status":
        return "No records is not absence; status is not abundance, diagnosis, or individual risk."
    if measure_id == "county_geometry":
        return "Geometry is a display boundary with source/version lineage."
    return "Contextual source measure; not a causal driver or individual risk measure."


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_text(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SemanticReleaseBlocked(f"Manifest field {field} is required")
    return value.strip()
