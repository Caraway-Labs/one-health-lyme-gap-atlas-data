"""Storage-neutral temporal alignment and as-of evidence for Data #431.

This validates declared analytical windows. It does not choose a lag, create a
feature, change a source observation, or approve a modeling cohort.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from math import isfinite
from typing import Any

from .semantic_metadata import SemanticMetadataError, _safe

CONTRACT_VERSION = "atlas-temporal-alignment-v1"
DISPOSITIONS = frozenset({"ELIGIBLE", "RETROSPECTIVE_ONLY", "UNKNOWN_AVAILABILITY", "INELIGIBLE"})
_LAG_KINDS = {"ZERO", "FIXED", "ROLLING", "SEASONAL"}
_AGGREGATIONS = {"NONE", "SUM", "MEAN", "CATEGORY", "ANOMALY"}
_COVERAGE_UNITS = {"DAYS", "COMPOSITES", "SOURCE_SUPPORTED_AREA", "RECORDS"}


class TemporalAlignmentError(ValueError):
    """A declared alignment is malformed or internally inconsistent."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TemporalAlignmentError(f"{name} must be a mapping")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TemporalAlignmentError(f"{name} is required")
    return value


def _date(value: Any, name: str) -> date:
    text = _text(value, name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise TemporalAlignmentError(f"{name} requires an ISO date") from exc
    if parsed.isoformat() != text:
        raise TemporalAlignmentError(f"{name} requires an ISO date")
    return parsed


def _instant(value: Any, name: str) -> datetime | None:
    if value is None:
        return None
    text = _text(value, name)
    if not text.endswith("Z"):
        raise TemporalAlignmentError(f"{name} requires a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TemporalAlignmentError(f"{name} requires a UTC timestamp") from exc
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise TemporalAlignmentError(f"{name} requires UTC")
    return parsed


def _window(value: Any, name: str) -> tuple[date, date]:
    window = _mapping(value, name)
    if window.get("calendar") != "GREGORIAN" or window.get("timezone") != "UTC":
        raise TemporalAlignmentError(f"{name} requires explicit Gregorian/UTC convention")
    start = _date(window.get("start"), f"{name}.start")
    end = _date(window.get("end_exclusive"), f"{name}.end_exclusive")
    if start >= end:
        raise TemporalAlignmentError(f"{name} must be a nonempty half-open period")
    return start, end


def _reference(value: Any, name: str) -> str:
    reference = _text(value, name)
    if not reference.startswith("https://"):
        raise TemporalAlignmentError(f"{name} requires an HTTPS reference")
    return reference


def _proven_time(evidence: Mapping[str, Any], timestamp: str, reference: str) -> datetime | None:
    instant = _instant(evidence.get(timestamp), timestamp)
    if instant is not None:
        _reference(evidence.get(reference), reference)
    elif evidence.get(reference) is not None:
        raise TemporalAlignmentError(f"{reference} cannot establish a missing timestamp")
    return instant


def _result(spec: Mapping[str, Any], state: str, reasons: list[str]) -> dict[str, Any]:
    observation = spec["observation_window"]
    target = spec["target_window"]
    lag = spec["lag"]
    coverage = spec["aggregation"]["coverage"]
    result = {
        "contract_version": CONTRACT_VERSION,
        "method_id": spec["method_id"],
        "method_version": spec["method_version"],
        "source_id": spec["source_id"],
        "measure_id": spec["measure_id"],
        "observation_window": {
            field: observation[field]
            for field in ("start", "end_exclusive", "calendar", "timezone")
        },
        "target_window": {
            field: target[field] for field in ("start", "end_exclusive", "calendar", "timezone")
        },
        "lag": {
            field: lag[field]
            for field in ("kind", "anchor", "offset_days", "window_days", "season_id")
            if field in lag
        },
        "coverage": {
            field: coverage[field] for field in ("expected", "observed", "unit", "partial_allowed")
        },
        "aggregation_rule": spec["aggregation"]["rule"],
        "coverage_denominator": spec["aggregation"]["denominator"],
        "decision_cutoff": spec["decision_cutoff"],
        "disposition": state,
        "reason_codes": reasons,
        "limitations": list(spec["limitations"]),
    }
    if spec.get("reference_period") is not None:
        reference = spec["reference_period"]
        result["reference_period"] = {
            field: reference[field] for field in ("id", "start", "end_exclusive", "source_vintage")
        }
    return result


def evaluate_alignment(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one declared alignment and return its strict as-of disposition."""
    if spec.get("contract_version") != CONTRACT_VERSION:
        raise TemporalAlignmentError("unsupported temporal alignment version")
    for field in (
        "method_id",
        "method_version",
        "source_id",
        "measure_id",
        "source_version_id",
        "source_vintage",
        "revision_id",
    ):
        _text(spec.get(field), field)
    limitations = spec.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise TemporalAlignmentError("nonempty limitations required")
    for limitation in limitations:
        _text(limitation, "limitation")

    observed_start, observed_end = _window(spec.get("observation_window"), "observation_window")
    target_start, target_end = _window(spec.get("target_window"), "target_window")
    cutoff = _instant(spec.get("decision_cutoff"), "decision_cutoff")
    if cutoff is None:
        raise TemporalAlignmentError("decision_cutoff required")
    lag = _mapping(spec.get("lag"), "lag")
    kind = lag.get("kind")
    if kind not in _LAG_KINDS or lag.get("anchor") not in {"START", "END_EXCLUSIVE"}:
        raise TemporalAlignmentError("explicit lag kind and anchor required")
    offset = lag.get("offset_days")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise TemporalAlignmentError("nonnegative integer offset_days required")
    if kind == "ZERO":
        if offset != 0 or (observed_start, observed_end) != (target_start, target_end):
            raise TemporalAlignmentError("ZERO requires identical windows and zero offset")
    else:
        anchor = observed_start if lag["anchor"] == "START" else observed_end
        if (target_start - anchor).days != offset or observed_end > target_start:
            raise TemporalAlignmentError("lag offset/window does not match declared periods")
        if kind in {"FIXED", "ROLLING", "SEASONAL"}:
            _reference(spec.get("rationale_reference"), "rationale_reference")
    if kind == "ROLLING":
        if lag.get("window_days") != (observed_end - observed_start).days:
            raise TemporalAlignmentError("rolling window_days does not match observation period")
    elif lag.get("window_days") is not None:
        raise TemporalAlignmentError("window_days is reserved for ROLLING")
    if kind == "SEASONAL":
        _text(lag.get("season_id"), "season_id")
    elif lag.get("season_id") is not None:
        raise TemporalAlignmentError("season_id is reserved for SEASONAL")

    aggregation = _mapping(spec.get("aggregation"), "aggregation")
    if aggregation.get("rule") not in _AGGREGATIONS:
        raise TemporalAlignmentError("unsupported aggregation rule")
    _text(aggregation.get("denominator"), "aggregation denominator")
    coverage = _mapping(aggregation.get("coverage"), "coverage")
    expected, observed = coverage.get("expected"), coverage.get("observed")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, (int, float))
        or not isfinite(expected)
        or expected <= 0
        or isinstance(observed, bool)
        or not isinstance(observed, (int, float))
        or not isfinite(observed)
        or not 0 <= observed <= expected
        or coverage.get("unit") not in _COVERAGE_UNITS
        or not isinstance(coverage.get("partial_allowed"), bool)
    ):
        raise TemporalAlignmentError("invalid expected/observed coverage")
    if coverage["unit"] != "SOURCE_SUPPORTED_AREA" and (
        not isinstance(expected, int) or not isinstance(observed, int)
    ):
        raise TemporalAlignmentError("discrete coverage requires integer counts")
    if coverage["unit"] == "DAYS" and expected != (observed_end - observed_start).days:
        raise TemporalAlignmentError("expected DAYS must include every calendar day in the window")
    if coverage["partial_allowed"]:
        _reference(coverage.get("policy_reference"), "coverage.policy_reference")
    if aggregation["rule"] == "ANOMALY" and spec.get("reference_period") is None:
        raise TemporalAlignmentError("ANOMALY requires a versioned reference period")
    if aggregation["rule"] != "ANOMALY" and spec.get("reference_period") is not None:
        raise TemporalAlignmentError("reference_period is reserved for ANOMALY")

    availability = _mapping(spec.get("availability"), "availability")
    published = _proven_time(availability, "first_published_at", "first_publication_reference")
    revised = _proven_time(availability, "revision_available_at", "revision_reference")
    completed = _proven_time(availability, "complete_at", "completeness_reference")
    retrieved = _instant(availability.get("retrieved_at"), "retrieved_at")
    _instant(availability.get("source_modified_at"), "source_modified_at")
    reference_available: datetime | None = None
    reference_revision: datetime | None = None
    reference_complete: datetime | None = None
    reference_end: date | None = None
    if spec.get("reference_period") is not None:
        reference = _mapping(spec["reference_period"], "reference_period")
        _text(reference.get("id"), "reference_period.id")
        _text(reference.get("source_vintage"), "reference_period.source_vintage")
        _text(reference.get("revision_id"), "reference_period.revision_id")
        _, reference_end = _window(reference, "reference_period")
        reference_available = _proven_time(
            reference, "first_published_at", "first_publication_reference"
        )
        reference_revision = _proven_time(reference, "revision_available_at", "revision_reference")
        reference_complete = _proven_time(reference, "complete_at", "completeness_reference")

    cutoff_day = cutoff.date()
    if observed_end > cutoff_day or (reference_end is not None and reference_end > cutoff_day):
        return _result(spec, "INELIGIBLE", ["FUTURE_OBSERVATION_OR_REFERENCE_WINDOW"])
    if observed == 0 or (observed < expected and not coverage["partial_allowed"]):
        return _result(spec, "INELIGIBLE", ["INCOMPLETE_REQUIRED_COVERAGE"])
    if any(
        instant is not None and instant > cutoff
        for instant in (
            published,
            revised,
            completed,
            reference_available,
            reference_revision,
            reference_complete,
        )
    ):
        return _result(spec, "INELIGIBLE", ["INPUT_OR_REVISION_AFTER_CUTOFF"])
    if any(instant is None for instant in (published, revised, completed)) or (
        reference_end is not None
        and any(
            instant is None
            for instant in (reference_available, reference_revision, reference_complete)
        )
    ):
        state = "RETROSPECTIVE_ONLY" if retrieved is not None else "UNKNOWN_AVAILABILITY"
        return _result(spec, state, ["HISTORICAL_AVAILABILITY_UNPROVEN"])
    return _result(spec, "ELIGIBLE", ["PROVEN_AVAILABLE_AT_CUTOFF"])


def project_temporal_alignment(result: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist explanatory timing fields; omit private lineage and source payloads."""
    if (
        result.get("contract_version") != CONTRACT_VERSION
        or result.get("disposition") not in DISPOSITIONS
    ):
        raise TemporalAlignmentError("invalid temporal alignment result")
    fields = (
        "contract_version",
        "method_id",
        "method_version",
        "source_id",
        "measure_id",
        "aggregation_rule",
        "coverage_denominator",
        "decision_cutoff",
        "disposition",
        "reason_codes",
        "limitations",
    )
    projected = {field: result[field] for field in fields}
    for name, allowed in (
        ("observation_window", ("start", "end_exclusive", "calendar", "timezone")),
        ("target_window", ("start", "end_exclusive", "calendar", "timezone")),
        ("lag", ("kind", "anchor", "offset_days", "window_days", "season_id")),
        ("coverage", ("expected", "observed", "unit", "partial_allowed")),
    ):
        values = _mapping(result.get(name), name)
        projected[name] = {field: values[field] for field in allowed if field in values}
    if result.get("reference_period") is not None:
        reference = _mapping(result["reference_period"], "reference_period")
        projected["reference_period"] = {
            field: reference[field]
            for field in ("id", "start", "end_exclusive", "source_vintage")
            if field in reference
        }
    try:
        _safe(projected)
    except SemanticMetadataError as exc:
        raise TemporalAlignmentError("restricted temporal projection value") from exc
    return projected
