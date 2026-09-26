"""Bind existing governed records to the #190/#191/#193 semantic contracts.

The caller supplies retained canonical/derived records and an authority snapshot.
This module performs no ingestion, database access, or publication.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from lyme_gap_atlas_data.semantic_domain import (
    CONTRACT_VERSION as DOMAIN_VERSION,
)
from lyme_gap_atlas_data.semantic_domain import (
    observation_key,
    revision_id,
    validate_domain,
)
from lyme_gap_atlas_data.semantic_lineage import (
    CONTRACT_VERSION as LINEAGE_VERSION,
)
from lyme_gap_atlas_data.semantic_lineage import (
    lineage_id,
    validate_lineage,
)
from lyme_gap_atlas_data.semantic_metadata import validate_metadata
from lyme_gap_atlas_data.tick_normalization import normalize_value

CONTRACT_VERSION = "atlas-semantic-source-mappings-v1"
_SOURCE_FIELDS = (
    "source_id",
    "dataset_id",
    "source_version_id",
    "source_vintage",
    "ingestion_run_id",
    "artifact_id",
    "source_record_id",
    "source_row_hash",
)
_NCLIMGRID_MEASURES = {
    "nclimgrid_prcp": ("PRCP", "prcp"),
    "nclimgrid_tmin": ("TMIN", "tmin"),
    "nclimgrid_tmax": ("TMAX", "tmax"),
    "nclimgrid_tavg": ("TAVG", "tavg"),
}
_NLCD_MEASURES = {
    "nlcd_forest": ("FOREST_AREA_SHARE", "LndCov"),
    "nlcd_developed": ("DEVELOPED_AREA_SHARE", "LndCov"),
    "nlcd_agriculture": ("AGRICULTURE_AREA_SHARE", "LndCov"),
    "nlcd_wetland": ("WETLAND_AREA_SHARE", "LndCov"),
    "nlcd_open_water": ("OPEN_WATER_AREA_SHARE", "LndCov"),
    "nlcd_impervious": ("MEAN_IMPERVIOUS_FRACTION", "FctImp"),
    "nlcd_change": ("LAND_COVER_CHANGED_AREA_SHARE", "LndChg"),
}


def _valid_nclimgrid_areas(output: Mapping[str, Any]) -> bool:
    """Keep source footprint and daily missingness distinct at the mapping gate."""
    fields = (
        "expected_area_m2",
        "intersected_area_m2",
        "source_supported_area_m2",
        "valid_area_m2",
        "source_coverage_fraction",
        "valid_fraction_of_supported_area",
    )
    if output.get("coverage_status") == "OUT_OF_SOURCE_COVERAGE":
        return output.get("valid_area_m2") == 0 and all(
            output.get(field) is None for field in fields if field != "valid_area_m2"
        )
    expected, intersected, supported, valid, source_fraction, daily_fraction = (
        output.get(field) for field in fields
    )
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in (expected, intersected, supported, valid, source_fraction)
    ):
        return False
    expected = cast(float, expected)
    intersected = cast(float, intersected)
    supported = cast(float, supported)
    valid = cast(float, valid)
    source_fraction = cast(float, source_fraction)
    if not (expected > 0 and 0 <= valid <= supported <= intersected <= expected * (1 + 1e-8)):
        return False
    if not math.isclose(source_fraction, supported / expected, abs_tol=1e-8):
        return False
    if supported == 0:
        return daily_fraction is None and output.get("coverage_status") == "SOURCE_MISSING"
    if not isinstance(daily_fraction, (int, float)) or isinstance(daily_fraction, bool):
        return False
    if not math.isfinite(daily_fraction) or not math.isclose(
        daily_fraction, valid / supported, abs_tol=1e-8
    ):
        return False
    status = output.get("coverage_status")
    return (
        (status == "SOURCE_MISSING" and valid == 0)
        or (status == "PARTIAL_COVERAGE" and 0 < daily_fraction < 0.95 - 1e-12)
        or (status == "COMPLETE" and daily_fraction + 1e-12 >= 0.95)
    )


class SemanticMappingError(ValueError):
    """A supplied record is incompatible with its exact governed mapping."""


def load_mapping_registry(path: Path) -> dict[str, Mapping[str, Any]]:
    """Load a versioned mapping document; malformed or duplicate rules fail."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("contract_version") != CONTRACT_VERSION:
        raise SemanticMappingError("unsupported mapping contract version")
    mappings = document.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise SemanticMappingError("mapping registry is empty")
    result: dict[str, Mapping[str, Any]] = {}
    for mapping in mappings:
        if not isinstance(mapping, Mapping) or not isinstance(mapping.get("id"), str):
            raise SemanticMappingError("invalid mapping entry")
        for field in ("resource_key", "vintage", "measure_id", "field"):
            _required(mapping, field)
        if (
            not isinstance(mapping.get("definition_version"), int)
            or mapping["definition_version"] < 1
        ):
            raise SemanticMappingError("invalid source definition version")
        if mapping.get("origin") not in {"REPORTED", "DERIVED"} or mapping.get("grain") not in {
            "COUNTY",
            "SITE_EVENT",
            "SOURCE_ONLY_COUNTY",
        }:
            raise SemanticMappingError("invalid mapping origin or grain")
        if mapping.get("time") not in {"PERIOD", "POINT_IN_TIME", "CUMULATIVE_THROUGH_DATE"}:
            raise SemanticMappingError("invalid mapping time")
        if mapping.get("status") not in {"EXISTING_REUSED", "NEW_SEMANTIC_MAPPING"}:
            raise SemanticMappingError("invalid executable mapping status")
        identity = mapping["id"]
        if identity in result:
            raise SemanticMappingError("duplicate mapping identity")
        result[identity] = mapping
    return result


def _required(mapping: Mapping[str, Any], field: str) -> Any:
    value = mapping.get(field)
    if value is None or value == "":
        raise SemanticMappingError(f"missing required {field}")
    return value


def _bind_source(
    edge: Mapping[str, Any], mapping: Mapping[str, Any], authority: Mapping[str, Any]
) -> None:
    versions = authority.get("source_versions")
    version_id = _required(edge, "source_version_id")
    source = versions.get(version_id) if isinstance(versions, Mapping) else None
    if not isinstance(source, Mapping):
        raise SemanticMappingError("unknown governed source version")
    for field in ("resource_key", "source_id", "dataset_id"):
        if edge.get(field) != source.get(field):
            raise SemanticMappingError(f"incompatible {field} for mapping")
        if field in mapping and source.get(field) != mapping[field]:
            raise SemanticMappingError(f"incompatible {field} for mapping")
    if edge.get("source_vintage") != mapping.get("vintage") or source.get(
        "source_vintage"
    ) != mapping.get("vintage"):
        raise SemanticMappingError("wrong source vintage")
    if source.get("definition_version") != mapping.get("definition_version"):
        raise SemanticMappingError("wrong source definition version")
    if source.get("approved") is not True:
        raise SemanticMappingError("source version is not approved")
    if "product" in mapping and source.get("product") != mapping["product"]:
        raise SemanticMappingError("wrong source product")


def _validate_strata(
    record: Mapping[str, Any], mapping: Mapping[str, Any], edges: list[Mapping[str, Any]]
) -> None:
    strata = record.get("strata", {})
    if not isinstance(strata, Mapping):
        raise SemanticMappingError("invalid strata")
    if not set(mapping.get("required_strata", [])) <= set(strata):
        raise SemanticMappingError("missing required canonical strata")
    if mapping.get("required_proof") and not all(
        edge.get(mapping["required_proof"]) for edge in edges
    ):
        raise SemanticMappingError("missing exact-source normalization or eligibility proof")
    evidence = record.get("strata_evidence", {})
    if not isinstance(evidence, Mapping) or set(evidence) != set(strata):
        raise SemanticMappingError("strata need exact-source evidence")
    for field, canonical_id in strata.items():
        proof = evidence[field]
        if not isinstance(proof, Mapping):
            raise SemanticMappingError("invalid stratum proof")
        context = proof.get("source_context")
        if not isinstance(context, Mapping) or context.get("source_version") != mapping["vintage"]:
            raise SemanticMappingError("wrong stratum source version")
        product = context.get("dataset_id")
        if mapping["resource_key"] == "neon_tick_release_2026":
            if context.get("publisher") != "NSF NEON" or product not in {
                "DP1.10093.001",
                "DP1.10092.001",
            }:
                raise SemanticMappingError("wrong stratum source product")
        elif product not in {edge["dataset_id"] for edge in edges}:
            raise SemanticMappingError("wrong stratum source product")
        source_value = proof.get("source_value")
        if not isinstance(source_value, (str, int, float, bool)):
            raise SemanticMappingError("missing source-native stratum value")
        result = normalize_value(
            field=field,
            source_value=source_value,
            publisher=str(context.get("publisher")),
            dataset_id=str(product),
            source_version=mapping["vintage"],
        )
        if (
            result.status != "APPROVED"
            or result.canonical_id != canonical_id
            or result.mapping_rule_id != proof.get("mapping_rule_id")
            or result.registry_id != proof.get("registry_id")
            or result.registry_version != proof.get("registry_version")
        ):
            raise SemanticMappingError("unapproved or display-label canonical stratum")


def _source_value(record: Mapping[str, Any], mapping: Mapping[str, Any]) -> tuple[Any, str]:
    """Read value/state from the owning canonical or derived output."""
    output = record.get("source_output")
    if not isinstance(output, Mapping) or mapping["field"] not in output:
        raise SemanticMappingError("existing source output and mapped field required")
    raw = output[mapping["field"]]
    mapping_id = mapping["id"]
    value: Any
    state: str
    if mapping_id in _NLCD_MEASURES:
        coverage = output.get("coverage_status")
        if coverage == "COMPLETE" and isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if not math.isfinite(raw) or not 0 <= raw <= 1:
                raise SemanticMappingError("Annual NLCD fraction outside zero to one")
            value, state = raw, "ZERO" if raw == 0 else "OBSERVED"
        elif (
            coverage in {"PARTIAL_COVERAGE", "SOURCE_MISSING", "UNVERIFIED_FIRST_YEAR_CHANGE"}
            and raw is None
        ):
            value, state = None, "MISSING"
        elif coverage == "OUT_OF_SOURCE_COVERAGE" and raw is None:
            value, state = None, "UNAVAILABLE"
        else:
            raise SemanticMappingError("invalid Annual NLCD coverage/value state")
    elif mapping_id in _NCLIMGRID_MEASURES:
        coverage = output.get("coverage_status")
        if coverage == "COMPLETE" and isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value, state = raw, "ZERO" if raw == 0 else "OBSERVED"
        elif coverage in {"PARTIAL_COVERAGE", "SOURCE_MISSING"} and raw is None:
            value, state = None, "MISSING"
        elif coverage == "OUT_OF_SOURCE_COVERAGE" and raw is None:
            value, state = None, "UNAVAILABLE"
        else:
            raise SemanticMappingError("invalid nClimGrid coverage/value state")
    elif mapping_id == "source_only":
        if raw not in {"UNMAPPED", "AMBIGUOUS"}:
            raise SemanticMappingError("source-only output must remain unresolved")
        value, state = None, "UNKNOWN"
    elif mapping_id == "infected_tick_result":
        if output.get("contract_version") != "infected-tick-derived-result-v1":
            raise SemanticMappingError("wrong infected-tick result contract")
        if output.get("state") == "UNAVAILABLE" and raw is None:
            value, state = None, "UNAVAILABLE"
        elif (
            output.get("state") == "NUMERIC"
            and isinstance(raw, (int, float))
            and not isinstance(raw, bool)
        ):
            value, state = raw, "ZERO" if raw == 0 else "OBSERVED"
        else:
            raise SemanticMappingError("invalid infected-tick result value state")
    elif mapping_id in {"coverage_result", "priority_result"}:
        contract = (
            "surveillance-coverage-result-v2"
            if mapping_id == "coverage_result"
            else "surveillance-priority-result-v2"
        )
        if output.get("contract_version") != contract or not isinstance(raw, str):
            raise SemanticMappingError("wrong derived result contract or state")
        state = raw if raw in {"UNKNOWN", "UNAVAILABLE", "NOT_DEFENSIBLE"} else "OBSERVED"
        value = None if state != "OBSERVED" else raw
    else:
        if raw is None:
            source_state = output.get("value_state")
            if source_state not in {
                "MISSING",
                "UNKNOWN",
                "SUPPRESSED",
                "NOT_REPORTED",
                "UNAVAILABLE",
            }:
                raise SemanticMappingError("null source value requires explicit value state")
            state = str(source_state)
            value = None
        elif raw == "No records":
            value, state = raw, "NO_RECORDS"
        elif isinstance(raw, str) and raw in {
            "no_county_linked_record",
            "NO_COUNTY_LINKED_RECORD",
        }:
            value, state = "NO_COUNTY_LINKED_RECORD", "NO_COUNTY_LINKED_RECORD"
        elif isinstance(raw, str) and raw in {"Unknown", "Suppressed", "Not reported"}:
            value, state = None, raw.upper().replace(" ", "_")
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw == 0:
            value, state = raw, "ZERO"
        else:
            value, state = raw, "OBSERVED"
    if record.get("value") != value or record.get("value_state") != state:
        raise SemanticMappingError("source output/value-state disagreement")
    return value, state


def _check_output_scope(
    record: Mapping[str, Any], mapping: Mapping[str, Any], edges: list[Mapping[str, Any]]
) -> None:
    output = record["source_output"]
    geography = record["geography"]
    temporal = record["temporal"]
    if mapping["id"] in _NLCD_MEASURES:
        measure, product = _NLCD_MEASURES[mapping["id"]]
        year = output.get("mapping_year")
        hashes = output.get("artifact_sha256_by_member")
        artifact_ids = output.get("artifact_id_by_member")
        members = set(hashes) if isinstance(hashes, Mapping) else set()
        tile_ids = {
            name.split("-")[1]
            for name in members
            if isinstance(name, str)
            and re.fullmatch(r"nlcd-h\d{2}v\d{2}-(lndcov|fctimp|lndchg)-(tif|xml)", name)
        }
        expected_members = {
            f"nlcd-{tile}-{native}-{suffix}"
            for tile in tile_ids
            for native in ("lndcov", "fctimp", "lndchg")
            for suffix in ("tif", "xml")
        } | {"tiger-2025-analysis-county-zip"}
        edge_members = {edge.get("member_name") for edge in edges}
        if (
            not isinstance(year, int)
            or not 1985 <= year <= 2025
            or output.get("id")
            != f"{mapping['resource_key']}:{geography.get('county_fips')}:{year}:{measure}"
            or output.get("measure") != measure
            or output.get("source_product") != product
            or output.get("county_fips") != geography.get("county_fips")
            or temporal.get("start") != f"{year}-01-01"
            or temporal.get("end") != f"{year}-12-31"
            or output.get("unit") != record.get("unit")
            or output.get("denominator") != record.get("denominator")
            or output.get("collection_version") != "C1V2"
            or (output.get("coverage_status") == "OUT_OF_SOURCE_COVERAGE")
            != str(output.get("county_fips", "")).startswith(("02", "15"))
            or (
                year == 1985 and product == "LndChg" and output.get("coverage_status") == "COMPLETE"
            )
            or not all(
                output.get(field)
                for field in (
                    "geometry_digest",
                    "tiger_sha256",
                    "weight_version",
                    "transformation_version",
                )
            )
            or not isinstance(hashes, Mapping)
            or not isinstance(artifact_ids, Mapping)
            or not tile_ids
            or members != expected_members
            or set(artifact_ids) != members
            or edge_members != members
            or len(edges) != len(members)
            or len({edge.get("ingestion_run_id") for edge in edges}) != 1
            or any(
                edge.get("artifact_sha256") != hashes[edge["member_name"]]
                or edge.get("artifact_id") != artifact_ids[edge["member_name"]]
                for edge in edges
            )
            or hashes["tiger-2025-analysis-county-zip"] != output.get("tiger_sha256")
        ):
            raise SemanticMappingError("Annual NLCD scope or named-member lineage mismatch")
        supported = output.get("source_supported_area_m2")
        valid = output.get("valid_area_m2")
        fraction = output.get("valid_fraction_of_supported_area")
        status = output.get("coverage_status")
        if status == "COMPLETE" and not (
            isinstance(supported, (int, float))
            and supported > 0
            and isinstance(valid, (int, float))
            and math.isclose(valid, supported, rel_tol=1e-8)
            and isinstance(fraction, (int, float))
            and math.isclose(fraction, 1, abs_tol=1e-8)
        ):
            raise SemanticMappingError("Annual NLCD complete state lacks full valid source support")
        if status == "UNVERIFIED_FIRST_YEAR_CHANGE" and (year != 1985 or product != "LndChg"):
            raise SemanticMappingError("first-year change state used on wrong product or year")
    elif mapping["id"] in _NCLIMGRID_MEASURES:
        if len(edges) != 2:
            raise SemanticMappingError("nClimGrid requires NOAA and TIGER lineage edges")
        measure, source_variable = _NCLIMGRID_MEASURES[mapping["id"]]
        expected_id = (
            f"{mapping['resource_key']}:{geography.get('county_fips')}:"
            f"{output.get('observation_date')}:{measure}"
        )
        if (
            output.get("id") != expected_id
            or output.get("measure") != measure
            or output.get("source_variable") != source_variable
            or output.get("county_fips") != geography.get("county_fips")
            or temporal.get("start") != output.get("observation_date")
            or temporal.get("end") != output.get("observation_date")
            or output.get("unit") != record.get("unit")
            or (output.get("coverage_status") == "OUT_OF_SOURCE_COVERAGE")
            != str(output.get("county_fips", "")).startswith(("02", "15"))
            or not _valid_nclimgrid_areas(output)
            or not all(
                output.get(field)
                for field in (
                    "grid_id",
                    "geometry_digest",
                    "noaa_sha256",
                    "tiger_sha256",
                    "weight_version",
                )
            )
            or output.get("noaa_sha256") != edges[0].get("artifact_sha256")
            or output.get("tiger_sha256") != edges[1].get("artifact_sha256")
            or edges[0].get("ingestion_run_id") != edges[1].get("ingestion_run_id")
        ):
            raise SemanticMappingError("nClimGrid source output or two-member lineage mismatch")
    elif mapping["id"] in {"neon_collection", "neon_pathogen_test"}:
        expected_type = (
            "COLLECTION_ABUNDANCE" if mapping["id"] == "neon_collection" else "PATHOGEN_TESTING"
        )
        if (
            output.get("observation_type") != expected_type
            or output.get("native_sampling_grain") != "SITE_EVENT"
            or output.get("source_dataset_id") != edges[0]["dataset_id"]
            or output.get("data_source_version_id") != edges[0]["source_vintage"]
            or output.get("source_record_id") != edges[0]["source_record_id"]
            or output.get("canonical_observation_id") != edges[0]["canonical_record_id"]
            or output.get("ingestion_run_id") != edges[0]["ingestion_run_id"]
            or output.get("artifact_id") != edges[0]["artifact_id"]
            or output.get("retrieved_at") != record.get("retrieved_at")
            or output.get("source_agency") != "NSF NEON"
        ):
            raise SemanticMappingError("canonical NEON source identity mismatch")
        normalization = output.get("normalization")
        normalized = normalization.get("mappings") if isinstance(normalization, Mapping) else None
        if not isinstance(normalized, Mapping):
            raise SemanticMappingError("canonical NEON normalization proof required")
        for proof in record["strata_evidence"].values():
            if (
                proof.get("mapping_rule_id") not in normalized
                or normalized[proof["mapping_rule_id"]] != proof
            ):
                raise SemanticMappingError("canonical NEON normalization proof mismatch")
        site = output.get("sampling_site")
        event = output.get("sampling_event")
        county = output.get("county_relationship")
        if (
            not isinstance(site, Mapping)
            or not isinstance(event, Mapping)
            or not isinstance(county, Mapping)
            or geography.get("site_id") != site.get("source_site_id")
            or geography.get("event_id") != event.get("source_event_id")
            or geography.get("county_fips") != county.get("county_fips")
            or geography.get("representativeness") != "NOT_COUNTY_REPRESENTATIVE"
            or temporal.get("date") != output.get("surveillance_period_start")
            or output.get("surveillance_period_start") != output.get("surveillance_period_end")
        ):
            raise SemanticMappingError("canonical NEON geography or time mismatch")
        if mapping["id"] == "neon_pathogen_test" and output.get("ticks_tested") != record.get(
            "denominator_value"
        ):
            raise SemanticMappingError("individual test denominator mismatch")
    elif mapping["origin"] == "DERIVED":
        result = record.get("result")
        evidence_status = output.get("evidence_status")
        infected_basis = (
            evidence_status.get("calculation_basis")
            if isinstance(evidence_status, Mapping)
            else None
        )
        if (
            not isinstance(result, Mapping)
            or output.get("result_id") != result.get("result_id")
            or output.get("result_revision") != result.get("revision_id")
            or output.get("evidence_basis", infected_basis) != record.get("evidence_basis")
        ):
            raise SemanticMappingError("derived output identity or evidence mismatch")
        if mapping["id"] == "priority_result" and output.get("coverage_result_revision") is None:
            raise SemanticMappingError("priority output lacks upstream coverage revision")
        if mapping["id"] in {"infected_tick_result", "coverage_result"} and set(
            output.get("input_canonical_observation_ids", [])
        ) != set(record.get("input_ids", [])):
            raise SemanticMappingError("derived output input IDs mismatch")
        if output.get("native_grain") != geography.get("grain"):
            raise SemanticMappingError("derived output native grain mismatch")
        if output.get("date") != temporal.get("date"):
            raise SemanticMappingError("derived output time mismatch")
        if not isinstance(output.get("quality"), Mapping):
            raise SemanticMappingError("derived output quality required")
        limitations_key = (
            "unavailable_reasons" if mapping["id"] == "infected_tick_result" else "reason_codes"
        )
        if not isinstance(output.get(limitations_key), list):
            raise SemanticMappingError("derived output limitations required")
        if mapping["id"] != "infected_tick_result" and not isinstance(
            output.get("scientific_eligibility"), Mapping
        ):
            raise SemanticMappingError("derived output eligibility required")
    elif mapping["id"] == "source_only":
        if output.get("reported_geography") != geography.get("reported_geography_id"):
            raise SemanticMappingError("source-only geography mismatch")
    elif output.get("county_fips") != geography.get("county_fips"):
        raise SemanticMappingError("county source output/FIPS mismatch")


def map_record(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Create a deterministic semantic assertion and complete trace.

    `record` is a selected existing canonical or derived safe record. Its edges
    must resolve against the supplied governed #193 authority snapshot. No
    value, denominator, county, time, or scientific ID is inferred here.
    """
    mapping_id = _required(record, "mapping_id")
    mapping = mappings.get(mapping_id)
    if mapping is None:
        raise SemanticMappingError("unknown source mapping")
    edges = _required(record, "edges")
    if (
        not isinstance(edges, list)
        or not edges
        or not all(isinstance(edge, Mapping) for edge in edges)
    ):
        raise SemanticMappingError("source lineage edges required")
    if mapping_id in _NLCD_MEASURES:
        if len(edges) < 7:
            raise SemanticMappingError("Annual NLCD requires six tile members and TIGER")
        versions = authority.get("source_versions")
        for edge in edges:
            if edge.get("member_name") == "tiger-2025-analysis-county-zip":
                tiger = (
                    versions.get(edge.get("source_version_id"))
                    if isinstance(versions, Mapping)
                    else None
                )
                if (
                    not isinstance(tiger, Mapping)
                    or tiger.get("approved") is not True
                    or tiger.get("source_vintage") != "2025"
                    or any(
                        edge.get(field) != tiger.get(field)
                        for field in ("resource_key", "source_id", "dataset_id", "source_vintage")
                    )
                ):
                    raise SemanticMappingError("approved 2025 TIGER lineage required")
            else:
                _bind_source(edge, mapping, authority)
    elif mapping_id in _NCLIMGRID_MEASURES:
        if len(edges) != 2:
            raise SemanticMappingError("nClimGrid requires NOAA and TIGER lineage edges")
        _bind_source(edges[0], mapping, authority)
        versions = authority.get("source_versions")
        tiger = (
            versions.get(edges[1].get("source_version_id"))
            if isinstance(versions, Mapping)
            else None
        )
        if (
            not isinstance(tiger, Mapping)
            or tiger.get("approved") is not True
            or any(
                edges[1].get(field) != tiger.get(field)
                for field in ("resource_key", "source_id", "dataset_id", "source_vintage")
            )
            or edges[1].get("source_vintage") != "2025"
        ):
            raise SemanticMappingError("approved 2025 TIGER lineage required")
    else:
        for edge in edges:
            _bind_source(edge, mapping, authority)
    validate_metadata(metadata)
    if metadata["steward_review"]["state"] != "REVIEWED" and not (
        fixture_mode and record.get("fixture") is True
    ):
        raise SemanticMappingError("unreviewed semantic metadata cannot map live records")
    measure = metadata["measure"]
    for actual, expected, name in (
        (measure["measure_id"], mapping["measure_id"], "measure"),
        (measure["origin"], mapping["origin"], "origin"),
        (measure["geography_grain"], mapping["grain"], "geography grain"),
        (measure["temporal_semantics"], mapping["time"], "temporal semantics"),
        (record.get("unit"), measure["unit"], "unit"),
        (record.get("denominator"), measure["denominator"], "denominator"),
    ):
        if actual != expected:
            raise SemanticMappingError(f"incompatible {name}")
    if record.get("indicator_id") != measure["indicator_id"]:
        raise SemanticMappingError("wrong indicator identity")
    _validate_strata(record, mapping, edges)
    value, value_state = _source_value(record, mapping)
    if measure["denominator"] != "NONE" and record.get("value_state") in {"OBSERVED", "ZERO"}:
        denominator_value = record.get("denominator_value")
        if (
            not isinstance(denominator_value, (int, float))
            or isinstance(denominator_value, bool)
            or denominator_value <= 0
        ):
            raise SemanticMappingError("positive governed denominator value required")
    geography = _required(record, "geography")
    temporal = _required(record, "temporal")
    if not isinstance(geography, Mapping) or not isinstance(temporal, Mapping):
        raise SemanticMappingError("geography and time scopes required")
    if geography.get("grain") != mapping["grain"] or temporal.get("semantics") != mapping["time"]:
        raise SemanticMappingError("incompatible native geography or time")
    _check_output_scope(record, mapping, edges)
    first = edges[0]
    if mapping["origin"] == "REPORTED":
        if len(edges) != 1 or record.get("result") is not None:
            raise SemanticMappingError("reported mapping requires one source record")
        provenance = {key: first.get(key) for key in _SOURCE_FIELDS}
        provenance["retrieved_at"] = _required(record, "retrieved_at")
    else:
        inputs = _required(record, "input_ids")
        if not isinstance(inputs, list) or not inputs or len(set(inputs)) != len(inputs):
            raise SemanticMappingError("derived inputs required and unique")
        provenance = {
            "dataset_id": _required(record, "output_dataset_id"),
            "transformation_version": _required(record, "transformation_version"),
            "input_ids": inputs,
            "evidence_basis": _required(record, "evidence_basis"),
            "lineage_sources": [
                {key: edge.get(key) for key in _SOURCE_FIELDS}
                | {"retrieved_at": _required(record, "retrieved_at")}
                for edge in edges
            ],
        }
        if not isinstance(record.get("result"), Mapping):
            raise SemanticMappingError("derived result identity and revision required")
    result_ref = record["result"]["result_id"] if mapping["origin"] == "DERIVED" else None
    observation = {
        "contract_version": DOMAIN_VERSION,
        "measure_id": measure["measure_id"],
        "measure_version": measure["semantic_version"],
        "unit": measure["unit"],
        "denominator": measure["denominator"],
        "origin": mapping["origin"],
        "geography": dict(geography),
        "temporal": dict(temporal),
        "strata": dict(record.get("strata", {})),
        "provenance": provenance,
        "value": value,
        "value_state": value_state,
        "quality_ref": result_ref or record.get("quality_ref"),
        "eligibility_ref": result_ref or record.get("eligibility_ref"),
        "limitations_ref": result_ref or record.get("limitations_ref"),
    }
    observation["observation_key"] = observation_key(observation, measure)
    observation["revision_id"] = revision_id(observation)
    validate_domain([measure], [observation])
    transformation = _required(record, "transformation")
    if not isinstance(transformation, Mapping):
        raise SemanticMappingError("transformation identity required")
    lineage = {
        "contract_version": LINEAGE_VERSION,
        "visibility": "INTERNAL",
        "semantic_observation_id": observation["observation_key"],
        "semantic_revision_id": observation["revision_id"],
        "metadata_revision_id": metadata["revision_id"],
        "metadata": metadata,
        "observation": observation,
        "edges": edges,
        "input_ids": record.get("input_ids", []),
        "transformation": dict(transformation),
        "result": record.get("result"),
        "release": record.get("release"),
    }
    lineage["lineage_id"] = lineage_id(lineage)
    validate_lineage(lineage, authority)
    return {
        "mapping_contract_version": CONTRACT_VERSION,
        "mapping_id": mapping_id,
        "source_id": first["source_id"],
        "dataset_id": provenance["dataset_id"],
        "indicator_id": measure["indicator_id"],
        "measure_id": measure["measure_id"],
        "semantic_version": measure["semantic_version"],
        "metadata_id": metadata["metadata_id"],
        "metadata_revision_id": metadata["revision_id"],
        "lineage_id": lineage["lineage_id"],
        "observation": observation,
        "lineage": lineage,
    }


def map_records(
    records: Sequence[Mapping[str, Any]],
    metadata_by_mapping: Mapping[str, Mapping[str, Any]],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    fixture_mode: bool = False,
) -> list[dict[str, Any]]:
    """Reject duplicate semantic assertions or conflicting immutable revisions."""
    output: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    revisions: set[str] = set()
    for record in records:
        identity = _required(record, "mapping_id")
        metadata = metadata_by_mapping.get(identity)
        if metadata is None:
            raise SemanticMappingError("missing mandatory metadata reference")
        mapped = map_record(record, metadata, authority, mappings, fixture_mode=fixture_mode)
        observation = mapped["observation"]
        key, revision = observation["observation_key"], observation["revision_id"]
        if key in seen or revision in revisions:
            raise SemanticMappingError("duplicate semantic observation or conflicting revision")
        seen[key] = revision
        revisions.add(revision)
        output.append(mapped)
    return output
