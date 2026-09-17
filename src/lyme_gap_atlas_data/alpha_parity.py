"""Produce a reproducible, metadata-only Alpha-to-semantic parity report.

The retained Alpha bundle is read locally and never copied into the report.
The report deliberately contains only counts, field hashes, and bounded FIPS
samples so it can be committed as release evidence without redistributing an
Alpha bundle or a restricted source artifact.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

EXPECTED_COUNTIES = 3_144
_FIELDS = (
    "fips",
    "county",
    "state",
    "state_name",
    "population",
    "in_contiguous_tick_scope",
    "human_status",
    "case_count_floor_2023",
    "incidence_floor_2023",
    "state_unallocated_records_2023",
    "tick_status",
    "scapularis_status",
    "pacificus_status",
    "burgdorferi_status",
    "svi_percentile",
    "uninsured_percentile",
    "uninsured_percent",
    "rucc_2023",
    "evidence_completeness",
    "geometry",
    "default",
)
_KNOWN_MISSINGNESS_FIELDS = {
    "tick_status",
    "scapularis_status",
    "pacificus_status",
    "burgdorferi_status",
    "evidence_completeness",
    "default",
}
_FIPS_SAMPLE_LIMIT = 25


class AlphaParityError(ValueError):
    """Raised when an input cannot prove the full county-level comparison."""


def fetch_current_semantic_rows(connection: str, release_id: str) -> list[dict[str, Any]]:
    """Read the active public semantic view through a named, read-only connection."""
    query = (
        """
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'fips', fips, 'county', county, 'state', state, 'state_name', state_name,
  'population', population, 'in_contiguous_tick_scope', in_contiguous_tick_scope,
  'human_status', human_status, 'case_count_floor_2023', case_count_floor_2023,
  'incidence_floor_2023', incidence_floor_2023,
  'state_unallocated_records_2023', state_unallocated_records_2023,
  'tick_status', tick_status, 'scapularis_status', scapularis_status,
  'pacificus_status', pacificus_status, 'burgdorferi_status', burgdorferi_status,
  'svi_percentile', svi_percentile, 'uninsured_percentile', uninsured_percentile,
  'uninsured_percent', uninsured_percent, 'rucc_2023', rucc_2023,
  'evidence_completeness', evidence_completeness, 'geometry', geometry_json
) AS county_record
FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V
WHERE release_id = '"""
        + _sql_literal(release_id)
        + "' ORDER BY fips"
    )
    result = subprocess.run(
        ["snow", "sql", "-c", connection, "-q", query, "--format", "JSON"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise AlphaParityError("The read-only semantic query failed; no report was generated")
    try:
        payload = json.loads(result.stdout)
        result_set = payload[0] if payload and isinstance(payload[0], list) else payload
        rows = [json.loads(row["COUNTY_RECORD"]) for row in result_set]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise AlphaParityError("The semantic query returned an unexpected JSON shape") from error
    return rows


def fetch_current_source_metadata(connection: str) -> list[dict[str, Any]]:
    """Read the source metadata that is actually exposed by the public view."""
    query = (
        "SELECT source_key, label, vintage, source_url, note "
        "FROM PRESENTATION.CURRENT_SOURCE_METADATA_V ORDER BY source_key"
    )
    result = subprocess.run(
        [
            "snow",
            "sql",
            "-c",
            connection,
            "-q",
            query,
            "--format",
            "JSON",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise AlphaParityError(
            "The read-only source metadata query failed; no report was generated"
        )
    try:
        payload = json.loads(result.stdout)
        result_set = payload[0] if payload and isinstance(payload[0], list) else payload
        return [{key.lower(): value for key, value in row.items()} for row in result_set]
    except (IndexError, TypeError, json.JSONDecodeError) as error:
        raise AlphaParityError(
            "The source metadata query returned an unexpected JSON shape"
        ) from error


def fetch_current_release_metadata(connection: str) -> dict[str, Any]:
    """Read the public release identifier, defaults, method, and limitations."""
    query = (
        "SELECT release_id, schema_version, generated_at, scope, bundle_sha256, "
        "score_defaults, methodology_version, limitations FROM PRESENTATION.CURRENT_RELEASE_V"
    )
    result = subprocess.run(
        ["snow", "sql", "-c", connection, "-q", query, "--format", "JSON"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise AlphaParityError(
            "The read-only release metadata query failed; no report was generated"
        )
    try:
        rows = json.loads(result.stdout)
        row = rows[0] if rows and isinstance(rows[0], dict) else rows[0][0]
        normalized = {key.lower(): value for key, value in row.items()}
        score_defaults = normalized.get("score_defaults")
        if isinstance(score_defaults, str):
            normalized["score_defaults"] = json.loads(score_defaults)
        return normalized
    except (IndexError, TypeError, json.JSONDecodeError) as error:
        raise AlphaParityError(
            "The release metadata query returned an unexpected JSON shape"
        ) from error


def build_report(
    alpha_bundle: Path,
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    release_id: str,
    bundle_sha256: str,
    methodology_version: str,
    source_metadata: Sequence[Mapping[str, Any]],
    release_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare every retained Alpha county to the governed candidate rows."""
    alpha = json.loads(alpha_bundle.read_text(encoding="utf-8"))
    alpha_rows = _alpha_rows(alpha)
    candidate = _candidate_rows(candidate_rows)
    alpha_by_fips = _index(alpha_rows, "Alpha")
    candidate_by_fips = _index(candidate, "semantic")
    _require_coverage(alpha_by_fips, candidate_by_fips)
    if release_metadata.get("release_id") != release_id:
        raise AlphaParityError("Release metadata does not match the requested semantic release")
    if release_metadata.get("bundle_sha256") != bundle_sha256:
        raise AlphaParityError("Release metadata bundle digest does not match the requested digest")

    comparisons = [_field_comparison(field, alpha_by_fips, candidate_by_fips) for field in _FIELDS]
    unclassified = [
        item for item in comparisons if item["difference_count"] and not item["category"]
    ]
    source_differences = _source_differences(alpha.get("sources"), source_metadata)
    release_comparison = _release_comparison(alpha, release_metadata)
    return {
        "report_schema": "atlas-alpha-parity-report/v1",
        "alpha_release_id": "alpha-2026-08-06",
        "alpha_bundle_sha256": _sha256(alpha_bundle),
        "semantic_release_id": release_id,
        "semantic_bundle_sha256": bundle_sha256,
        "semantic_methodology_version": methodology_version,
        "coverage": {
            "alpha_count": len(alpha_by_fips),
            "semantic_count": len(candidate_by_fips),
            "shared_count": len(set(alpha_by_fips) & set(candidate_by_fips)),
            "missing_from_semantic": sorted(set(alpha_by_fips) - set(candidate_by_fips)),
            "unexpected_in_semantic": sorted(set(candidate_by_fips) - set(alpha_by_fips)),
        },
        "field_comparisons": comparisons,
        "source_metadata_comparison": source_differences,
        "release_metadata_comparison": release_comparison,
        "unclassified_differences": unclassified,
        "signoff": {
            "data_steward": "PENDING",
            "product_owner": "PENDING",
            "engineering": "PENDING",
        },
        "classification_complete": not unclassified and not source_differences["unclassified"],
        # A classified report is necessary but never substitutes for the three
        # human approvals required by the Alpha parity contract.
        "cutover_eligible": False,
        "interpretation": [
            "Published county-linked values are floors, not true incidence.",
            "No records is not absence.",
            "Ecological status is not individual infection risk or diagnosis.",
            "The score is a surveillance follow-up priority, not a prediction or causal claim.",
        ],
    }


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    """Write canonical JSON so the report digest is reproducible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _alpha_rows(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        features = bundle["feature_collection"]["features"]
    except (KeyError, TypeError) as error:
        raise AlphaParityError("Alpha bundle is missing its feature collection") from error
    return [dict(feature["properties"], geometry=feature["geometry"]) for feature in features]


def _candidate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        geometry = row.get("geometry")
        if isinstance(geometry, str):
            row["geometry"] = json.loads(geometry)
        row["default"] = _score(row)
        result.append(row)
    return result


def _index(rows: Iterable[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        fips = str(row.get("fips", ""))
        if fips in indexed or len(fips) != 5 or not fips.isdigit():
            raise AlphaParityError(f"{label} rows do not have unique five-digit FIPS")
        indexed[fips] = row
    return indexed


def _require_coverage(alpha: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    if len(alpha) != EXPECTED_COUNTIES or len(candidate) != EXPECTED_COUNTIES:
        raise AlphaParityError("Parity requires exactly 3,144 Alpha and semantic county rows")
    if set(alpha) != set(candidate):
        raise AlphaParityError("Parity cannot classify a non-identical county FIPS universe")


def _field_comparison(
    field: str, alpha: Mapping[str, Mapping[str, Any]], candidate: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    changed = [
        fips
        for fips in alpha
        if _canonical(alpha[fips].get(field)) != _canonical(candidate[fips].get(field))
    ]
    category = "MISSINGNESS_VALUE_STATE" if changed and field in _KNOWN_MISSINGNESS_FIELDS else None
    if changed and field == "geometry":
        category = "GEOMETRY"
    return {
        "field": field,
        "alpha_value_hash": _field_hash(alpha, field),
        "semantic_value_hash": _field_hash(candidate, field),
        "difference_count": len(changed),
        "affected_fips_sample": changed[:_FIPS_SAMPLE_LIMIT],
        "affected_fips_hash": _hash_values(changed),
        "category": category,
        "approval": "PENDING" if changed else "NOT_REQUIRED",
    }


def _source_differences(
    alpha_sources: Any, semantic_sources: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if not isinstance(alpha_sources, list):
        raise AlphaParityError("Alpha bundle source metadata is missing")
    alpha = {str(source.get("key")): source for source in alpha_sources}
    semantic = {str(source.get("source_key")): source for source in semantic_sources}
    expected = {"human", "tick", "pathogen", "context_svi", "context_rucc"}
    missing = sorted(expected - set(semantic))
    # SVI and RUCC are renamed source keys in governed lineage.  The rest retain their key.
    normalized_semantic = {
        "human": semantic.get("human"),
        "tick": semantic.get("tick"),
        "pathogen": semantic.get("pathogen"),
        "svi": semantic.get("context_svi"),
        "rurality": semantic.get("context_rucc"),
    }
    differences = [
        {"source_key": key, "category": "SOURCE_REVISION", "approval": "PENDING"}
        for key in sorted(alpha)
        if alpha[key] != normalized_semantic.get(key)
    ]
    return {
        "missing_semantic_source_keys": missing,
        "differences": differences,
        "unclassified": missing,
    }


def _release_comparison(
    alpha: Mapping[str, Any], semantic: Mapping[str, Any]
) -> list[dict[str, Any]]:
    comparisons = (
        ("release_id", "alpha-2026-08-06", semantic.get("release_id"), "METHODOLOGY"),
        (
            "schema_version",
            alpha.get("schema_version"),
            semantic.get("schema_version"),
            "METHODOLOGY",
        ),
        ("methodology_version", "alpha-0.2.0", semantic.get("methodology_version"), "METHODOLOGY"),
        ("scope", alpha.get("scope"), semantic.get("scope"), "GEOGRAPHY_SCOPE"),
        (
            "score_defaults",
            alpha.get("score_defaults"),
            semantic.get("score_defaults"),
            "METHODOLOGY",
        ),
        ("limitations", None, semantic.get("limitations"), "METHODOLOGY"),
    )
    return [
        {
            "field": field,
            "alpha_value_hash": _hash_values([_canonical(alpha_value)]),
            "semantic_value_hash": _hash_values([_canonical(semantic_value)]),
            "different": _canonical(alpha_value) != _canonical(semantic_value),
            "category": category,
            "approval": "PENDING"
            if _canonical(alpha_value) != _canonical(semantic_value)
            else "NOT_REQUIRED",
        }
        for field, alpha_value, semantic_value, category in comparisons
    ]


def _score(row: Mapping[str, Any]) -> dict[str, float]:
    human = 75.0
    if (
        row.get("human_status") == "published_count_floor"
        and row.get("incidence_floor_2023") is not None
    ):
        human = 100 * _clamp(1 - float(row["incidence_floor_2023"]) / 10)
    tick = {"Established": 100.0, "Reported": 55.0, "No records": 0.0, "Unknown": 0.0}[
        str(row["tick_status"])
    ]
    pathogen = 100.0 if row.get("burgdorferi_status") == "Present" else 0.0
    ecological = 0.6 * tick + 0.4 * pathogen
    svi = float(row.get("svi_percentile") or 0) * 100
    access = float(row.get("uninsured_percentile") or 0) * 100
    rural = _clamp((float(row.get("rucc_2023") or 1) - 1) / 8 * 100)
    community = 0.5 * svi + 0.3 * access + 0.2 * rural
    return {
        "score": round(human * (0.65 * ecological + 0.35 * community) / 100, 1),
        "human_weakness": round(human, 1),
        "ecological": round(ecological, 1),
        "community": round(community, 1),
        "tick_signal": tick,
        "pathogen_signal": pathogen,
        "svi_signal": round(svi, 1),
        "access_signal": round(access, 1),
        "rural_signal": round(rural, 1),
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _field_hash(rows: Mapping[str, Mapping[str, Any]], field: str) -> str:
    return _hash_values(
        [f"{fips}:{_canonical(row.get(field))}" for fips, row in sorted(rows.items())]
    )


def _hash_values(values: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")
