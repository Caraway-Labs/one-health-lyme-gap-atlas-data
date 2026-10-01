"""Policy-bound health reduction over accepted intelligence ingestion evidence.

No scheduler, alert sender, warehouse permissions or new ingestion entry point.
Callers must supply immutable per-source history and reviewed policy authority.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any, Literal

from .ingestion.intelligence_feed import FETCH_VERSION, PARSER_VERSION
from .ingestion.types import FailureCategory, RunState, Stage, StageStatus
from .intelligence_items import (
    TOKEN,
    canonical_timestamp,
    identity_hash,
    validate_acquisition_context,
    validate_record,
)
from .intelligence_storage import WriteReceipt

Outcome = Literal[
    "success",
    "parser_drift",
    "malformed",
    "access_expired",
    "rate_limited",
    "upstream_outage",
    "policy_blocked",
    "storage_failed",
    "partial",
]


def _time(value: str) -> Fraction:
    canonical = canonical_timestamp(value)
    seconds = canonical[:19]
    fraction = canonical[19:-1]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = datetime.fromisoformat(seconds).replace(tzinfo=UTC) - epoch
    return Fraction(delta.days * 86400 + delta.seconds) + Fraction(f"0{fraction or '.0'}")


def _token(value: str) -> None:
    if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
        raise ValueError("INTELLIGENCE_HEALTH_INVALID_TOKEN")


@dataclass(frozen=True)
class HealthPolicy:
    """Explicit reviewed inputs, never inferred defaults or source activation."""

    policy_ref: str
    source_sha256: str
    escalation_owner: str
    fetch_grace_seconds: int
    item_grace_seconds: int | None
    failure_threshold: int

    def validate(self, source: dict[str, Any]) -> None:
        _token(self.policy_ref)
        _token(self.escalation_owner)
        if self.source_sha256 != identity_hash(source):
            raise ValueError("INTELLIGENCE_HEALTH_POLICY_SOURCE_MISMATCH")
        for value, minimum in ((self.fetch_grace_seconds, 0), (self.failure_threshold, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError("INTELLIGENCE_HEALTH_POLICY_INVALID")
        if self.item_grace_seconds is not None and (
            type(self.item_grace_seconds) is not int or self.item_grace_seconds < 0
        ):
            raise ValueError("INTELLIGENCE_HEALTH_POLICY_INVALID")


@dataclass(frozen=True)
class HealthHistory:
    document: dict[str, Any]
    # Source-local accepted revisions, not the global revision-insert count.
    seen_revisions: frozenset[str]
    source_sha256: str
    attempt_key: str | None = None
    attempt_input_sha256: str | None = None
    incident_episode_at: str | None = None


@dataclass(frozen=True)
class HealthResult:
    history: HealthHistory
    source_state: str
    expected_cadence: dict[str, Any]
    incident_key: str | None
    escalation_owner: str | None
    recovered: bool


def reduce_health(
    source: dict[str, Any],
    *,
    observed_at: str,
    previous: HealthHistory | None = None,
    outcome: Outcome | None = None,
    fetched_at: str | None = None,
    items: tuple[dict[str, Any], ...] = (),
    receipt: WriteReceipt | None = None,
    rejected_items: int = 0,
    policy: HealthPolicy | None = None,
    policy_allowed: Callable[[HealthPolicy], bool] | None = None,
) -> HealthResult:
    """Reduce one completed attempt or a read-only freshness observation.

    Success is accepted only after the storage receipt. Failed attempts preserve
    prior good chronology/items. Coverage is accepted capture time, not evidence
    of continuous publisher coverage. Repeat health observations do not fetch.
    """
    validate_record("source", source)
    if source["transport"] not in {"rss", "atom"}:
        raise ValueError("INTELLIGENCE_HEALTH_TRANSPORT_NOT_DELIVERED")
    now = _time(observed_at)
    observed_at = canonical_timestamp(observed_at)
    if type(rejected_items) is not int or rejected_items < 0:
        raise ValueError("INTELLIGENCE_HEALTH_INVALID_COUNTS")
    if len(items) + rejected_items > source["limits"]["maximum_items"]:
        raise ValueError("INTELLIGENCE_HEALTH_INVALID_COUNTS")
    if policy is not None:
        policy.validate(source)
        allowed = False
        with suppress(Exception):
            allowed = policy_allowed is not None and policy_allowed(policy) is True
        if not allowed:
            raise PermissionError("INTELLIGENCE_HEALTH_POLICY_NOT_REVIEWED")
    old = previous.document if previous else None
    if old is not None:
        validate_record("health", old)
        if (
            old["source_id"] != source["source_id"]
            or old["registry_version"] != source["registry_version"]
            or previous is None
            or previous.source_sha256 != identity_hash(source)
            or _time(old["observed_at"]) > now
        ):
            raise ValueError("INTELLIGENCE_HEALTH_HISTORY_MISMATCH")
    document: dict[str, Any] = {
        "contract_version": "1.0.0",
        "source_id": source["source_id"],
        "registry_version": source["registry_version"],
        "observed_at": observed_at,
        "last_fetch_success_at": None,
        "last_item_observed_at": None,
        "coverage_start_at": None,
        "coverage_end_at": None,
        "parser_version": PARSER_VERSION,
        "fetch_version": FETCH_VERSION,
        "state": "never_fetched",
        "failure_category": None,
        "consecutive_failures": 0,
        "accepted_items": 0,
        "rejected_items": 0,
        "policy_ref": policy.policy_ref if policy else None,
        "next_safe_action": "review-source-policy",
        "diagnostic_code": None,
    }
    if old:
        document.update(old)
        document.update(observed_at=observed_at, policy_ref=policy.policy_ref if policy else None)
    seen = previous.seen_revisions if previous else frozenset()
    if source["state"] not in {"active", "manual"}:
        document.update(
            state="paused",
            failure_category=None,
            accepted_items=0,
            rejected_items=0,
            next_safe_action="review-source-policy",
            diagnostic_code="SOURCE_INACTIVE",
        )
    elif outcome in {"success", "partial"}:
        if fetched_at is None or receipt is None:
            raise ValueError("INTELLIGENCE_HEALTH_STORAGE_RECEIPT_REQUIRED")
        fetch = _time(fetched_at)
        if fetch > now or (
            old and old["last_fetch_success_at"] and (fetch < _time(old["last_fetch_success_at"]))
        ):
            raise ValueError("INTELLIGENCE_HEALTH_FETCH_TIME_INVALID")
        for value in (
            receipt.captures_inserted,
            receipt.captures_replayed,
            receipt.revisions_inserted,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("INTELLIGENCE_HEALTH_INVALID_RECEIPT")
        if receipt.captures_inserted + receipt.captures_replayed != len(
            items
        ) or receipt.revisions_inserted > len(items):
            raise ValueError("INTELLIGENCE_HEALTH_INVALID_RECEIPT")
        revisions: set[str] = set()
        for item in items:
            validate_record("item", item)
            if (
                item["source_id"] != source["source_id"]
                or item["registry_version"] != source["registry_version"]
                or _time(item["fetched_at"]) != fetch
            ):
                raise ValueError("INTELLIGENCE_HEALTH_ITEM_SOURCE_MISMATCH")
            revisions.add(item["revision_id"])
        new = revisions - seen
        seen = seen | revisions
        if len(seen) > 100_000:
            raise ValueError("INTELLIGENCE_HEALTH_HISTORY_LIMIT")
        document.update(
            state="healthy" if new else "quiet",
            last_fetch_success_at=canonical_timestamp(fetched_at),
            failure_category=None,
            consecutive_failures=0,
            accepted_items=len(new),
            rejected_items=0,
            next_safe_action="wait-for-approved-poll",
            diagnostic_code=None,
        )
        if new:
            document["last_item_observed_at"] = canonical_timestamp(fetched_at)
        if items:
            document["coverage_start_at"] = document["coverage_start_at"] or canonical_timestamp(
                fetched_at
            )
            document["coverage_end_at"] = canonical_timestamp(fetched_at)
        if rejected_items or outcome == "partial":
            if not rejected_items:
                raise ValueError("INTELLIGENCE_HEALTH_PARTIAL_REJECTIONS_REQUIRED")
            document.update(
                state="partial",
                failure_category="parser",
                rejected_items=rejected_items,
                consecutive_failures=(old["consecutive_failures"] if old else 0) + 1,
                next_safe_action="review-rejected-items",
                diagnostic_code="PARTIAL_INGESTION",
            )
    elif outcome is not None:
        failures = {
            "parser_drift": ("parser_drift", "parser", "review-parser"),
            "malformed": ("malformed", "parser", "review-parser"),
            "access_expired": ("access_expired", "fetch", "review-access"),
            "rate_limited": ("rate_limited", "fetch", "defer-within-approved-budget"),
            "upstream_outage": ("upstream_outage", "fetch", "defer-within-approved-budget"),
            "policy_blocked": ("access_expired", "policy", "review-source-policy"),
            "storage_failed": ("partial", "storage", "resume-storage-checkpoint"),
        }
        if outcome not in failures:
            raise ValueError("INTELLIGENCE_HEALTH_INVALID_OUTCOME")
        state, category, action = failures[outcome]
        document.update(
            state=state,
            failure_category=category,
            consecutive_failures=(old["consecutive_failures"] if old else 0) + 1,
            accepted_items=0,
            rejected_items=rejected_items,
            next_safe_action=action,
            diagnostic_code=outcome.upper(),
        )
    elif items or receipt is not None or fetched_at is not None or rejected_items:
        raise ValueError("INTELLIGENCE_HEALTH_ATTEMPT_OUTCOME_REQUIRED")
    # A failed attempt stays a failure; never hide it with a stale/quiet label.
    if document["state"] in {"healthy", "quiet", "stale"}:
        stale = False
        if policy:
            cadence = source["cadence"]
            poll = cadence["poll_seconds"]
            expected = cadence["expected_item_seconds"]
            last_fetch = document["last_fetch_success_at"]
            # Manual sources have no automatically assumed polling commitment.
            if source["state"] == "active" and poll and last_fetch:
                stale = now - _time(last_fetch) > poll + policy.fetch_grace_seconds
            last_item = document["last_item_observed_at"]
            if (
                expected is not None
                and cadence["basis"] != "unknown"
                and last_item
                and policy.item_grace_seconds is not None
            ):
                stale |= now - _time(last_item) > expected + policy.item_grace_seconds
        if stale:
            document.update(
                state="stale",
                next_safe_action="review-source-freshness",
                diagnostic_code="REVIEWED_CADENCE_OVERDUE",
            )
        elif document["state"] == "stale":
            document.update(
                state="quiet",
                accepted_items=0,
                next_safe_action="wait-for-approved-poll",
                diagnostic_code=None,
            )
    validate_record("health", document)
    incident = None
    episode_at = None
    if document["state"] not in {"healthy", "quiet", "never_fetched", "paused"}:
        episode_at = observed_at
        if (
            old
            and previous
            and old["state"] == document["state"]
            and old["policy_ref"] == document["policy_ref"]
        ):
            episode_at = previous.incident_episode_at or observed_at
    if (
        policy
        and (
            document["state"] == "stale"
            or document["consecutive_failures"] >= policy.failure_threshold
        )
        and document["state"] != "paused"
    ):
        incident = identity_hash(
            {
                "source_id": source["source_id"],
                "registry_version": source["registry_version"],
                "policy_ref": policy.policy_ref,
                "state": document["state"],
                "episode_at": episode_at,
            }
        )
    return HealthResult(
        HealthHistory(document, seen, identity_hash(source), incident_episode_at=episode_at),
        source["state"],
        dict(source["cadence"]),
        incident,
        policy.escalation_owner if incident and policy else None,
        bool(
            old
            and old["state"] not in {"healthy", "quiet", "never_fetched", "paused"}
            and document["state"] in {"healthy", "quiet"}
        ),
    )


def health_from_run(
    source: dict[str, Any],
    state: RunState,
    *,
    observed_at: str,
    source_context: dict[str, Any] | None = None,
    items: tuple[dict[str, Any], ...] = (),
    previous: HealthHistory | None = None,
    policy: HealthPolicy | None = None,
    policy_allowed: Callable[[HealthPolicy], bool] | None = None,
) -> HealthResult:
    """Adapt existing orchestrator checkpoints and atomic intelligence receipts.

    Terminal load receipts are evidence, not planned/dry-run row counts. A failed
    later stage preserves accepted load evidence separately from its failure.
    Call only against durable checkpoints and the matching retained payload.
    """
    if state.dry_run or state.resource_key != source["source_id"]:
        raise ValueError("INTELLIGENCE_HEALTH_RUN_MISMATCH")
    failed = next(
        (checkpoint for checkpoint in state.stages if checkpoint.status is StageStatus.FAILED), None
    )
    load = state.checkpoint(Stage.LOAD)
    terminal = failed or load
    if terminal is None or terminal.status not in {StageStatus.FAILED, StageStatus.COMPLETED}:
        raise ValueError("INTELLIGENCE_HEALTH_TERMINAL_EVIDENCE_REQUIRED")
    key = identity_hash(
        {
            "run": state.ingestion_run_id,
            "stage": terminal.stage.value,
            "attempt": terminal.attempt_count,
            "status": terminal.status.value,
        }
    )
    evidence_hash = identity_hash(
        {
            "source_context": source_context,
            "items": items,
            "load_receipt": load.detail if load else None,
            "diagnostic": failed.redacted_diagnostic_code if failed else None,
            "category": failed.failure_category.value
            if failed and failed.failure_category
            else None,
        }
    )
    if previous and previous.attempt_key == key and previous.attempt_input_sha256 != evidence_hash:
        raise ValueError("INTELLIGENCE_HEALTH_ATTEMPT_CONFLICT")
    options: dict[str, Any] = {}
    if not previous or previous.attempt_key != key:
        if load and load.status is StageStatus.COMPLETED:
            if load.detail.get("mode") != "atomic_intelligence" or source_context is None:
                raise ValueError("INTELLIGENCE_HEALTH_STORAGE_RECEIPT_REQUIRED")
            validate_acquisition_context(
                source, state.resource_key, source["fetch_location"], source_context
            )
            acquire = state.checkpoint(Stage.ACQUIRE)
            if acquire is None or acquire.artifact_sha256 != source_context["artifact_sha256"]:
                raise ValueError("INTELLIGENCE_HEALTH_CAPTURE_MISMATCH")
            for item in items:
                if (
                    item["provenance"]["run_id"] != state.ingestion_run_id
                    or item["provenance"]["artifact_id"] != acquire.artifact_id
                    or item["provenance"]["artifact_sha256"] != acquire.artifact_sha256
                ):
                    raise ValueError("INTELLIGENCE_HEALTH_CAPTURE_MISMATCH")
            for field in ("revisions_inserted", "captures_inserted", "captures_replayed"):
                if type(load.detail.get(field)) is not int:
                    raise ValueError("INTELLIGENCE_HEALTH_INVALID_RECEIPT")
            options = {
                "outcome": "success",
                "fetched_at": source_context["fetched_at"],
                "items": items,
                "receipt": WriteReceipt(
                    load.detail["revisions_inserted"],
                    load.detail["captures_inserted"],
                    load.detail["captures_replayed"],
                ),
            }
        elif failed:
            code = failed.redacted_diagnostic_code
            mapping: dict[str, Outcome] = {
                "MALFORMED_FEED": "malformed",
                "UNSUPPORTED_FEED_ENVELOPE": "parser_drift",
                "AMBIGUOUS_FEED_FIELD": "parser_drift",
                "XML_BASE_INVALID": "parser_drift",
                "FEED_RATE_LIMITED": "rate_limited",
                "FEED_ACCESS_FAILED": "access_expired",
            }
            outcome: Outcome = mapping.get(code or "", "upstream_outage")
            if failed.failure_category in {
                FailureCategory.POLICY_LICENSE,
                FailureCategory.PERMISSION,
                FailureCategory.CONFIGURATION,
            }:
                outcome = "policy_blocked"
            elif failed.stage is Stage.LOAD:
                outcome = "storage_failed"
            elif failed.stage in {Stage.VALIDATE, Stage.NORMALIZE} and code not in mapping:
                outcome = "parser_drift"
            options = {"outcome": outcome}
    result = reduce_health(
        source,
        observed_at=observed_at,
        previous=previous,
        policy=policy,
        policy_allowed=policy_allowed,
        **options,
    )
    if (
        failed
        and load
        and load.status is StageStatus.COMPLETED
        and (not previous or previous.attempt_key != key)
    ):
        result = reduce_health(
            source,
            observed_at=observed_at,
            previous=result.history,
            outcome="storage_failed",
            policy=policy,
            policy_allowed=policy_allowed,
        )
    return replace(
        result,
        history=replace(
            result.history,
            attempt_key=key,
            attempt_input_sha256=evidence_hash,
        ),
    )


def record_health(result: HealthResult, emit: Callable[[dict[str, Any]], None]) -> bool:
    """Existing telemetry seam; outage never changes the primary source result.

    Event contains only finite metadata. No publisher text, addresses, URLs,
    exception strings or item identities are sent. Incident descriptors are
    deduplication suggestions, not permission to send alerts.
    """
    document = result.history.document
    event = {
        "event": "intelligence_source_health",
        "source_id": document["source_id"],
        "registry_version": document["registry_version"],
        "state": document["state"],
        "diagnostic_code": document["diagnostic_code"],
        "consecutive_failures": document["consecutive_failures"],
        "accepted_items": document["accepted_items"],
        "rejected_items": document["rejected_items"],
        "incident_key": result.incident_key,
    }
    try:
        emit(event)
    except Exception:
        return False
    return True
