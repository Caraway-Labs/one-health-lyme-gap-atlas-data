"""Complete oversized feed handling; fixtures never admit a production source."""

import json
from pathlib import Path

import pytest
from test_intelligence_feed import approved, definition

from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError
from lyme_gap_atlas_data.ingestion.intelligence_feed import (
    acquisition_context,
)
from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    RECEIPTS,
    FeedPassBounds,
    PilotFeedAdapter,
    compose_pilot,
)
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.intelligence_items import identity_hash, validate_record
from lyme_gap_atlas_data.intelligence_metadata import NativeMetadataPolicy, inventory_feed
from lyme_gap_atlas_data.settings import PipelineSettings


def captured(count: int):
    import base64
    import hashlib

    source = approved()
    source["limits"].update(maximum_items=3000, maximum_bytes=2097152)
    source["access_use"].update(public_excerpt_permitted=False, excerpt_max_chars=0)
    configured = definition(source)
    entries = "".join(
        f"<item><guid>{n}</guid><title>Publication {n}</title>"
        f"<link>https://example.org/article/{n}</link>"
        "<pubDate>Wed, 21 Oct 2026 00:00:00 GMT</pubDate></item>"
        for n in range(count)
    )
    raw = f'<rss version="2.0"><channel>{entries}</channel></rss>'.encode()
    digest = hashlib.sha256(raw).hexdigest()
    payload = {
        "xml_base64": base64.b64encode(raw).decode(),
        "artifact_sha256": digest,
        "fetched_at": "2026-10-22T00:00:00Z",
        "source_context": acquisition_context(
            configured,
            source,
            effective_url=configured.endpoint_template,
            fetched_at="2026-10-22T00:00:00Z",
            artifact_sha256=digest,
            capture_mode="fixture",
        ),
        "_acquisition_lineage": {"ingestion_run_id": "fixture-run", "artifact_id": "fixture"},
    }
    return configured, payload


def test_extended_pass_preserves_every_item_and_last_link():
    configured, payload = captured(2343)
    adapter = PilotFeedAdapter(pass_bounds=FeedPassBounds(3000, 10_000_000))
    records = adapter.normalize(configured, payload).records
    assert len(records) == 2343
    assert records[-1]["canonical_url"] == "https://example.org/article/2342"
    assert all(record["excerpt"] is None for record in records)


def test_extended_native_v2_pass_preserves_repeat_and_revision_identity():
    import base64
    import hashlib

    configured, payload = captured(251)
    source = configured.extra["intelligence_registry"]
    raw = base64.b64decode(payload["xml_base64"])
    inventory = frozenset(inventory_feed(raw, source))
    policy = NativeMetadataPolicy(
        policy_ref="fixture-only",
        source_sha256=identity_hash(source),
        inventory=inventory,
        permitted_paths=frozenset({"item/link", "item/pubDate", "item/title"}),
        published_path="item/pubDate",
        published_format="rfc822",
    )
    adapter = PilotFeedAdapter(
        pass_bounds=FeedPassBounds(3000, 10_000_000),
        native_policy_lookup=lambda *_: policy,
    )
    original = adapter.normalize(configured, payload).records
    assert len(original) == 251
    assert all(item["contract_version"] == "2.0.0" for item in original)
    assert adapter.normalize(configured, payload).records == original
    changed = raw.replace(b"Publication 250", b"Corrected publication 250")
    payload["xml_base64"] = base64.b64encode(changed).decode()
    payload["artifact_sha256"] = hashlib.sha256(changed).hexdigest()
    payload["source_context"]["artifact_sha256"] = payload["artifact_sha256"]
    revised = adapter.normalize(configured, payload).records
    assert original[-1]["item_id"] == revised[-1]["item_id"]
    assert original[-1]["revision_id"] != revised[-1]["revision_id"]
    assert all(
        before["revision_id"] == after["revision_id"]
        for before, after in zip(original[:-1], revised[:-1], strict=True)
    )


def test_complete_large_native_fixture_needs_explicit_extended_byte_bound():
    """Real feed field structure, synthetic entries; never a live admission."""
    import base64
    import hashlib
    import xml.etree.ElementTree as ET

    from test_intelligence_real_feed_metadata import _element

    configured, payload = captured(2343)
    source = configured.extra["intelligence_registry"]
    packet = json.loads(
        (Path(__file__).parent / "fixtures/intelligence/native-captures/cdc-mmwr.json").read_text()
    )
    root = ET.fromstring(base64.b64decode(payload["xml_base64"]))
    channel = root.find("channel")
    assert channel is not None
    for node in packet["samples"][0]["native_metadata"]["feed"]:
        channel.insert(0, _element(node))
    raw = ET.tostring(root)
    payload["xml_base64"] = base64.b64encode(raw).decode()
    payload["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    payload["source_context"]["artifact_sha256"] = payload["artifact_sha256"]
    policy = NativeMetadataPolicy(
        policy_ref="synthetic-large-fixture-only",
        source_sha256=identity_hash(source),
        inventory=frozenset(inventory_feed(raw, source)),
        permitted_paths=frozenset(
            {"feed/language", "feed/link", "feed/title", "item/link", "item/pubDate", "item/title"}
        ),
        published_path="item/pubDate",
        published_format="rfc822",
    )
    adapter = PilotFeedAdapter(
        pass_bounds=FeedPassBounds(3000, 32_000_000), native_policy_lookup=lambda *_: policy
    )
    records = adapter.normalize(configured, payload).records
    size = len(json.dumps(records).encode())
    assert 10_000_000 < size <= 32_000_000
    assert len(records) == 2343
    assert records[-1]["canonical_url"] == "https://example.org/article/2342"
    assert all(
        row["excerpt"] is None and row["publisher_metadata"]["media"] == [] for row in records
    )
    with pytest.raises(PermissionError, match="PILOT_NORMALIZED_LIMIT"):
        PilotFeedAdapter(
            pass_bounds=FeedPassBounds(3000, 10_000_000), native_policy_lookup=lambda *_: policy
        ).normalize(configured, payload)


def test_existing_pilot_still_rejects_the_complete_oversized_feed():
    configured, payload = captured(251)
    with pytest.raises(PermissionError, match="PILOT_ITEM_LIMIT"):
        PilotFeedAdapter().normalize(configured, payload)


def test_registry_limit_still_rejects_before_normalization():
    configured, payload = captured(3001)
    with pytest.raises(AcquisitionError, match="FEED_ITEM_LIMIT"):
        PilotFeedAdapter(pass_bounds=FeedPassBounds(3000, 10_000_000)).normalize(
            configured, payload
        )


def test_normalized_byte_limit_rejects_whole_capture():
    configured, payload = captured(2)
    adapter = PilotFeedAdapter(pass_bounds=FeedPassBounds(3000, 1))
    with pytest.raises(PermissionError, match="PILOT_NORMALIZED_LIMIT"):
        adapter.normalize(configured, payload)


@pytest.mark.parametrize("items,size", [(0, 1), (5001, 1), (True, 1), (1, 32_000_001)])
def test_bounds_cannot_exceed_existing_storage_envelope(items, size):
    with pytest.raises(ValueError, match="PASS_BOUNDS_INVALID"):
        FeedPassBounds(items, size)


def test_expanded_dev_bounds_cannot_enter_existing_production_package():
    configured, _ = captured(1)

    def forbidden():
        pytest.fail("Expanded PROD bounds must fail before credentials or database I/O")

    with pytest.raises(PermissionError, match="PROD_EXPANDED_BOUNDS_NOT_ADMITTED"):
        compose_pilot(
            configured,
            receipts=[],
            connection_factory=forbidden,
            settings=PipelineSettings(
                topx_env="prod",
                snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                enable_production_execution=True,
            ),
            pass_bounds=FeedPassBounds(3000, 10_000_000),
        )


@pytest.mark.parametrize("source_id", ["cdc-mmwr", "cdc-newsroom"])
def test_real_cdc_proposals_are_exact_but_cannot_self_admit(source_id):
    root = Path(__file__).parents[1]
    directory = root / "config/intelligence/proposed-five-feeds"
    source = json.loads((directory / f"{source_id}-source-v1.json").read_text())
    proposal = json.loads((directory / f"{source_id}-native-policy-proposal.json").read_text())
    validate_record("source", source)
    assert source["state"] == "candidate"
    assert source["topics"] == source["geographies"] == []
    for key in ("approval", "trust_review"):
        assert source[key]["status"] == "pending"
        assert source[key]["decision_ref"] is None
    assert source["limits"] == {
        "maximum_bytes": 2097152,
        "timeout_seconds": 30,
        "maximum_items": 3000,
        "maximum_redirects": 0,
        "maximum_attempts": 1,
    }
    assert proposal["status"] == "proposed-not-an-approval"
    assert proposal["proposed_pass_bounds"] == {
        "maximum_items": 3000,
        "maximum_normalized_bytes": 32_000_000,
    }
    assert proposal["source_sha256"] == identity_hash(source)
    document = proposal["native_policy"]
    policy = NativeMetadataPolicy(
        **{
            **document,
            **{
                key: frozenset(document[key])
                for key in ("inventory", "permitted_paths", "required_paths")
            },
        }
    )
    policy.validate(source)
    assert policy.permitted_paths == frozenset(
        {
            "feed/language",
            "feed/link",
            "feed/title",
            "item/link",
            "item/pubDate",
            "item/title",
            "item/description",
            "item/category",
        }
    )
    assert proposal["endpoint_evidence"]["status"] == 200
    assert proposal["endpoint_evidence"]["raw_retained"] is False
    configured = load_source_definition(
        root / f"config/sources/intelligence_{source_id.replace('-', '_')}.yml"
    )
    assert configured.artifact_policy == "REVIEW_REQUIRED"
    assert configured.endpoint_template == source["fetch_location"]

    def forbidden():
        pytest.fail("A proposed package must not access credentials or the registry")

    with pytest.raises(PermissionError, match="REVIEWED_POLICY_REQUIRED"):
        compose_pilot(
            configured,
            receipts=json.loads((root / RECEIPTS).read_text())["receipts"],
            connection_factory=forbidden,
            settings=PipelineSettings(),
            pass_bounds=FeedPassBounds(3000, 10_000_000),
        )
