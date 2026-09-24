"""Storage-neutral metadata attached to Story #190 semantic measure identities.

This module validates contract definitions, not source approval, lineage joins,
Snowflake state, or permission to publish an internal derived result.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from .semantic_domain import meaning_signature, validate_measures
from .surveillance_safe import has_sensitive_path

CONTRACT_VERSION = "atlas-semantic-metadata-v1"
_STATES = {"KNOWN", "UNKNOWN", "NOT_APPLICABLE", "UNAVAILABLE"}
_AUTHORITIES = {
    "SOURCE_REPORTED",
    "STEWARD_REVIEWED",
    "GOVERNED_GENERATED",
    "NON_AUTHORITATIVE_GENERATED_SUMMARY",
}
_VISIBILITIES = {"INTERNAL", "CONSUMER_SAFE", "PUBLIC"}
_TOP_LEVEL_FIELDS = {
    "contract_version",
    "metadata_id",
    "metadata_revision",
    "revision_id",
    "meaning_signature",
    "measure",
    "label",
    "definition",
    "short_description",
    "authority",
    "summary_source_revision",
    "steward_review",
    "applicability",
    "unit",
    "denominator",
    "allowed_value_states",
    "provenance",
    "freshness",
    "quality_evidence",
    "limitations",
    "visibility",
}
_LIMIT_CATEGORIES = {
    "USE_RESTRICTION",
    "INTERPRETATION",
    "REPRESENTATIVENESS",
    "DENOMINATOR",
    "SOURCE",
    "METHOD",
}
_SAFE_CONTRACTS = {
    "surveillance-quality-profile-v1",
    "surveillance-quality-propagation-v1",
    "surveillance-scientific-eligibility-v1",
    "infected-tick-derived-result-v1",
    "surveillance-coverage-result-v2",
    "surveillance-priority-result-v2",
}
_DERIVED_METHODS = {
    "infected-tick-metrics-v1": (
        "infected-tick-calculation-v1",
        {"SYNTHETIC_FIXTURE", "CURRENT_CODE_CI_TESTED_SOURCE_REPLAY_LIMITED"},
    ),
    "surveillance-coverage-v1": (
        "surveillance-coverage-calculation-v2",
        {"SYNTHETIC_FIXTURE", "CURRENT_CODE_SOURCE_BACKED_REPLAY"},
    ),
    "surveillance-priority-v1": (
        "surveillance-priority-v1",
        {"SYNTHETIC_FIXTURE", "CURRENT_CODE_SOURCE_BACKED_REPLAY"},
    ),
}
_UNSAFE_VALUE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|[?&](?:token|signature|credential|password|secret)=|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----|[A-Za-z]:\\|(?:^|\s)/(?:home|tmp|private|mnt)/)",
    re.IGNORECASE,
)
_UNSAFE_KEY = re.compile(
    r"(?:artifact|raw|secret|token|credential|password|private.key|signed|payload)",
    re.IGNORECASE,
)
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class SemanticMetadataError(ValueError):
    """Metadata contradicts its authoritative measure or safe contract."""


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticMetadataError(f"{field} requires nonempty text")
    return value


def _reference(value: object, field: str) -> str:
    result = _text(value, field)
    if not _ID.fullmatch(result):
        raise SemanticMetadataError(f"{field} requires a stable reference ID")
    return result


def _state_field(value: object, field: str, *, date_value: bool = False) -> None:
    if not isinstance(value, Mapping) or set(value) != {"state", "value"}:
        raise SemanticMetadataError(f"{field} requires state and value")
    state = value["state"]
    if state not in _STATES:
        raise SemanticMetadataError(f"{field} has invalid state")
    if state == "KNOWN":
        text = _text(value["value"], field)
        if date_value:
            if not _DATE.fullmatch(text):
                raise SemanticMetadataError(f"{field} requires ISO date")
            try:
                date.fromisoformat(text)
            except ValueError as exc:
                raise SemanticMetadataError(f"{field} requires ISO date") from exc
    elif value["value"] is not None:
        raise SemanticMetadataError(f"{field} absent state requires null value")


def _timestamp_field(value: Mapping[str, Any], field: str) -> None:
    if value["state"] != "KNOWN":
        return
    stamp = value["value"]
    if not isinstance(stamp, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z",
        stamp,
    ):
        raise SemanticMetadataError(f"{field} requires UTC ISO timestamp")
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SemanticMetadataError(f"{field} requires UTC ISO timestamp") from exc


def _observation_period(value: Mapping[str, Any], semantics: str) -> None:
    if value["state"] != "KNOWN":
        return
    period = value["value"]
    if semantics == "PERIOD":
        if not isinstance(period, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}", period
        ):
            raise SemanticMetadataError("observation_period requires ISO start/end")
        start, end = period.split("/")
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError as exc:
            raise SemanticMetadataError("observation_period requires ISO start/end") from exc
        if start_date > end_date:
            raise SemanticMetadataError("observation_period start exceeds end")
    elif not isinstance(period, str) or not _DATE.fullmatch(period):
        raise SemanticMetadataError("observation_period requires ISO date")
    else:
        try:
            date.fromisoformat(period)
        except ValueError as exc:
            raise SemanticMetadataError("observation_period requires ISO date") from exc


def _safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _UNSAFE_KEY.search(key) or _UNSAFE_VALUE.search(key):
                raise SemanticMetadataError("restricted metadata key")
            _safe(item)
    elif isinstance(value, list):
        for item in value:
            _safe(item)
    elif isinstance(value, str) and (_UNSAFE_VALUE.search(value) or has_sensitive_path(value)):
        raise SemanticMetadataError("restricted metadata value")


def metadata_revision_id(metadata: Mapping[str, Any]) -> str:
    """Hash reviewed metadata content, excluding the supplied revision digest."""
    content = {key: value for key, value in metadata.items() if key != "revision_id"}
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return "metadata-revision:v1:" + digest


def validate_metadata(
    metadata: Mapping[str, Any],
    *,
    approved_source_versions: set[tuple[str, str, str]] | None = None,
) -> None:
    """Validate one metadata revision against its embedded #190 measure."""
    if metadata.get("contract_version") != CONTRACT_VERSION:
        raise SemanticMetadataError("unsupported metadata contract version")
    if metadata.get("visibility") in {"CONSUMER_SAFE", "PUBLIC"}:
        _safe(metadata)
    if set(metadata) - _TOP_LEVEL_FIELDS:
        raise SemanticMetadataError("unsupported metadata field")
    measure = metadata.get("measure")
    if not isinstance(measure, Mapping):
        raise SemanticMetadataError("measure definition required")
    try:
        validate_measures([measure])
    except (KeyError, ValueError) as exc:
        raise SemanticMetadataError(f"invalid #190 measure: {exc}") from exc
    identity = f"metadata:{measure['measure_id']}:{measure['semantic_version']}"
    if metadata.get("metadata_id") != identity:
        raise SemanticMetadataError("metadata identity must attach to #190 measure identity")
    revision = metadata.get("metadata_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise SemanticMetadataError("positive metadata revision required")
    if metadata.get("meaning_signature") != meaning_signature(measure):
        raise SemanticMetadataError("unversioned meaning change")
    _text(metadata.get("label"), "label")
    _text(metadata.get("definition"), "definition")
    if metadata["definition"] != measure["definition"]:
        raise SemanticMetadataError("definition must agree with #190 meaning")
    _state_field(metadata.get("short_description"), "short_description")
    authority = metadata.get("authority")
    if not isinstance(authority, Mapping) or set(authority) != {
        "label",
        "definition",
        "short_description",
    }:
        raise SemanticMetadataError("field authority required")
    if any(item not in _AUTHORITIES for item in authority.values()):
        raise SemanticMetadataError("invalid field authority")
    if authority["definition"] == "NON_AUTHORITATIVE_GENERATED_SUMMARY":
        raise SemanticMetadataError("generated summary cannot author scientific definition")
    if authority["short_description"] == "NON_AUTHORITATIVE_GENERATED_SUMMARY":
        if metadata["short_description"]["state"] != "KNOWN":
            raise SemanticMetadataError("generated summary requires labeled text")
        source_revision = metadata.get("summary_source_revision")
        if (
            not isinstance(source_revision, str)
            or not source_revision.startswith("metadata-revision:v1:")
            or source_revision == metadata.get("revision_id")
        ):
            raise SemanticMetadataError(
                "generated summary requires authoritative revision reference"
            )
    elif metadata.get("summary_source_revision") is not None:
        raise SemanticMetadataError("summary reference only applies to generated summary")
    review = metadata.get("steward_review")
    if not isinstance(review, Mapping) or set(review) != {"state", "reviewed_at"}:
        raise SemanticMetadataError("steward review state required")
    if review["state"] not in {"PENDING", "REVIEWED"}:
        raise SemanticMetadataError("invalid steward review state")
    _state_field(review["reviewed_at"], "reviewed_at", date_value=True)
    if (review["state"] == "REVIEWED") != (review["reviewed_at"]["state"] == "KNOWN"):
        raise SemanticMetadataError("review state/date contradiction")
    applicability = metadata.get("applicability")
    if not isinstance(applicability, Mapping) or set(applicability) != {
        "geography_grain",
        "temporal_semantics",
        "allowed_strata",
        "origin",
        "representativeness",
    }:
        raise SemanticMetadataError("complete applicability required")
    for field in ("geography_grain", "temporal_semantics", "allowed_strata", "origin"):
        if applicability[field] != measure[field]:
            raise SemanticMetadataError(f"invalid {field} applicability")
    representative = applicability["representativeness"]
    expected = {
        "COUNTY": "COUNTY_NATIVE_STATUS",
        "SITE_EVENT": "NOT_COUNTY_REPRESENTATIVE",
        "SOURCE_ONLY_COUNTY": "UNKNOWN",
    }[measure["geography_grain"]]
    if representative != expected:
        raise SemanticMetadataError("contradictory representativeness applicability")
    if metadata.get("unit") != measure["unit"]:
        raise SemanticMetadataError("incompatible unit")
    if metadata.get("denominator") != measure["denominator"]:
        raise SemanticMetadataError("incompatible denominator")
    if metadata.get("allowed_value_states") != measure["allowed_value_states"]:
        raise SemanticMetadataError("incompatible value states")
    provenance = metadata.get("provenance")
    if not isinstance(provenance, Mapping) or set(provenance) != {
        "publisher",
        "source_id",
        "dataset_id",
        "source_version_id",
        "source_vintage",
        "method_version",
        "transformation_version",
    }:
        raise SemanticMetadataError("complete provenance references required")
    for field in ("publisher", "source_id", "dataset_id", "source_version_id", "source_vintage"):
        _state_field(provenance[field], field)
        if provenance[field]["state"] != "KNOWN":
            raise SemanticMetadataError(f"mandatory {field} provenance unknown or unavailable")
    for field in ("source_id", "dataset_id"):
        _reference(provenance[field]["value"], field)
    source_version = provenance["source_version_id"]["value"]
    if source_version.startswith("REPLACE_WITH_") or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]*", source_version
    ):
        raise SemanticMetadataError("invalid source/version reference")
    source_tuple = (
        provenance["source_id"]["value"],
        provenance["dataset_id"]["value"],
        source_version,
    )
    if approved_source_versions is not None and source_tuple not in approved_source_versions:
        raise SemanticMetadataError("stale or unapproved source/version reference")
    _state_field(provenance["method_version"], "method_version")
    if (
        provenance["method_version"]["state"] != "KNOWN"
        or provenance["method_version"]["value"] != measure["methodology_version"]
    ):
        raise SemanticMetadataError("unapproved method version reference")
    _state_field(provenance["transformation_version"], "transformation_version")
    if measure["origin"] == "DERIVED" and provenance["transformation_version"]["state"] != "KNOWN":
        raise SemanticMetadataError("derived transformation version required")
    if measure["origin"] == "DERIVED":
        method = _DERIVED_METHODS.get(measure["methodology_version"])
        if method is None or provenance["transformation_version"]["value"] != method[0]:
            raise SemanticMetadataError("unapproved derived transformation version")
    freshness = metadata.get("freshness")
    if not isinstance(freshness, Mapping) or set(freshness) != {
        "observation_period",
        "source_vintage",
        "retrieved_at",
        "published_at",
        "metadata_revised_at",
    }:
        raise SemanticMetadataError("distinct freshness fields required")
    for field in freshness:
        _state_field(
            freshness[field], field, date_value=field in {"published_at", "metadata_revised_at"}
        )
    _timestamp_field(freshness["retrieved_at"], "retrieved_at")
    _observation_period(freshness["observation_period"], measure["temporal_semantics"])
    if freshness["source_vintage"] != provenance["source_vintage"]:
        raise SemanticMetadataError("source vintage freshness mismatch")
    if freshness["metadata_revised_at"]["state"] != "KNOWN":
        raise SemanticMetadataError("metadata revision date required")
    quality = metadata.get("quality_evidence")
    if not isinstance(quality, Mapping) or set(quality) != {
        "quality_contract",
        "propagation_contract",
        "eligibility_contract",
        "uncertainty",
        "evidence_basis",
    }:
        raise SemanticMetadataError("quality/evidence references required")
    for field in quality:
        _state_field(quality[field], field)
        if (
            field.endswith("contract")
            and quality[field]["state"] == "KNOWN"
            and quality[field]["value"] not in _SAFE_CONTRACTS
        ):
            raise SemanticMetadataError("unapproved quality or eligibility contract")
    if measure["origin"] == "DERIVED" and quality["evidence_basis"]["state"] != "KNOWN":
        raise SemanticMetadataError("derived evidence basis required")
    if measure["origin"] == "DERIVED":
        allowed_basis = _DERIVED_METHODS[measure["methodology_version"]][1]
        if quality["evidence_basis"]["value"] not in allowed_basis:
            raise SemanticMetadataError("unapproved derived evidence basis")
    limitations = metadata.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise SemanticMetadataError("at least one interpretation limitation required")
    categories: set[str] = set()
    for limit in limitations:
        if not isinstance(limit, Mapping) or set(limit) != {"category", "code", "text"}:
            raise SemanticMetadataError("typed limitation required")
        if limit["category"] not in _LIMIT_CATEGORIES:
            raise SemanticMetadataError("invalid limitation category")
        _reference(limit["code"], "limitation code")
        _text(limit["text"], "limitation text")
        categories.add(limit["category"])
    if "INTERPRETATION" not in categories:
        raise SemanticMetadataError("interpretation limitation required")
    if measure["geography_grain"] != "COUNTY" and "REPRESENTATIVENESS" not in categories:
        raise SemanticMetadataError("representativeness limitation required")
    if measure["denominator"] != "NONE" and "DENOMINATOR" not in categories:
        raise SemanticMetadataError("denominator limitation required")
    visibility = metadata.get("visibility")
    if visibility not in _VISIBILITIES:
        raise SemanticMetadataError("invalid visibility")
    if measure["origin"] == "DERIVED" and visibility != "INTERNAL":
        raise SemanticMetadataError("derived result requires separate exposure approval")
    if visibility == "PUBLIC" and review["state"] != "REVIEWED":
        raise SemanticMetadataError("public metadata requires steward review")
    if metadata.get("revision_id") != metadata_revision_id(metadata):
        raise SemanticMetadataError("metadata revision digest mismatch")


def validate_metadata_revisions(
    revisions: Sequence[Mapping[str, Any]],
    *,
    approved_source_versions: set[tuple[str, str, str]] | None = None,
) -> None:
    """Reject duplicate revisions, gaps, and silent changes to one measure version."""
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in revisions:
        validate_metadata(item, approved_source_versions=approved_source_versions)
        by_id.setdefault(item["metadata_id"], []).append(item)
    for items in by_id.values():
        ordered = sorted(items, key=lambda item: item["metadata_revision"])
        authoritative_revisions: set[str] = set()
        for number, item in enumerate(ordered, 1):
            if item["metadata_revision"] != number:
                raise SemanticMetadataError("metadata revision gap or duplicate")
            if number > 1 and item["meaning_signature"] != ordered[0]["meaning_signature"]:
                raise SemanticMetadataError("unversioned meaning change")
            if number > 1 and item["definition"] != ordered[0]["definition"]:
                raise SemanticMetadataError("definition change requires semantic version")
            if (
                number > 1
                and item["limitations"] != ordered[number - 2]["limitations"]
                and item["steward_review"]["state"] != "REVIEWED"
            ):
                raise SemanticMetadataError("interpretation change requires steward review")
            source_revision = item.get("summary_source_revision")
            if source_revision is not None and source_revision not in authoritative_revisions:
                raise SemanticMetadataError(
                    "generated summary source revision is not authoritative"
                )
            if item["steward_review"]["state"] == "REVIEWED":
                authoritative_revisions.add(item["revision_id"])
