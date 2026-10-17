"""Read-only CDC readiness before existing publication status/pointer DML.

Candidates retain their real lifecycle. Serving stays PUBLISHED-only. The
predecessor's retained reviewed membership, not successful joins/counts, defines
required support. All scope rows are inspected, including excluded placeholders.
"""

import json
from collections.abc import Iterable, Mapping
from importlib.resources import as_file
from pathlib import Path
from typing import Any

from .cdc_consumer_admission import RELEASE_BUNDLES, RELEASE_ID, SLICES
from .cdc_consumer_runtime import AUTHORITY_SQL, _inputs, _json, _metadata, _packet, _resources
from .semantic_source_mappings import load_mapping_registry
from .surveillance_evidence_mapping import project_surveillance_evidence


class CDCPromotionBlocked(ValueError):
    """Safe fixed failure; no private records or authority in the message."""


def validate_candidate_rows(
    rows: Iterable[dict[str, Any]],
    metadata: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    required_counties: set[str],
    release_id: str,
    *,
    expected_status: str = "CANDIDATE",
) -> int:
    if not required_counties:
        raise CDCPromotionBlocked("CDC predecessor membership unavailable")
    seen: set[str] = set()
    try:
        for row in rows:
            county = row["county_fips"]
            if row["release_id"] != release_id or county in seen or county not in required_counties:
                raise CDCPromotionBlocked("CDC candidate membership mismatch")
            seen.add(county)
            record, authority = _inputs(row, metadata, expected_status=expected_status)
            project_surveillance_evidence(record, metadata, authority, mappings)
    except Exception:
        raise CDCPromotionBlocked("CDC candidate consumer authority invalid") from None
    if seen != required_counties:
        raise CDCPromotionBlocked("CDC candidate loses supported observations")
    return len(seen)


def _withdrawal_approved(
    configured: Any, reviews: list[Any], release_id: str, measure: str
) -> bool:
    """A reviewed contract artifact AND a separately retained active human decision."""
    if not isinstance(configured, dict) or set(configured) != {"decision_id", "decision_reference"}:
        return False
    matches = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        if (
            review.get("decision_id") == configured["decision_id"]
            and review.get("active_steward") is True
            and review.get("reviewer")
            and review.get("decided_at")
            and review.get("decision") in {"APPROVED", "APPROVED_WITH_CONDITIONS"}
        ):
            for condition in review.get("conditions") or []:
                withdrawal = (
                    condition.get("cdc_consumer_withdrawal", {})
                    if isinstance(condition, dict)
                    else {}
                )
                if (
                    withdrawal
                    == {
                        "release_id": release_id,
                        "bundle_sha256": RELEASE_BUNDLES[release_id],
                        "measure_id": measure,
                        "decision_reference": configured["decision_reference"],
                    }
                    and len(str(configured["decision_reference"]).strip()) >= 6
                ):
                    matches.append(review["decision_id"])
    return len(matches) == 1


def _read_scope(cursor: Any, release_id: str, measure: str) -> list[dict[str, Any]]:
    # Do not SQL-filter versions/match kinds: doing so would hide invalid extras.
    select = AUTHORITY_SQL.split("\n FROM", 1)[0].replace(
        " cdc_runtime_authority",
        " OBJECT_DELETE(cdc_runtime_authority, 'review_decisions', "
        "'attestations') AS cdc_runtime_authority",
    )
    cursor.execute(
        select + " FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V "
        "WHERE release_id=%s AND measure_id=%s ORDER BY county_fips",
        (release_id, measure),
    )
    columns = [str(c[0]).lower() for c in cursor.description]
    rows: list[dict[str, Any]] = []
    while batch := cursor.fetchmany(128):
        rows.extend(dict(zip(columns, values, strict=True)) for values in batch)
    counties = [r["county_fips"] for r in rows]
    ids = [r["observation_id"] for r in rows]
    if not rows or len(counties) != len(set(counties)) or len(ids) != len(set(ids)):
        raise CDCPromotionBlocked("CDC scope is missing or contains duplicates")
    # The audit view joins source tuples. Compare against storage independently
    # so malformed tuples cannot disappear before this gate sees them.
    cursor.execute(
        "SELECT observation_id, value, value_state, temporal_window, limitations, quality_state, "
        "retrieved_at, transformation_version, geography_semantics "
        "FROM PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id=%s AND measure_id=%s",
        (release_id, measure),
    )
    columns = [str(c[0]).lower() for c in cursor.description]
    persisted: dict[str, dict[str, Any]] = {}
    while batch := cursor.fetchmany(128):
        for values in batch:
            item = dict(zip(columns, values, strict=True))
            identity = item.pop("observation_id")
            if identity in persisted:
                raise CDCPromotionBlocked("CDC persisted membership ambiguous")
            persisted[identity] = item
    if set(persisted) != set(ids):
        raise CDCPromotionBlocked("CDC lineage omits persisted observations")
    for row in rows:
        row["persisted_interpretation"] = persisted[row["observation_id"]]
    samples = [r for r in rows if r["record_match_kind"] == "RESTRICTED_CDC_CONFORMED"]
    if not samples:
        raise CDCPromotionBlocked("CDC source authority unavailable")
    cursor.execute(
        AUTHORITY_SQL,
        (release_id, measure, samples[0]["county_fips"], SLICES[measure]["source_version_id"]),
    )
    columns = [str(c[0]).lower() for c in cursor.description]
    values = cursor.fetchmany(2)
    if len(values) != 1:
        raise CDCPromotionBlocked("CDC source authority unavailable")
    facts = dict(zip(columns, values[0], strict=True))["cdc_runtime_authority"]
    facts = json.loads(facts) if isinstance(facts, str) else facts
    for row in rows:
        item = row["cdc_runtime_authority"]
        item = json.loads(item) if isinstance(item, str) else item
        if isinstance(item, dict):
            item["review_decisions"] = facts.get("review_decisions") or []
            item["attestations"] = facts.get("attestations") or []
        row["cdc_runtime_authority"] = item
    return rows


def _reviewed_ids(
    rows: list[dict[str, Any]], metadata: Mapping[str, Any], release: str
) -> set[str]:
    facts = next(
        r["cdc_runtime_authority"] for r in rows if isinstance(r["cdc_runtime_authority"], dict)
    )
    ids: set[str] = set()
    for review in facts.get("review_decisions") or []:
        for condition in review.get("conditions") or []:
            packet = (
                condition.get("cdc_consumer_admission", {}) if isinstance(condition, dict) else {}
            )
            if (
                packet.get("release_id") != release
                or packet.get("metadata_revision_id") != metadata["revision_id"]
            ):
                continue
            bindings = packet.get("observation_bindings")
            if not isinstance(bindings, dict) or not bindings:
                raise CDCPromotionBlocked("CDC reviewed membership unavailable")
            try:
                _packet(
                    facts, metadata, {"release_id": release, "observation_id": next(iter(bindings))}
                )
            except Exception:
                raise CDCPromotionBlocked("CDC retained review invalid") from None
            if ids & bindings.keys():
                raise CDCPromotionBlocked("CDC reviewed membership ambiguous")
            ids.update(bindings)
    if not ids or not ids <= {r["observation_id"] for r in rows}:
        raise CDCPromotionBlocked("CDC reviewed membership lost")
    return ids


def _excluded_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in row.items()
        if k
        not in {
            "observation_id",
            "release_id",
            "release_bundle_sha256",
            "cdc_runtime_authority",
        }
    }


def verify_cdc_candidate(
    cursor: Any, release_id: str, bundle: str, previous_release_id: str | None
) -> dict[str, int]:
    if RELEASE_BUNDLES.get(release_id) != bundle or previous_release_id is None:
        raise CDCPromotionBlocked("CDC candidate has no reviewed consumer binding")
    root = _resources()
    binding = _json(
        root.joinpath(
            "release-binding.json"
            if release_id == RELEASE_ID
            else "release-binding-2026-10-15.json"
        )
    )
    if (
        binding.get("release_id") != release_id
        or binding.get("bundle_sha256") != bundle
        or binding.get("slices") != SLICES
    ):
        raise CDCPromotionBlocked("CDC candidate packaged scope mismatch")
    resource = root.joinpath("atlas-semantic-source-mappings-v1.json")
    if not resource.is_file() and isinstance(root, Path):
        resource = root.parent / "atlas-semantic-source-mappings-v1.json"
    with as_file(resource) as path:
        mappings = load_mapping_registry(path)
    counts = {}
    for measure, scope in SLICES.items():
        previous = _read_scope(cursor, previous_release_id, measure)
        previous_metadata = _metadata(root, measure, previous_release_id)
        previous_ids = _reviewed_ids(previous, previous_metadata, previous_release_id)
        admitted = [r for r in previous if r["observation_id"] in previous_ids]
        counties = {r["county_fips"] for r in admitted}
        validate_candidate_rows(
            admitted,
            previous_metadata,
            mappings,
            counties,
            previous_release_id,
            expected_status="PUBLISHED",
        )
        withdrawal = binding.get("withdrawals", {}).get(measure)
        if withdrawal is not None:
            cursor.execute(
                "SELECT OBJECT_CONSTRUCT('decision_id', d.manual_review_decision_id, "
                "'active_steward', TRUE, 'reviewer', d.reviewer_username, "
                "'decided_at', TO_VARCHAR(d.decided_at), 'decision', d.decision, "
                "'conditions', d.conditions) FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d "
                "WHERE d.resource_key=%s AND d.data_source_version_id=%s "
                "AND (SELECT COUNT(*) FROM GOVERNANCE.APPROVAL_STEWARDS s "
                "WHERE s.username=d.reviewer_username AND s.is_active=TRUE "
                "AND s.authorization_scope='GLOBAL')=1 "
                "AND NOT EXISTS (SELECT 1 FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS n "
                "WHERE n.supersedes_decision_id=d.manual_review_decision_id)",
                (scope["resource_key"], scope["source_version_id"]),
            )
            reviews = [
                json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in cursor.fetchall()
            ]
            if not _withdrawal_approved(withdrawal, reviews, release_id, measure):
                raise CDCPromotionBlocked("CDC withdrawal is not independently approved")
            counts[measure] = 0
            continue
        candidate = _read_scope(cursor, release_id, measure)
        excluded = {
            r["county_fips"]: r for r in previous if r["observation_id"] not in previous_ids
        }
        if {r["county_fips"] for r in candidate} != counties | excluded.keys():
            raise CDCPromotionBlocked("CDC scope membership changed")
        for row in candidate:
            if row["county_fips"] in excluded and (
                _excluded_identity(row) != _excluded_identity(excluded[row["county_fips"]])
                or row["record_match_kind"] == "RESTRICTED_CDC_CONFORMED"
            ):
                raise CDCPromotionBlocked("CDC excluded observation changed")
        counts[measure] = validate_candidate_rows(
            [r for r in candidate if r["county_fips"] in counties],
            _metadata(root, measure, release_id),
            mappings,
            counties,
            release_id,
        )
    return counts
