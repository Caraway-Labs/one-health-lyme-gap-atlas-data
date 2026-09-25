"""Reviewed service-consumer projection of an authoritative semantic trace.

This module has no storage access and grants no public API publication rights.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .semantic_lineage import consumer_safe_lineage, validate_lineage
from .semantic_metadata import _safe

CONTRACT_VERSION = "atlas-semantic-consumer-v1"
MAX_PAGE_SIZE = 100
_ID = re.compile(r"^[a-z][a-z0-9_:-]*$")
_STRATA = {"tick_taxon", "life_stage", "pathogen_target", "collection_method", "testing_scope"}


class SemanticConsumerError(ValueError):
    """The trace cannot cross the governed consumer boundary."""


def _fields(
    value: object, required: set[str], optional: set[str] | None = None
) -> Mapping[str, Any]:
    """Reject an unreviewed field at every consumer nesting level."""
    if (
        not isinstance(value, Mapping)
        or not required <= value.keys()
        or set(value) - (required | (optional or set()))
    ):
        raise SemanticConsumerError("invalid consumer shape")
    return value


def _scalar(value: object) -> None:
    if value is not None and not isinstance(value, str | int | float | bool):
        raise SemanticConsumerError("invalid consumer shape")


def _strings(value: object) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SemanticConsumerError("invalid consumer shape")


def _state(value: object) -> None:
    item = _fields(value, {"state", "value"})
    _scalar(item["state"])
    _scalar(item["value"])


def _limitations(value: object) -> None:
    if not isinstance(value, list):
        raise SemanticConsumerError("invalid consumer shape")
    for limit in value:
        item = _fields(limit, {"category", "code", "text"})
        for field in item:
            _scalar(item[field])


def _consumer_shape(payload: Mapping[str, Any]) -> None:
    """Runtime counterpart of the checked-in schema; blocks extra storage fields."""
    top = _fields(
        payload,
        {
            "contract_version",
            "evidence_tier",
            "indicator",
            "measure",
            "observation",
            "provenance",
            "freshness",
            "lineage",
            "release",
        },
    )
    for field in ("contract_version", "evidence_tier"):
        _scalar(top[field])
    indicator = _fields(top["indicator"], {"id"})
    _scalar(indicator["id"])
    measure = _fields(
        top["measure"],
        {
            "id",
            "semantic_version",
            "metadata_id",
            "metadata_revision",
            "metadata_revision_id",
            "meaning_signature",
            "label",
            "definition",
            "description",
            "type",
            "origin",
            "unit",
            "denominator",
            "allowed_value_states",
            "allowed_strata",
            "applicability",
            "quality_evidence",
            "limitations",
        },
    )
    for field in (
        "id",
        "semantic_version",
        "metadata_id",
        "metadata_revision",
        "metadata_revision_id",
        "meaning_signature",
        "label",
        "definition",
        "type",
        "origin",
        "unit",
        "denominator",
    ):
        _scalar(measure[field])
    _state(measure["description"])
    _strings(measure["allowed_value_states"])
    _strings(measure["allowed_strata"])
    applicability = _fields(
        measure["applicability"],
        {"geography_grain", "temporal_semantics", "allowed_strata", "origin", "representativeness"},
    )
    for field in ("geography_grain", "temporal_semantics", "origin", "representativeness"):
        _scalar(applicability[field])
    _strings(applicability["allowed_strata"])
    quality = _fields(
        measure["quality_evidence"],
        {
            "quality_contract",
            "propagation_contract",
            "eligibility_contract",
            "uncertainty",
            "evidence_basis",
        },
    )
    for value in quality.values():
        _state(value)
    _limitations(measure["limitations"])
    observation = _fields(
        top["observation"],
        {
            "id",
            "revision_id",
            "value",
            "value_state",
            "geography",
            "temporal",
            "strata",
            "denominator_value",
        },
    )
    for field in ("id", "revision_id", "value", "value_state", "denominator_value"):
        _scalar(observation[field])
    geography = _fields(
        observation["geography"],
        {"grain"},
        {
            "county_fips",
            "site_id",
            "event_id",
            "representativeness",
            "county_relationship",
            "mapping_version",
            "reported_geography_id",
            "mapping_status",
        },
    )
    for value in geography.values():
        _scalar(value)
    temporal = _fields(observation["temporal"], {"semantics"}, {"start", "end", "date"})
    for value in temporal.values():
        _scalar(value)
    strata = _fields(observation["strata"], set(), _STRATA)
    for value in strata.values():
        _scalar(value)
    provenance = _fields(
        top["provenance"],
        {
            "publisher",
            "source_id",
            "dataset_id",
            "source_version_id",
            "source_vintage",
            "method_version",
            "transformation_version",
        },
    )
    for value in provenance.values():
        _state(value)
    freshness = _fields(
        top["freshness"],
        {
            "observation_period",
            "source_vintage",
            "retrieved_at",
            "published_at",
            "metadata_revised_at",
        },
    )
    for value in freshness.values():
        _state(value)
    lineage = _fields(
        top["lineage"],
        {
            "lineage_id",
            "semantic_observation_id",
            "semantic_revision_id",
            "measure_id",
            "measure_version",
            "metadata_revision_id",
            "publisher",
            "dataset_id",
            "source_version_id",
            "source_vintage",
            "methodology_version",
            "transformation_version",
            "limitations",
            "evidence_basis",
            "representativeness",
            "record_refs",
            "result_id",
            "result_revision_id",
            "release_id",
        },
    )
    for field, value in lineage.items():
        if field == "limitations":
            _limitations(value)
        elif field == "record_refs":
            _strings(value)
        else:
            _scalar(value)
    if top["release"] is not None:
        release = _fields(top["release"], {"id", "bundle_sha256"})
        for value in release.values():
            _scalar(value)


def project_consumer(
    lineage: Mapping[str, Any],
    authority: Mapping[str, Any],
    *,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Validate internal authority and emit only explicitly permitted fields."""
    validate_lineage(lineage, authority)
    metadata = lineage["metadata"]
    observation = lineage["observation"]
    measure = metadata["measure"]
    if metadata["visibility"] not in {"CONSUMER_SAFE", "PUBLIC"}:
        raise SemanticConsumerError("metadata is internal")
    if lineage["visibility"] != "CONSUMER_SAFE":
        raise SemanticConsumerError("lineage is internal")
    if fixture_mode and not metadata["provenance"]["source_version_id"]["value"].startswith(
        "fixture-"
    ):
        raise SemanticConsumerError("fixture mode requires synthetic source identity")
    if metadata["steward_review"]["state"] != "REVIEWED" and not fixture_mode:
        raise SemanticConsumerError("metadata lacks reviewed publication state")
    if measure["origin"] == "DERIVED" and measure["methodology_version"] in {
        "infected-tick-metrics-v1",
        "surveillance-coverage-v1",
        "surveillance-priority-v1",
    }:
        raise SemanticConsumerError("derived product remains internal")
    if fixture_mode and metadata["steward_review"]["state"] == "PENDING":
        evidence_tier = "SYNTHETIC_FIXTURE"
    else:
        evidence_tier = "REVIEWED_CONTRACT"
    safe_lineage = consumer_safe_lineage(lineage)
    release = lineage.get("release")
    geography = observation["geography"]
    temporal = observation["temporal"]
    payload = {
        "contract_version": CONTRACT_VERSION,
        "evidence_tier": evidence_tier,
        "indicator": {"id": measure["indicator_id"]},
        "measure": {
            "id": measure["measure_id"],
            "semantic_version": measure["semantic_version"],
            "metadata_id": metadata["metadata_id"],
            "metadata_revision": metadata["metadata_revision"],
            "metadata_revision_id": metadata["revision_id"],
            "meaning_signature": metadata["meaning_signature"],
            "label": metadata["label"],
            "definition": metadata["definition"],
            "description": metadata["short_description"],
            "type": measure["data_type"],
            "origin": measure["origin"],
            "unit": measure["unit"],
            "denominator": measure["denominator"],
            "allowed_value_states": measure["allowed_value_states"],
            "allowed_strata": measure["allowed_strata"],
            "applicability": metadata["applicability"],
            "quality_evidence": metadata["quality_evidence"],
            "limitations": metadata["limitations"],
        },
        "observation": {
            "id": observation["observation_key"],
            "revision_id": observation["revision_id"],
            "value": observation["value"],
            "value_state": observation["value_state"],
            "geography": {
                field: geography[field]
                for field in (
                    "grain",
                    "county_fips",
                    "site_id",
                    "event_id",
                    "representativeness",
                    "county_relationship",
                    "mapping_version",
                    "reported_geography_id",
                    "mapping_status",
                )
                if field in geography
            },
            "temporal": {
                field: temporal[field]
                for field in ("semantics", "start", "end", "date")
                if field in temporal
            },
            "strata": observation["strata"],
            "denominator_value": observation.get("denominator_value"),
        },
        "provenance": metadata["provenance"],
        "freshness": metadata["freshness"],
        "lineage": safe_lineage,
        "release": (
            {"id": release["release_id"], "bundle_sha256": release["bundle_sha256"]}
            if release is not None
            else None
        ),
    }
    _consumer_shape(payload)
    _safe(payload)
    return payload


def canonical_consumer_json(payload: Mapping[str, Any]) -> str:
    """Stable bytes for revision comparison and future generated contracts."""
    if payload.get("contract_version") != CONTRACT_VERSION:
        raise SemanticConsumerError("unsupported consumer contract version")
    _consumer_shape(payload)
    _safe(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def page_consumer(
    items: Sequence[Mapping[str, Any]],
    *,
    indicator_id: str | None = None,
    measure_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Bound in-memory service discovery; the future HTTP policy belongs to API #52."""
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= MAX_PAGE_SIZE
    ):
        raise SemanticConsumerError("invalid pagination")
    for field, value in (("indicator_id", indicator_id), ("measure_id", measure_id)):
        if value is not None and (
            not isinstance(value, str) or len(value) > 120 or not _ID.fullmatch(value)
        ):
            raise SemanticConsumerError(f"invalid {field}")
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item.get("contract_version") != CONTRACT_VERSION:
            raise SemanticConsumerError("unsupported consumer contract version")
        _consumer_shape(item)
        _safe(item)
        identity = (item["observation"]["id"], item["observation"]["revision_id"])
        if identity in seen:
            raise SemanticConsumerError("duplicate consumer observation revision")
        seen.add(identity)
    if indicator_id is not None and not any(
        item["indicator"]["id"] == indicator_id for item in items
    ):
        raise KeyError("unknown indicator ID")
    if measure_id is not None and not any(item["measure"]["id"] == measure_id for item in items):
        raise KeyError("unknown measure ID")
    selected = sorted(
        (
            item
            for item in items
            if (indicator_id is None or item["indicator"]["id"] == indicator_id)
            and (measure_id is None or item["measure"]["id"] == measure_id)
        ),
        key=lambda item: (
            item["measure"]["id"],
            item["observation"]["id"],
            item["observation"]["revision_id"],
        ),
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "total": len(selected),
        "offset": offset,
        "limit": limit,
        "items": selected[offset : offset + limit],
    }
