"""Health outcomes against accepted source/items and actual orchestration seams."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from test_intelligence_feed import approved
from test_intelligence_storage import item

from lyme_gap_atlas_data.intelligence_health import (
    HealthHistory,
    HealthPolicy,
    health_from_run,
    record_health,
    reduce_health,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash, validate_record
from lyme_gap_atlas_data.intelligence_storage import WriteReceipt

NOW = "2026-10-01T00:00:00Z"


def success(
    source: dict[str, Any],
    previous: HealthHistory | None = None,
    fetched: str = NOW,
    records: tuple[dict[str, Any], ...] | None = None,
) -> Any:
    rows = records if records is not None else (item(source, fetched_at=fetched),)
    return reduce_health(
        source,
        observed_at=fetched,
        fetched_at=fetched,
        outcome="success",
        items=rows,
        receipt=WriteReceipt(0, len(rows), 0),
        previous=previous,
    )


def policy(source: dict[str, Any], **changes: Any) -> HealthPolicy:
    values = dict(
        policy_ref="synthetic-reviewed-health-v1",
        source_sha256=identity_hash(source),
        escalation_owner="synthetic-owner",
        fetch_grace_seconds=60,
        item_grace_seconds=None,
        failure_threshold=2,
    )
    values.update(changes)
    return HealthPolicy(**values)


def test_global_zero_revision_inserts_is_still_first_source_observation_then_repoll_is_quiet() -> (
    None
):
    source = approved()
    first = success(source)
    assert first.history.document["state"] == "healthy"
    second = success(source, first.history, fetched="2026-10-01T01:00:00Z")
    assert second.history.document["state"] == "quiet"
    assert second.history.document["last_item_observed_at"] == NOW
    assert second.history.document["last_fetch_success_at"] == "2026-10-01T01:00:00Z"
    assert second.history.document["accepted_items"] == 0
    assert first.history.document["last_fetch_success_at"] == NOW
    validate_record("health", second.history.document)


def test_empty_success_304_style_retained_poll_is_quiet_not_broken() -> None:
    result = success(approved(), records=())
    assert result.history.document["state"] == "quiet"
    assert result.history.document["last_item_observed_at"] is None
    assert result.history.document["coverage_end_at"] is None


@pytest.mark.parametrize(
    "outcome,state,category",
    [
        ("parser_drift", "parser_drift", "parser"),
        ("malformed", "malformed", "parser"),
        ("access_expired", "access_expired", "fetch"),
        ("rate_limited", "rate_limited", "fetch"),
        ("upstream_outage", "upstream_outage", "fetch"),
        ("policy_blocked", "access_expired", "policy"),
        ("storage_failed", "partial", "storage"),
    ],
)
def test_failures_keep_last_good_item_and_capture_chronology(
    outcome: Any, state: str, category: str
) -> None:
    source = approved()
    good = success(source)
    failure = reduce_health(
        source, previous=good.history, observed_at="2026-10-02T00:00:00Z", outcome=outcome
    )
    assert failure.history.document["state"] == state
    assert failure.history.document["failure_category"] == category
    assert failure.history.document["consecutive_failures"] == 1
    for field in (
        "last_item_observed_at",
        "last_fetch_success_at",
        "coverage_start_at",
        "coverage_end_at",
    ):
        assert failure.history.document[field] == good.history.document[field]
    recovered = success(source, failure.history, fetched="2026-10-02T01:00:00Z")
    assert recovered.recovered and recovered.history.document["state"] == "quiet"
    assert recovered.history.document["consecutive_failures"] == 0


def test_reviewed_poll_threshold_is_exact_and_preserves_submicrosecond_boundary() -> None:
    source = approved()
    source["state"] = "active"
    source["cadence"]["poll_seconds"] = 3600
    good = success(source)
    reviewed = policy(source)
    exact = reduce_health(
        source,
        previous=good.history,
        observed_at="2026-10-01T01:01:00Z",
        policy=reviewed,
        policy_allowed=lambda value: True,
    )
    assert exact.history.document["state"] == "healthy"
    overdue = reduce_health(
        source,
        previous=good.history,
        observed_at="2026-10-01T01:01:00.00000000000000000000000001Z",
        policy=reviewed,
        policy_allowed=lambda value: True,
    )
    assert overdue.history.document["state"] == "stale" and overdue.incident_key
    assert overdue.escalation_owner == "synthetic-owner"
    assert overdue.history.document["last_fetch_success_at"] == NOW


def test_unknown_publication_cadence_and_manual_poll_do_not_invent_staleness() -> None:
    source = approved()
    good = success(source)
    result = reduce_health(
        source,
        previous=good.history,
        observed_at="2027-10-01T00:00:00Z",
        policy=policy(source),
        policy_allowed=lambda value: True,
    )
    assert result.history.document["state"] == "healthy"
    assert result.source_state == "manual" and result.incident_key is None


def test_reviewed_item_gap_can_be_stale_despite_successful_quiet_fetch() -> None:
    source = approved()
    source["cadence"].update(expected_item_seconds=3600, basis="reviewed_observation")
    good = success(source)
    quiet = success(source, good.history, fetched="2026-10-01T02:00:00Z")
    result = reduce_health(
        source,
        previous=quiet.history,
        observed_at="2026-10-01T02:00:00Z",
        policy=policy(source, item_grace_seconds=0),
        policy_allowed=lambda value: True,
    )
    assert result.history.document["state"] == "stale"
    assert result.history.document["last_fetch_success_at"] == "2026-10-01T02:00:00Z"


def test_partial_rejections_are_failure_not_a_quiet_poll() -> None:
    source = approved()
    rows = (item(source),)
    result = reduce_health(
        source,
        observed_at=NOW,
        fetched_at=NOW,
        outcome="partial",
        items=rows,
        receipt=WriteReceipt(0, 1, 0),
        rejected_items=2,
    )
    assert result.history.document["state"] == "partial"
    assert result.history.document["accepted_items"] == 1
    assert result.history.document["rejected_items"] == 2


def test_repeated_failures_have_stable_dedup_descriptor_until_recovery() -> None:
    source = approved()
    good = success(source)
    options = dict(policy=policy(source), policy_allowed=lambda value: True, outcome="rate_limited")
    one = reduce_health(
        source, previous=good.history, observed_at="2026-10-01T01:00:00Z", **options
    )
    two = reduce_health(source, previous=one.history, observed_at="2026-10-01T02:00:00Z", **options)
    three = reduce_health(
        source, previous=two.history, observed_at="2026-10-01T03:00:00Z", **options
    )
    assert one.incident_key is None
    assert two.incident_key == three.incident_key
    assert three.history.document["consecutive_failures"] == 3


def test_telemetry_outage_is_redacted_and_does_not_replace_primary_health() -> None:
    result = success(approved())
    before = copy.deepcopy(result.history.document)
    events = []

    def unavailable(event: dict[str, Any]) -> None:
        events.append(event)
        raise RuntimeError("private mail, provider credential and message content")

    assert record_health(result, unavailable) is False
    assert result.history.document == before
    assert not any(key in str(events) for key in ("credential", "excerpt", "title", "fetched_at"))
    assert record_health(result, lambda event: None) is True


@pytest.mark.parametrize("change", [{"registry_version": 2}, {"topics": ["changed"]}])
def test_history_cannot_be_relabelled_under_another_source_version_or_policy(
    change: dict[str, Any],
) -> None:
    source = approved()
    good = success(source)
    with pytest.raises(ValueError, match="HISTORY_MISMATCH"):
        reduce_health({**source, **change}, previous=good.history, observed_at=NOW)


def test_policy_must_be_explicitly_reviewed_and_exactly_bound_to_source() -> None:
    source = approved()
    with pytest.raises(PermissionError, match="NOT_REVIEWED"):
        reduce_health(source, observed_at=NOW, policy=policy(source))
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        reduce_health(source, observed_at=NOW, policy=policy(source, source_sha256="a" * 64))


def test_inactive_source_is_paused_without_health_evidence_becoming_approval() -> None:
    source = approved()
    source["state"] = "paused"
    result = reduce_health(source, observed_at=NOW, outcome="success")
    assert result.history.document["state"] == "paused"
    assert result.history.document["last_fetch_success_at"] is None


def test_invalid_receipt_or_future_observation_cannot_claim_success() -> None:
    source = approved()
    with pytest.raises(ValueError, match="INVALID_RECEIPT"):
        reduce_health(
            source,
            observed_at=NOW,
            fetched_at=NOW,
            outcome="success",
            items=(item(source),),
            receipt=WriteReceipt(0, 0, 0),
        )
    with pytest.raises(ValueError, match="FETCH_TIME_INVALID"):
        reduce_health(
            source,
            observed_at=NOW,
            fetched_at="2026-10-02T00:00:00Z",
            outcome="success",
            receipt=WriteReceipt(0, 0, 0),
        )


def test_real_orchestrator_effects_store_receipt_health_and_resume_are_consistent(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from test_intelligence_feed import FIXTURES, definition, fetch_adapter
    from test_intelligence_recovery import AcquisitionLedger, FailingCheckpoints, Objects

    from lyme_gap_atlas_data.ingestion import IngestionOrchestrator, Tier
    from lyme_gap_atlas_data.ingestion.intelligence_effects import IntelligenceStageEffects
    from lyme_gap_atlas_data.ingestion.intelligence_feed import FeedResponse

    database = AcquisitionLedger()
    source = database.sources[0]
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, calls = fetch_adapter(source, [FeedResponse(200, {}, raw)])
    original_acquire = adapter.acquire
    adapter.acquire = lambda selected, **kwargs: original_acquire(selected)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2026, 10, 1, tzinfo=UTC)

    monkeypatch.setattr("lyme_gap_atlas_data.ingestion.intelligence_feed.datetime", Clock)
    checkpoints = FailingCheckpoints(tmp_path, database, "")
    effects = IntelligenceStageEffects(
        connection_factory=database.connect,
        spaces_client=Objects(),
        retention_allowed=lambda ref: True,
        artifact_policy_allowed=lambda ref, value: True,
    )
    orchestrator = IngestionOrchestrator(
        store=checkpoints, adapter=adapter, fixture_dir=FIXTURES / "rss", effects=effects
    )
    state = orchestrator.run(definition(source), tier=Tier.A)
    assert state.status.value == "SUCCEEDED"
    rows = tuple(checkpoints.load_normalized(state.ingestion_run_id))
    context = checkpoints.load_payload(state.ingestion_run_id)["source_context"]
    first = health_from_run(source, state, observed_at=NOW, items=rows, source_context=context)
    assert first.history.document["state"] == "healthy"
    assert first.history.document["accepted_items"] == len(rows)
    resumed = orchestrator.resume(state.ingestion_run_id, definition=definition(source))
    replay = health_from_run(
        source,
        resumed,
        observed_at="2026-10-01T01:00:00Z",
        items=rows,
        source_context=context,
        previous=first.history,
    )
    assert len(calls) == 1
    assert replay.history.seen_revisions == first.history.seen_revisions
    assert replay.history.document["last_fetch_success_at"] == NOW
    assert replay.history.document["last_item_observed_at"] == NOW
    assert replay.history.document["consecutive_failures"] == 0
    from lyme_gap_atlas_data.ingestion.types import FailureCategory, Stage, StageStatus

    quality = resumed.checkpoint(Stage.QUALITY)
    assert quality is not None
    quality.status = StageStatus.FAILED
    quality.attempt_count = 1
    quality.failure_category = FailureCategory.QUALITY
    quality.redacted_diagnostic_code = "QUALITY_FAILED"
    reviewed = policy(source)
    partial = health_from_run(
        source,
        resumed,
        observed_at="2026-10-01T01:00:00Z",
        items=rows,
        source_context=context,
        previous=replay.history,
        policy=reviewed,
        policy_allowed=lambda value: True,
    )
    quality.attempt_count = 2
    repeated = health_from_run(
        source,
        resumed,
        observed_at="2026-10-01T02:00:00Z",
        items=rows,
        source_context=context,
        previous=partial.history,
        policy=reviewed,
        policy_allowed=lambda value: True,
    )
    assert repeated.history.document["state"] == "partial"
    assert repeated.history.document["consecutive_failures"] == 2
    assert repeated.history.document["last_fetch_success_at"] == NOW
    assert repeated.history.seen_revisions == first.history.seen_revisions
    assert repeated.incident_key


def test_actual_failed_checkpoint_redacts_and_replay_does_not_count_a_new_attempt() -> None:
    from lyme_gap_atlas_data.ingestion.types import (
        FailureCategory,
        RunState,
        RunStatus,
        Stage,
        StageCheckpoint,
        StageStatus,
        Tier,
    )

    source = approved()
    failed = StageCheckpoint(
        stage=Stage.VALIDATE,
        status=StageStatus.FAILED,
        attempt_count=1,
        failure_category=FailureCategory.SCHEMA,
        redacted_diagnostic_code="UNSUPPORTED_FEED_ENVELOPE",
    )
    state = RunState("synthetic-run", source["source_id"], 1, Tier.A, RunStatus.FAILED, [failed])
    first = health_from_run(source, state, observed_at=NOW)
    replay = health_from_run(
        source, state, observed_at="2026-10-01T01:00:00Z", previous=first.history
    )
    assert replay.history.document["state"] == "parser_drift"
    assert replay.history.document["consecutive_failures"] == 1
    failed.attempt_count += 1
    again = health_from_run(
        source, state, observed_at="2026-10-01T02:00:00Z", previous=replay.history
    )
    assert again.history.document["consecutive_failures"] == 2


def test_delayed_item_preserves_publisher_date_and_observes_current_capture_only() -> None:
    source = approved()
    delayed = item(source, published_at="2020-01-01T00:00:00Z")
    before = copy.deepcopy(delayed)
    result = success(source, records=(delayed,))
    assert result.history.document["last_item_observed_at"] == NOW
    assert delayed == before and delayed["published_at"] == "2020-01-01T00:00:00Z"


def test_recovered_new_failure_episode_gets_a_new_incident_descriptor() -> None:
    source = approved()
    reviewed = policy(source, failure_threshold=1)
    first = reduce_health(
        source,
        observed_at=NOW,
        outcome="upstream_outage",
        policy=reviewed,
        policy_allowed=lambda value: True,
    )
    recovered = success(source, first.history, fetched="2026-10-01T01:00:00Z")
    second = reduce_health(
        source,
        previous=recovered.history,
        observed_at="2026-10-01T02:00:00Z",
        outcome="upstream_outage",
        policy=reviewed,
        policy_allowed=lambda value: True,
    )
    assert first.incident_key and second.incident_key and first.incident_key != second.incident_key


def test_same_checkpoint_changed_failure_evidence_is_a_conflict() -> None:
    from lyme_gap_atlas_data.ingestion.types import (
        FailureCategory,
        RunState,
        RunStatus,
        Stage,
        StageCheckpoint,
        StageStatus,
        Tier,
    )

    source = approved()
    failed = StageCheckpoint(
        stage=Stage.ACQUIRE,
        status=StageStatus.FAILED,
        attempt_count=1,
        failure_category=FailureCategory.ACQUISITION,
        redacted_diagnostic_code="FEED_RATE_LIMITED",
    )
    state = RunState("synthetic-run", source["source_id"], 1, Tier.A, RunStatus.FAILED, [failed])
    first = health_from_run(source, state, observed_at=NOW)
    failed.redacted_diagnostic_code = "FEED_ACCESS_FAILED"
    with pytest.raises(ValueError, match="ATTEMPT_CONFLICT"):
        health_from_run(source, state, observed_at=NOW, previous=first.history)
