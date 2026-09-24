"""Versioned, storage-neutral semantic identity contract for Story #190.

This validator describes existing county, canonical, and derived shapes. It does
not persist observations, map new sources, or authorize publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

CONTRACT_VERSION = "atlas-semantic-domain-v1"
_ID = re.compile(r"^[a-z][a-z0-9_:-]*$")
_FIPS = re.compile(r"^[0-9]{5}$")
_NULL_STATES = {"MISSING", "UNKNOWN", "SUPPRESSED", "NOT_REPORTED", "UNAVAILABLE", "NOT_DEFENSIBLE"}
_LITERAL_STATES = {"NO_RECORDS": "No records", "NO_COUNTY_LINKED_RECORD": "NO_COUNTY_LINKED_RECORD"}
_TIME = {"PERIOD", "CUMULATIVE_THROUGH_DATE", "POINT_IN_TIME"}
_GRAINS = {"COUNTY", "SITE_EVENT", "SOURCE_ONLY_COUNTY"}
_ORIGINS = {"REPORTED", "DERIVED"}
_STRATA = {"tick_taxon", "life_stage", "pathogen_target", "collection_method", "testing_scope"}
_SENTINEL_VALUES = {
    "unknown",
    "suppressed",
    "not reported",
    "no records",
    "no_county_linked_record",
}


class SemanticDomainError(ValueError):
    """An assertion cannot be described by the reviewed domain contract."""


def _required(mapping: Mapping[str, Any], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SemanticDomainError(f"{name} is required")
    return value


def _machine_id(mapping: Mapping[str, Any], name: str) -> str:
    value = _required(mapping, name)
    if not _ID.fullmatch(value):
        raise SemanticDomainError(f"{name} must be a stable machine ID")
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def meaning_signature(measure: Mapping[str, Any]) -> str:
    """Scientific meaning excludes display-only metadata and labels."""
    fields = (
        "indicator_id",
        "definition",
        "data_type",
        "unit",
        "denominator",
        "geography_grain",
        "temporal_semantics",
        "allowed_strata",
        "origin",
        "methodology_version",
        "allowed_value_states",
    )
    return _digest({key: measure.get(key) for key in fields})


def validate_measures(measures: Sequence[Mapping[str, Any]]) -> None:
    """Reject duplicate or silently changed meanings for one semantic version."""
    seen: dict[tuple[str, str], str] = {}
    for measure in measures:
        measure_id = _machine_id(measure, "measure_id")
        _machine_id(measure, "indicator_id")
        version = _required(measure, "semantic_version")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise SemanticDomainError("semantic_version must be major.minor.patch")
        _required(measure, "definition")
        _required(measure, "data_type")
        _required(measure, "unit")
        _required(measure, "methodology_version")
        if measure.get("denominator") is None:
            raise SemanticDomainError("denominator must be explicit, using NONE when absent")
        if measure["geography_grain"] not in _GRAINS:
            raise SemanticDomainError("invalid geography grain")
        if measure["temporal_semantics"] not in _TIME:
            raise SemanticDomainError("invalid temporal semantics")
        if measure["origin"] not in _ORIGINS:
            raise SemanticDomainError("invalid reported/derived origin")
        strata = measure.get("allowed_strata")
        if (
            not isinstance(strata, list)
            or any(not isinstance(item, str) for item in strata)
            or len(strata) != len(set(strata))
            or not set(strata) <= _STRATA
        ):
            raise SemanticDomainError("invalid allowed strata")
        states = measure.get("allowed_value_states")
        if (
            not isinstance(states, list)
            or not states
            or any(not isinstance(item, str) for item in states)
            or len(states) != len(set(states))
        ):
            raise SemanticDomainError("invalid allowed value states")
        if not set(states) <= {"OBSERVED", "ZERO", *_NULL_STATES, *_LITERAL_STATES}:
            raise SemanticDomainError("unknown value state")
        key = (measure_id, version)
        signature = meaning_signature(measure)
        if key in seen:
            reason = (
                "duplicate identity" if seen[key] == signature else "unversioned meaning change"
            )
            raise SemanticDomainError(reason)
        seen[key] = signature


def _scope(observation: Mapping[str, Any], measure: Mapping[str, Any]) -> dict[str, Any]:
    geography = observation.get("geography")
    if not isinstance(geography, dict) or geography.get("grain") != measure["geography_grain"]:
        raise SemanticDomainError("incompatible geography grain")
    grain = geography["grain"]
    if grain == "COUNTY":
        if not isinstance(geography.get("county_fips"), str) or not _FIPS.fullmatch(
            geography["county_fips"]
        ):
            raise SemanticDomainError("canonical county FIPS required")
        if geography.get("representativeness") not in (None, "COUNTY_NATIVE_STATUS"):
            raise SemanticDomainError("county representativeness mismatch")
        geo_id = geography["county_fips"]
    elif grain == "SITE_EVENT":
        if geography.get("county_fips") is not None:
            county_fips = geography["county_fips"]
            if not isinstance(county_fips, str) or not _FIPS.fullmatch(county_fips):
                raise SemanticDomainError("invalid contextual county FIPS")
            relationship = geography.get("county_relationship")
            if relationship not in {"SOURCE_REPORTED_COUNTY", "ATLAS_DERIVED_MATCH"}:
                raise SemanticDomainError("site county is contextual only with mapping proof")
            if relationship == "ATLAS_DERIVED_MATCH":
                _required(geography, "mapping_version")
                _required(geography, "mapping_artifact_id")
        if geography.get("representativeness") != "NOT_COUNTY_REPRESENTATIVE":
            raise SemanticDomainError("site/event must not claim county representativeness")
        geo_id = (_required(geography, "site_id"), _required(geography, "event_id"))
    else:
        if geography.get("county_fips") is not None:
            raise SemanticDomainError("source-only evidence cannot have county FIPS")
        if geography.get("mapping_status") not in {"UNMAPPED", "AMBIGUOUS"}:
            raise SemanticDomainError("source-only mapping status required")
        geo_id = _required(geography, "reported_geography_id")
    temporal = observation.get("temporal")
    if not isinstance(temporal, dict) or temporal.get("semantics") != measure["temporal_semantics"]:
        raise SemanticDomainError("incompatible temporal semantics")
    kind = temporal["semantics"]
    if kind == "PERIOD":
        start, end = _required(temporal, "start"), _required(temporal, "end")
        _valid_date(start)
        _valid_date(end)
        if start > end or temporal.get("date") is not None:
            raise SemanticDomainError("invalid period")
        time_id: Any = (start, end)
    else:
        time_id = _required(temporal, "date")
        _valid_date(time_id)
        if temporal.get("start") is not None or temporal.get("end") is not None:
            raise SemanticDomainError("invalid point/cumulative date")
    strata = observation.get("strata", {})
    if not isinstance(strata, dict) or not set(strata) <= set(measure["allowed_strata"]):
        raise SemanticDomainError("invalid strata")
    if any(not isinstance(value, str) or not value for value in strata.values()):
        raise SemanticDomainError("strata require canonical IDs")
    return {"geography": geo_id, "time": time_id, "strata": strata}


def _valid_date(value: str) -> None:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise SemanticDomainError("invalid temporal date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SemanticDomainError("invalid temporal date") from exc


def validate_observation(observation: Mapping[str, Any], measure: Mapping[str, Any]) -> None:
    """Validate an assertion and its supplied deterministic IDs."""
    if observation.get("contract_version") != CONTRACT_VERSION:
        raise SemanticDomainError("unsupported domain contract version")
    if observation.get("measure_id") != measure.get("measure_id") or observation.get(
        "measure_version"
    ) != measure.get("semantic_version"):
        raise SemanticDomainError("measure identity/version mismatch")
    if observation.get("unit") != measure.get("unit") or observation.get(
        "denominator"
    ) != measure.get("denominator"):
        raise SemanticDomainError("incompatible unit or denominator")
    if observation.get("origin") != measure.get("origin"):
        raise SemanticDomainError("reported/derived mismatch")
    scope = _scope(observation, measure)
    provenance = observation.get("provenance")
    if not isinstance(provenance, dict):
        raise SemanticDomainError("provenance required")
    _required(provenance, "dataset_id")
    if observation["origin"] == "DERIVED":
        _required(provenance, "transformation_version")
        _required(provenance, "evidence_basis")
        inputs = provenance.get("input_ids")
        if (
            not isinstance(inputs, list)
            or not inputs
            or any(not isinstance(item, str) or not item for item in inputs)
            or len(inputs) != len(set(inputs))
        ):
            raise SemanticDomainError("derived inputs required and unique")
        sources = provenance.get("lineage_sources")
        if not isinstance(sources, list) or not sources:
            raise SemanticDomainError("derived lineage sources required")
        for source in sources:
            if not isinstance(source, dict):
                raise SemanticDomainError("invalid derived lineage source")
            for field in (
                "source_id",
                "dataset_id",
                "source_version_id",
                "source_vintage",
                "ingestion_run_id",
                "artifact_id",
                "retrieved_at",
            ):
                _required(source, field)
            if not source.get("source_record_id") and not source.get("source_row_hash"):
                raise SemanticDomainError("derived lineage source record identity required")
    else:
        for field in (
            "source_id",
            "source_version_id",
            "source_vintage",
            "ingestion_run_id",
            "artifact_id",
            "retrieved_at",
        ):
            _required(provenance, field)
        if not provenance.get("source_record_id") and not provenance.get("source_row_hash"):
            raise SemanticDomainError("source record identity required")
        if provenance.get("input_ids") or provenance.get("lineage_sources"):
            raise SemanticDomainError("reported observation cannot claim derived inputs")
    state = observation.get("value_state")
    value = observation.get("value")
    if state not in measure["allowed_value_states"]:
        raise SemanticDomainError("value state not allowed for measure")
    if state in _NULL_STATES and value is not None:
        raise SemanticDomainError("unavailable/unknown value must be null")
    if state == "ZERO" and (
        not isinstance(value, (int, float)) or isinstance(value, bool) or value != 0
    ):
        raise SemanticDomainError("ZERO requires numeric zero")
    if state == "OBSERVED" and (value is None or value == 0):
        raise SemanticDomainError("OBSERVED requires nonzero present value")
    if state == "OBSERVED" and isinstance(value, str) and value.casefold() in _SENTINEL_VALUES:
        raise SemanticDomainError("sentinel value requires explicit value state")
    if state in _LITERAL_STATES and value != _LITERAL_STATES[state]:
        raise SemanticDomainError("publisher no-records state has wrong literal")
    if observation.get("geography", {}).get("grain") == "SOURCE_ONLY_COUNTY" and state != "UNKNOWN":
        raise SemanticDomainError("source-only county evidence must remain UNKNOWN")
    if observation.get("observation_key") != observation_key(observation, measure, scope):
        raise SemanticDomainError("observation identity collision or mismatch")
    if observation.get("revision_id") != revision_id(observation):
        raise SemanticDomainError("revision identity collision or mismatch")


def observation_key(
    observation: Mapping[str, Any],
    measure: Mapping[str, Any],
    scope: Mapping[str, Any] | None = None,
) -> str:
    """Scientific key excludes display labels, revisions, and release membership."""
    native = scope if scope is not None else _scope(observation, measure)
    provenance = observation["provenance"]
    source_identity: dict[str, Any]
    if observation["origin"] == "DERIVED":
        source_identity = {"input_ids": sorted(provenance["input_ids"])}
    else:
        source_identity = {
            "source_id": provenance["source_id"],
            "source_version_id": provenance["source_version_id"],
            "source_vintage": provenance["source_vintage"],
            "source_record_id": provenance.get("source_record_id"),
            "source_row_hash": provenance.get("source_row_hash")
            if not provenance.get("source_record_id")
            else None,
        }
    return "observation:v1:" + _digest(
        {
            "measure_id": measure["measure_id"],
            "measure_version": measure["semantic_version"],
            "dataset_id": provenance["dataset_id"],
            "origin": observation["origin"],
            "scope": native,
            "source_identity": source_identity,
        }
    )


def revision_id(observation: Mapping[str, Any]) -> str:
    """Content revision includes evidence basis, method, inputs and value."""
    fields = (
        "observation_key",
        "value",
        "value_state",
        "provenance",
        "quality_ref",
        "eligibility_ref",
        "limitations_ref",
    )
    content = {key: observation.get(key) for key in fields}
    provenance = content.get("provenance")
    if observation.get("origin") == "DERIVED" and isinstance(provenance, dict):
        provenance = dict(provenance)
        if isinstance(provenance.get("input_ids"), list):
            provenance["input_ids"] = sorted(provenance["input_ids"])
        if isinstance(provenance.get("lineage_sources"), list):
            provenance["lineage_sources"] = sorted(
                provenance["lineage_sources"], key=lambda source: _digest(source)
            )
        content["provenance"] = provenance
    return "revision:v1:" + _digest(content)


def validate_domain(
    measures: Sequence[Mapping[str, Any]], observations: Sequence[Mapping[str, Any]]
) -> None:
    validate_measures(measures)
    registry = {(m["measure_id"], m["semantic_version"]): m for m in measures}
    seen_keys: dict[str, str] = {}
    seen_revisions: set[str] = set()
    for observation in observations:
        key = (observation.get("measure_id"), observation.get("measure_version"))
        if key not in registry:
            raise SemanticDomainError("orphan measure reference")
        validate_observation(observation, registry[key])
        semantic_key = observation["observation_key"]
        revision = observation["revision_id"]
        if revision in seen_revisions:
            raise SemanticDomainError("duplicate revision identity")
        if semantic_key in seen_keys and seen_keys[semantic_key] == revision:
            raise SemanticDomainError("duplicate observation identity")
        seen_keys[semantic_key] = revision
        seen_revisions.add(revision)
