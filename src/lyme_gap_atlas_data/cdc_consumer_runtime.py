"""CDC intended-reader adapter. Read-only; no approval, publication or fixture mode.

Only packaged immutable metadata and the existing secure lineage view enter the
consumer writer. A retained review packet binds physical and semantic revisions;
the adapter never manufactures release membership from a successful projection.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .cdc_consumer_admission import (
    PERIOD,
    RELEASE_BUNDLES,
    RELEASE_ID,
    SLICES,
    TARGET_RELEASE_ID,
    is_cdc_metadata,
)
from .semantic_metadata import validate_metadata_revisions
from .semantic_source_mappings import load_mapping_registry, map_record
from .surveillance_evidence_mapping import project_surveillance_evidence

Query = Callable[[str, tuple[str, ...]], list[dict[str, Any]]]
PENDING_IDS = {
    "scapularis_status": "metadata-revision:v1:"
    "c146e1252bc3a7f3c6891ef82600a519616745e588f49c02519f1c4a962e489e",
    "burgdorferi_status": "metadata-revision:v1:"
    "4bb80138955c0bedd8c802453cdfeae88948cdfc8dca3119566d6aaad31a0c74",
}
IDENTITY_SQL = (
    "SELECT CURRENT_USER() AS USER, CURRENT_ROLE() AS ROLE, "
    "CURRENT_DATABASE() AS DATABASE, CURRENT_WAREHOUSE() AS WAREHOUSE"
)
AUTHORITY_SQL = """SELECT observation_id, release_id, measure_id, county_fips,
 temporal_window, source_version_id, governed_source_version_id,
 ingestion_run_id, governed_ingestion_run_id, artifact_id, artifact_sha256,
 semantic_source_record_id, semantic_source_row_hash, source_id, dataset_id,
 resource_key, release_bundle_sha256, conformed_record_id,
 governed_source_record_id, governed_source_row_hash, record_match_kind,
 cdc_runtime_authority
 FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V
 WHERE release_id=%s AND measure_id=%s AND county_fips=%s
 AND source_version_id=%s LIMIT 2"""


class CDCConsumerUnavailable(ValueError):
    """Safe operator error: private lineage and database diagnostics stay private."""


def _resources() -> Traversable:
    packaged = files("lyme_gap_atlas_data").joinpath("cdc_metadata")
    if packaged.is_dir():
        return packaged
    # Editable checkout only. Wheels/containers use force-included canonical resources.
    return Path(__file__).resolve().parents[2] / "docs/contracts/semantic-domain/cdc-2025"


def _json(resource: Traversable) -> Any:
    try:
        return json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CDCConsumerUnavailable("accepted CDC metadata resource unavailable") from None


def _metadata(root: Traversable, measure: str, release_id: str = RELEASE_ID) -> dict[str, Any]:
    if release_id not in RELEASE_BUNDLES:
        raise CDCConsumerUnavailable("unreviewed CDC release")
    revision = 3 if release_id == TARGET_RELEASE_ID else 2
    binding = _json(
        root.joinpath(
            "release-binding-2026-10-15.json" if revision == 3 else "release-binding.json"
        )
    )
    if (
        binding.get("release_id") != release_id
        or binding.get("bundle_sha256") != RELEASE_BUNDLES[release_id]
        or binding.get("slices") != SLICES
    ):
        raise CDCConsumerUnavailable("packaged CDC release scope mismatch")
    pending = _json(root.joinpath(f"{measure}.metadata.json"))
    reviewed = _json(root.joinpath(f"{measure}.revision-{revision}.metadata.json"))
    revisions = [pending]
    if revision == 3:
        revisions.append(_json(root.joinpath(f"{measure}.revision-2.metadata.json")))
    validate_metadata_revisions([*revisions, reviewed])
    if (
        pending.get("revision_id") != PENDING_IDS[measure]
        or pending.get("steward_review", {}).get("state") != "PENDING"
        or reviewed.get("metadata_revision") != revision
        or reviewed.get("steward_review", {}).get("state") != "REVIEWED"
        or reviewed.get("visibility") != "CONSUMER_SAFE"
        or not is_cdc_metadata(reviewed)
    ):
        raise CDCConsumerUnavailable("immutable reviewed CDC metadata required")
    return dict(reviewed)


def _packet(
    facts: Mapping[str, Any], metadata: Mapping[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    accepted = []
    for review in facts.get("review_decisions") or []:
        if (
            not isinstance(review, Mapping)
            or review.get("decision") not in {"APPROVED", "APPROVED_WITH_CONDITIONS"}
            or review.get("active_steward") is not True
            or not review.get("reviewer")
            or not review.get("decision_id")
            or not isinstance(review.get("rationale"), str)
            or len(review["rationale"].strip()) < 10
            or not review.get("decided_at")
            or (
                row["release_id"] == RELEASE_ID
                and review.get("decided_at") != metadata["steward_review"]["reviewed_at"]["value"]
            )
            or not isinstance(review.get("conditions"), list)
        ):
            continue
        for condition in review["conditions"]:
            packet = (
                condition.get("cdc_consumer_admission") if isinstance(condition, dict) else None
            )
            if not isinstance(packet, dict):
                continue
            if (
                packet.get("release_id") == row["release_id"]
                and packet.get("bundle_sha256") == RELEASE_BUNDLES.get(row["release_id"])
                and packet.get("scope") == SLICES[metadata["measure"]["measure_id"]]
                and packet.get("metadata_revision_id") == metadata["revision_id"]
                and isinstance(packet.get("decision_reference"), str)
                and len(packet["decision_reference"].strip()) >= 6
                and isinstance(packet.get("observation_bindings"), dict)
                and row["observation_id"] in packet["observation_bindings"]
                and (
                    row["release_id"] == RELEASE_ID
                    or (
                        packet.get("reviewed_at")
                        == metadata["steward_review"]["reviewed_at"]["value"]
                        and review["decided_at"] >= packet["reviewed_at"]
                    )
                )
            ):
                accepted.append(packet)
    if len(accepted) != 1:
        raise CDCConsumerUnavailable("exact retained steward/release decision required")
    return dict(accepted[0])


def _inputs(
    row: dict[str, Any], metadata: Mapping[str, Any], *, expected_status: str = "PUBLISHED"
) -> tuple[dict[str, Any], dict[str, Any]]:
    measure = metadata["measure"]["measure_id"]
    scope = SLICES[measure]
    release_id = row["release_id"]
    bundle = RELEASE_BUNDLES.get(release_id)
    if bundle is None or expected_status not in {"PUBLISHED", "CANDIDATE", "RETIRED"}:
        raise CDCConsumerUnavailable("unreviewed CDC release")
    facts = row["cdc_runtime_authority"]
    if isinstance(facts, str):
        facts = json.loads(facts)
    if not isinstance(facts, dict):
        raise CDCConsumerUnavailable("CDC reader authority not available")
    if (
        any(row.get(k) != v for k, v in scope.items())
        or row.get("source_id") != "cdc_arbonet_tick_module"
        or facts.get("source_vintage") != f"through {PERIOD}"
        or row.get("measure_id") != measure
        or row.get("release_bundle_sha256") != bundle
        or facts.get("release_status") != expected_status
        or row.get("temporal_window") != f"through {PERIOD}"
        or row.get("record_match_kind") != "RESTRICTED_CDC_CONFORMED"
        or row.get("governed_source_version_id") != scope["source_version_id"]
        or row.get("governed_ingestion_run_id") != row.get("ingestion_run_id")
        or facts.get("source_status") not in {"APPROVED", "CONDITIONAL"}
        or facts.get("source_retired_at") is not None
        or facts.get("source_decision") not in {"APPROVED", "APPROVED_WITH_CONDITIONS"}
        or not facts.get("source_decision_id")
        or facts.get("source_review_version") != scope["source_version_id"]
        or facts.get("source_review_resource") != scope["resource_key"]
        or not isinstance(facts.get("source_conditions"), list)
        or (facts.get("source_status") == "CONDITIONAL" and not facts["source_conditions"])
        or facts.get("geography_semantics") != "COUNTY_FIPS_5"
        or facts.get("transformation_version") != "semantic_county_assembly_v1"
        or facts.get("derivation_mode") != "RESTRICTED_FULL_PROD"
        or facts.get("derivation_status") != "COMPLETED"
        or facts.get("evidence_status") != "COMPLETED"
        or facts.get("evidence_mode") != "EVIDENCE_ONLY"
        or facts.get("evidence_resource") != scope["resource_key"]
        or facts.get("artifact_type") != "SOURCE_WORKBOOK_EVIDENCE"
        or facts.get("artifact_run_id") != facts.get("evidence_run_id")
        or facts.get("source_definition_version") != 1
        or facts.get("record_resource") != scope["resource_key"]
        or facts.get("record_county") != row.get("county_fips")
        or facts.get("value") != facts.get("publisher_value")
        or facts.get("coverage_state") == "UNKNOWN_SOURCE_COVERAGE"
        or row.get("semantic_source_row_hash") != row.get("governed_source_row_hash")
        or row.get("semantic_source_record_id")
        not in {row.get("governed_source_record_id"), row.get("conformed_record_id")}
    ):
        raise CDCConsumerUnavailable("CDC source/release/record authority mismatch")
    packet = _packet(facts, metadata, row)
    source = dict(
        scope,
        source_id=row["source_id"],
        source_vintage="2025",
        publisher="CDC",
        definition_version=1,
        approved=True,
    )
    version, run, evidence, artifact, record_id = (
        row["source_version_id"],
        row["ingestion_run_id"],
        facts["evidence_run_id"],
        row["artifact_id"],
        row["conformed_record_id"],
    )
    edge = dict(
        scope,
        source_id=row["source_id"],
        source_vintage="2025",
        publisher="CDC",
        ingestion_run_id=run,
        artifact_id=artifact,
        artifact_sha256=row["artifact_sha256"],
        record_id=record_id,
        canonical_record_id=record_id,
        record_revision=None,
        source_record_id=row["governed_source_record_id"],
        source_row_hash=row["governed_source_row_hash"],
        record_kind="CANONICAL",
    )
    retained = dict(
        edge,
        evidence_run_id=evidence,
        workbook_sha256=facts["workbook_sha256"],
        source_definition_version=1,
        county_fips=row["county_fips"],
        coverage_state=facts["coverage_state"],
    )
    retained[measure] = facts["publisher_value"]
    # Exact legacy cumulative vintage is translated to the existing 2025 mapping above.
    # These ledgers pin an approved resource/version, not a separate capture DSV.
    # Bind both completed resource runs to that release's existing approved DSV;
    # never invent a capture version or collapse evidence and derivation run IDs.
    authority: dict[str, Any] = {
        "source_versions": {version: source},
        "runs": {
            r: {"source_version_id": version, "dataset_id": scope["dataset_id"]}
            for r in (run, evidence)
        },
        "artifacts": {
            artifact: {
                "sha256": row["artifact_sha256"],
                "ingestion_run_id": evidence,
                "source_version_id": version,
            }
        },
        "records": {record_id: retained},
        "releases": {},
    }
    record = {
        "mapping_id": "county_tick_status"
        if measure == "scapularis_status"
        else "county_pathogen_status",
        "indicator_id": metadata["measure"]["indicator_id"],
        "unit": "status",
        "denominator": "NONE",
        "value": facts["value"],
        "value_state": facts["value_state"],
        "geography": {"grain": "COUNTY", "county_fips": row["county_fips"]},
        "temporal": {"semantics": "CUMULATIVE_THROUGH_DATE", "date": PERIOD},
        "strata": {},
        "edges": [edge],
        "retrieved_at": facts["retrieved_at"],
        "transformation": {
            "id": "cdc-county-status",
            "version": "tick-surveillance-v1",
            "methodology_version": "tick-surveillance-v1",
        },
        "source_output": {
            measure: facts["publisher_value"],
            "value_state": facts["value_state"],
            "county_fips": row["county_fips"],
        },
    }
    binding = packet["observation_bindings"][row["observation_id"]]
    if not isinstance(binding, dict) or binding.get("record_id") != record_id:
        raise CDCConsumerUnavailable("reviewed observation/record membership mismatch")
    if release_id == TARGET_RELEASE_ID and (
        facts.get("donor_record_equivalent") is not True
        or not facts.get("donor_observation_id")
        or binding.get("donor_observation_id") != facts.get("donor_observation_id")
    ):
        raise CDCConsumerUnavailable("reviewed unchanged donor record required")
    authority["releases"][release_id] = {
        "bundle_sha256": bundle,
        "metadata_revision_ids": [metadata["revision_id"]],
        "semantic_revision_ids": [binding.get("semantic_revision_id")],
        "observation_ids": [row["observation_id"]],
        "observation_records": {row["observation_id"]: record_id},
        "restricted_source_publication_attestations": facts.get("attestations") or [],
        "restricted_copy_reuse": packet.get("restricted_copy_reuse", {}),
        "donor_record_equivalent": facts.get("donor_record_equivalent") is True,
    }
    record["release"] = {
        "release_id": release_id,
        "bundle_sha256": bundle,
        "observation_id": row["observation_id"],
    }
    return record, authority


def _project(
    query: Query,
    root: Traversable,
    measure: str,
    county: str,
    environment: str,
    *,
    release_id: str = RELEASE_ID,
) -> dict[str, Any]:
    if (
        measure not in SLICES
        or not re.fullmatch(r"[0-9]{5}", county)
        or environment not in {"dev", "prod"}
    ):
        raise CDCConsumerUnavailable("unsupported CDC consumer slice")
    identity = query(IDENTITY_SQL, ())
    suffix = environment.upper()
    if len(identity) != 1 or (
        not identity[0].get("USER")
        or not identity[0].get("WAREHOUSE")
        or identity[0].get("ROLE") != f"OH_LYME_{suffix}_READ"
        or identity[0].get("DATABASE") != f"ONE_HEALTH_LYME_GAP_ATLAS_{suffix}"
    ):
        raise CDCConsumerUnavailable("CDC intended reader identity required")
    metadata = _metadata(root, measure, release_id)
    rows = query(AUTHORITY_SQL, (release_id, measure, county, SLICES[measure]["source_version_id"]))
    if len(rows) != 1:
        raise CDCConsumerUnavailable("exactly one authoritative CDC observation required")
    row = {str(k).lower(): v for k, v in rows[0].items()}
    record, authority = _inputs(row, metadata)
    mapping_resource = root.joinpath("atlas-semantic-source-mappings-v1.json")
    if not mapping_resource.is_file() and isinstance(root, Path):
        mapping_resource = root.parent / "atlas-semantic-source-mappings-v1.json"
    with as_file(mapping_resource) as path:
        mappings = load_mapping_registry(path)
    # map_record checks semantic revision membership against the retained packet.
    map_record(record, metadata, authority, mappings)
    return project_surveillance_evidence(record, metadata, authority, mappings)


def read_cdc_consumer(
    measure: str, county: str, *, environment: str = "prod", release_id: str = RELEASE_ID
) -> dict[str, Any]:
    """Service entry point, existing PAT/key-pair settings; exact reader role required."""
    try:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30")
            cursor.execute("USE SECONDARY ROLES NONE")

            def query(sql: str, params: tuple[str, ...]) -> list[dict[str, Any]]:
                cursor.execute(sql, params)
                columns = [str(col[0]) for col in cursor.description or []]
                return [dict(zip(columns, row, strict=True)) for row in cursor.fetchmany(2)]

            return _project(
                query, _resources(), measure, county, environment, release_id=release_id
            )
    except CDCConsumerUnavailable:
        raise
    except Exception:
        raise CDCConsumerUnavailable("CDC consumer authority unavailable; no fallback") from None


def read_cdc_consumer_named(
    measure: str, county: str, *, environment: str = "prod", release_id: str = RELEASE_ID
) -> dict[str, Any]:
    """Operator acceptance via installed snow CLI and repository-approved named PAT."""
    if environment not in {"dev", "prod"}:
        raise CDCConsumerUnavailable("unsupported CDC consumer environment")

    def query(sql: str, params: tuple[str, ...]) -> list[dict[str, Any]]:
        # CLI has no connector binds; quote validated fixed-slice literals only.
        for value in params:
            if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", value):
                raise CDCConsumerUnavailable("invalid bounded CDC query parameter")
            sql = sql.replace("%s", "'" + value + "'", 1)
        result = subprocess.run(
            [
                "snow",
                "sql",
                "--silent",
                "--connection",
                f"ATLAS_{environment.upper()}_READ",
                "--warehouse",
                "COMPUTE_WH",
                "--secondary-roles",
                "NONE",
                "--format",
                "json",
                "--query",
                "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30; " + sql,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        rows = json.loads(result.stdout)
        if rows and isinstance(rows[-1], list):
            rows = rows[-1]
        return list(rows)

    try:
        return _project(query, _resources(), measure, county, environment, release_id=release_id)
    except CDCConsumerUnavailable:
        raise
    except Exception:
        raise CDCConsumerUnavailable("CDC consumer authority unavailable; no fallback") from None
