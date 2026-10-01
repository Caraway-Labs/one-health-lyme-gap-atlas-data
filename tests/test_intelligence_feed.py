"""Independent RSS/Atom, network-policy and shared-orchestration examples."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from lyme_gap_atlas_data.ingestion import (
    FileCheckpointStore,
    IngestionOrchestrator,
    InMemoryCheckpointStore,
    Stage,
    Tier,
)
from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError, get_adapter
from lyme_gap_atlas_data.ingestion.intelligence_feed import (
    FeedCache,
    FeedResponse,
    IntelligenceFeedAdapter,
    parse_feed,
)
from lyme_gap_atlas_data.ingestion.types import AdapterKind, SourceDefinition
from lyme_gap_atlas_data.intelligence_items import identity_hash

FIXTURES = Path(__file__).parent / "fixtures/intelligence"


def source(transport: str = "rss", family: str = "cdc_mmwr") -> dict[str, Any]:
    record = json.loads((FIXTURES / "v1/candidate-source.json").read_text())
    record.update(transport=transport, family=family)
    record["access_use"].update(public_excerpt_permitted=True, excerpt_max_chars=100)
    return record


def definition(record: dict[str, Any]) -> SourceDefinition:
    return SourceDefinition(
        resource_key=record["source_id"],
        definition_version=1,
        adapter_kind=AdapterKind.RSS_ATOM,
        endpoint_template="https://example.org/feed.xml",
        deterministic_order_clause="publisher_document_order",
        incremental_strategy="CONTENT_REVISION",
        geography_semantics="Publication; no inferred geography",
        temporal_semantics="Publisher chronology; missing remains unknown",
        destination="PRESENTATION.INTELLIGENCE_FEED_V",
        quality_rules=(),
        extra={"intelligence_registry": record},
    )


def approved() -> dict[str, Any]:
    """In-memory simulation of a steward record, never a configured live source."""
    record = source()
    record.update(
        state="manual",
        trust_classification="official_public_health",
        canonical_location="https://example.org/",
        fetch_location="https://example.org/feed.xml",
        approved_hosts=["example.org"],
    )
    for review in ("approval", "trust_review"):
        record[review].update(
            status="approved",
            decision_ref="synthetic-test-review",
            reviewed_at="2026-09-30T00:00:00Z",
        )
    record["access_use"].update(
        terms_location="https://example.org/terms",
        availability_verified_at="2026-09-30T00:00:00Z",
        content_retention_policy_ref="synthetic-test-policy",
    )
    return record


def normalized(record: dict[str, Any], raw: bytes) -> list[dict[str, Any]]:
    adapter = IntelligenceFeedAdapter()
    import base64
    import hashlib

    payload = {
        "xml_base64": base64.b64encode(raw).decode(),
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "fetched_at": "2026-10-01T01:00:00Z",
        "_acquisition_lineage": {"ingestion_run_id": "local-run", "artifact_id": "local-artifact"},
    }
    return adapter.normalize(definition(record), payload).records


@pytest.mark.parametrize(
    "family,transport", [("cdc_mmwr", "rss"), ("nih_niaid", "atom"), ("pubmed", "rss")]
)
def test_representative_disabled_family_runs_through_shared_orchestrator(
    family: str, transport: str
) -> None:
    record = source(transport, family)
    assert record["state"] == "candidate" and record["approval"]["status"] == "pending"
    store = InMemoryCheckpointStore()
    adapter = get_adapter(AdapterKind.RSS_ATOM)
    orch = IngestionOrchestrator(store=store, adapter=adapter, fixture_dir=FIXTURES / transport)
    run = orch.run(definition(record), tier=Tier.A)
    assert run.status.value == "SUCCEEDED"
    records = store.load_normalized(run.ingestion_run_id)
    assert records and records[0]["provenance"]["run_id"] == run.ingestion_run_id
    assert (
        records[0]["provenance"]["artifact_sha256"] == run.checkpoint(Stage.ACQUIRE).artifact_sha256
    )
    repoll = orch.run(definition(record), tier=Tier.A)
    again = store.load_normalized(repoll.ingestion_run_id)
    assert [(x["item_id"], x["revision_id"]) for x in records] == [
        (x["item_id"], x["revision_id"]) for x in again
    ]
    assert records[0]["provenance"]["run_id"] != again[0]["provenance"]["run_id"]


def test_rss_reissued_guid_dedup_missing_dates_and_markup() -> None:
    items = normalized(source(), (FIXTURES / "rss/sample.xml").read_bytes())
    assert len(items) == 2
    assert items[0]["published_at"] == "2026-09-30T14:00:00Z"
    assert items[0]["excerpt"] == "Permitted summary."
    assert items[1]["published_at"] is None
    assert items[1]["field_states"]["published_at"] == "not_provided"
    assert all(
        x["geographies"] == [] and x["event_at"] is None and x["content_is_untrusted"]
        for x in items
    )
    changed = (
        (FIXTURES / "rss/sample.xml").read_bytes().replace(b"research update", b"corrected update")
    )
    correction = normalized(source(), changed)
    assert correction[0]["item_id"] == items[0]["item_id"]
    assert correction[0]["revision_id"] != items[0]["revision_id"]


def test_atom_precision_xhtml_unknown_chronology() -> None:
    items = normalized(source("atom"), (FIXTURES / "atom/sample.xml").read_bytes())
    assert items[0]["published_at"] == "2026-09-30T14:00:00.123456789Z"
    assert items[0]["updated_at"] == "2026-09-30T14:30:00Z"
    assert items[0]["excerpt"] == "Permitted summary."
    assert items[1]["published_at"] is None
    assert items[1]["field_states"]["published_at"] == "invalid"


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"<rss>", "MALFORMED_FEED"),
        (
            b"<!DOCTYPE rss [<!ENTITY x 'attack'>]><rss version='2.0'><channel/></rss>",
            "XML_DTD_FORBIDDEN",
        ),
        (
            "<!DOCTYPE rss SYSTEM 'file:///secret'><rss version='2.0'><channel/></rss>".encode(
                "utf-16"
            ),
            "XML_DTD_FORBIDDEN",
        ),
        (b"<html/>", "UNSUPPORTED_FEED_ENVELOPE"),
        (b"<rss version='2.0'>" + b"<x>" * 33 + b"</x>" * 33 + b"</rss>", "XML_COMPLEXITY_LIMIT"),
    ],
)
def test_invalid_xml_fails_closed(raw: bytes, code: str) -> None:
    with pytest.raises(AcquisitionError, match=code):
        parse_feed(raw, source())


def test_response_and_item_limits_and_ambiguous_fields() -> None:
    record = source()
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    record["limits"]["maximum_items"] = 1
    with pytest.raises(AcquisitionError, match="FEED_ITEM_LIMIT"):
        parse_feed(raw, record)
    record["limits"]["maximum_bytes"] = 1
    with pytest.raises(AcquisitionError, match="FEED_TOO_LARGE"):
        parse_feed(raw, record)
    with pytest.raises(AcquisitionError, match="AMBIGUOUS_FEED_FIELD"):
        parse_feed(
            b"<rss version='2.0'><channel><item><title>A</title>"
            b"<title>B</title></item></channel></rss>",
            source(),
        )


def test_fixture_resume_preserves_fetch_manifest(tmp_path: Path) -> None:
    store = FileCheckpointStore(tmp_path / "runs")
    record = source()
    orch = IngestionOrchestrator(store=store, fixture_dir=FIXTURES / "rss")
    run = orch.run(definition(record), tier=Tier.A, fail_after_stage="ACQUIRE")
    payload = store.load_payload(run.ingestion_run_id)
    restarted = IngestionOrchestrator(store=store, fixture_dir=FIXTURES / "rss")
    resumed = restarted.resume(run.ingestion_run_id, definition=definition(record))
    assert resumed.status.value == "SUCCEEDED"
    assert store.load_normalized(run.ingestion_run_id)[0]["fetched_at"] == payload["fetched_at"]
    with pytest.raises(AcquisitionError, match="FEED_REPLAY_MANIFEST_REQUIRED"):
        IntelligenceFeedAdapter().restore_raw_payload(definition(record), b"<rss/>")


def test_default_and_forged_registry_and_retention_block_live_before_dns() -> None:
    record = approved()
    with pytest.raises(PermissionError, match="LIVE_APPROVAL_REQUIRED"):
        IntelligenceFeedAdapter().acquire(definition(record))
    for lookup, retention, code in [
        (lambda sid, version: source(), lambda ref: True, "SOURCE_NOT_APPROVED"),
        (lambda sid, version: record, lambda ref: False, "RETENTION_NOT_APPROVED"),
    ]:
        adapter = IntelligenceFeedAdapter(
            registry_lookup=lookup,
            retention_allowed=retention,
            resolve=lambda host, timeout: pytest.fail("must not resolve"),
        )
        with pytest.raises(PermissionError, match=code):
            adapter.acquire(definition(record))


def fetch_adapter(
    record: dict[str, Any], responses: list[FeedResponse], **kwargs: Any
) -> tuple[IntelligenceFeedAdapter, list[Any]]:
    calls: list[Any] = []

    def request(*args: Any) -> FeedResponse:
        calls.append(args)
        return responses.pop(0)

    return IntelligenceFeedAdapter(
        registry_lookup=lambda sid, version: record,
        retention_allowed=lambda ref: True,
        request=request,
        resolve=lambda host, timeout: ("93.184.216.34",),
        **kwargs,
    ), calls


def test_conditional_repoll_retains_real_capture_and_unchanged_revision() -> None:
    record = approved()
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    cache = FeedCache(
        identity_hash(record),
        raw,
        "retained-artifact",
        '"publisher-etag"',
        "Wed, 30 Sep 2026 14:00:00 GMT",
    )
    adapter, calls = fetch_adapter(
        record,
        [FeedResponse(304, {}, b"")],
        cache=cache,
        cache_allowed=lambda saved: saved == cache,
    )
    acquired = adapter.acquire(definition(record))
    assert acquired.raw_payload == raw and acquired.detail["fetch_status"] == 304
    assert calls[0][1] == "93.184.216.34"
    assert calls[0][2]["If-None-Match"] == '"publisher-etag"'
    assert calls[0][2]["If-Modified-Since"] == cache.last_modified
    no_cache, _ = fetch_adapter(record, [FeedResponse(304, {}, b"")])
    with pytest.raises(AcquisitionError, match="304_WITHOUT_CAPTURE"):
        no_cache.acquire(definition(record))


def test_redirect_allowlist_is_checked_before_second_request() -> None:
    record = approved()
    record["limits"]["maximum_redirects"] = 1
    adapter, calls = fetch_adapter(
        record, [FeedResponse(302, {"location": "https://evil.example/feed"}, b"")]
    )
    with pytest.raises(AcquisitionError, match="HOST_NOT_APPROVED"):
        adapter.acquire(definition(record))
    assert len(calls) == 1
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, calls = fetch_adapter(
        record, [FeedResponse(302, {"location": "/new.xml"}, b""), FeedResponse(200, {}, raw)]
    )
    assert adapter.acquire(definition(record)).raw_payload == raw
    assert calls[1][0] == "https://example.org/new.xml"


@pytest.mark.parametrize(
    "addresses", [("127.0.0.1",), ("169.254.169.254",), ("93.184.216.34", "10.0.0.1"), ("::1",)]
)
def test_all_resolved_addresses_must_be_public(addresses: tuple[str, ...]) -> None:
    record = approved()
    adapter, calls = fetch_adapter(record, [])
    adapter.resolve = lambda host, timeout: addresses
    with pytest.raises(AcquisitionError, match="PRIVATE_ADDRESS"):
        adapter.acquire(definition(record))
    assert calls == []


def test_rate_limit_retry_budget_and_retry_after() -> None:
    record = approved()
    record["limits"]["maximum_attempts"] = 2
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    waits: list[float] = []
    adapter, calls = fetch_adapter(
        record,
        [FeedResponse(429, {"retry-after": "2"}, b""), FeedResponse(200, {}, raw)],
        sleep=waits.append,
    )
    adapter.acquire(definition(record))
    assert waits == [2.0] and len(calls) == 2
    adapter, calls = fetch_adapter(
        record, [FeedResponse(503, {}, b""), FeedResponse(503, {}, b"")], sleep=waits.append
    )
    with pytest.raises(AcquisitionError, match="UPSTREAM_FAILED"):
        adapter.acquire(definition(record))
    assert len(calls) == 2
    adapter, calls = fetch_adapter(record, [FeedResponse(429, {"retry-after": "3600"}, b"")])
    with pytest.raises(AcquisitionError, match="RETRY_DEFERRED"):
        adapter.acquire(definition(record))
    assert len(calls) == 1


def test_quiet_is_success_and_auth_failure_is_not_quiet() -> None:
    record = approved()
    adapter, _ = fetch_adapter(
        record, [FeedResponse(200, {}, b"<rss version='2.0'><channel/></rss>")]
    )
    assert adapter.acquire(definition(record)).detail["outcome"] == "quiet"
    adapter, _ = fetch_adapter(record, [FeedResponse(403, {}, b"private provider message")])
    with pytest.raises(AcquisitionError, match="FEED_ACCESS_FAILED") as caught:
        adapter.acquire(definition(record))
    assert "private provider" not in str(caught.value)


def test_cross_feed_attribution_and_conflicting_chronology_remain_separate() -> None:
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    original = normalized(source(), raw)[0]
    other = copy.deepcopy(source())
    other["source_id"] = "other-synthetic-source"
    attributed = normalized(other, raw)[0]
    assert attributed["item_id"] == original["item_id"]
    assert attributed["source_id"] != original["source_id"]
    conflicting = normalized(source(), raw.replace(b"10:00:00 -0400", b"11:00:00 -0400"))[0]
    assert conflicting["item_id"] == original["item_id"]
    assert conflicting["revision_id"] != original["revision_id"]
