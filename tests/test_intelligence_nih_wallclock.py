"""NIH Drupal wall-clock publication times. Recorded fixture only; no live fetch."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_intelligence_recovery import AcquisitionLedger
from test_intelligence_runtime import PilotConnection

from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_metadata import (
    NIH_PUBLISHED_TIMEZONE,
    NativeMetadataPolicy,
    inventory_feed,
    normalize_native_item,
    parse_native_feed,
    parse_nih_drupal_wallclock,
    verify_native_item,
)
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/intelligence/nih-news-releases-live-sample.xml"
PREPARED = ROOT / "config/intelligence/nih-news-releases-settings-receipt-prepared.json"
APPLIED_RECEIPTS = (
    ROOT / "config/intelligence/daily-policy-receipts.json",
    ROOT / "config/intelligence/pilot-policy-receipts.json",
)
RFC822_SOURCES = (
    "cdc-eid-expedited",
    "cdc-eid-ahead-of-print",
    "cdc-outbreaks",
    "cdc-mmwr",
)
# identity_hash of each applied native-policy document. These stay put because
# published_timezone is omitted unless the NIH dialect sets it.
APPLIED_RFC822_NATIVE_POLICY_SHA256 = {
    "config/intelligence/daily-policy-receipts.json": {
        "cdc-eid-expedited": "714a2ee5e03e6803092c1cd10d37e67844a5e90a33f386e3877b12a85b7ee1a5",
        "cdc-eid-ahead-of-print": (
            "0b28ddc533bfd483f993ad032a285b3ab2d0aacaa47192eb3955cd436f50baf9"
        ),
        "cdc-outbreaks": "d70e209bdcfb0692c5b08df7b893b9555ec8613c0c7298f0b1da96ab2758a3ae",
        "cdc-mmwr": "a090d2aff50ad75d36feed3f384106c6df6c247ccaea10e6a6e328278c56d274",
    },
    "config/intelligence/pilot-policy-receipts.json": {
        "cdc-eid-expedited": "4c9eccc9e751aeaf3184653921fd190e65a0a955f5019ec1c67fb985a01e01e7",
        "cdc-eid-ahead-of-print": (
            "25f2c41e9b9f2b2aafefd04a82405a70e73c4af8900b40f9c49fe52863f8eb47"
        ),
        "cdc-outbreaks": "6abda46ddfb5ca89f4f0d0cfbdeb3333a19805679cc87639309b982dd08bd66f",
        "cdc-mmwr": "50c2a1c1f68c39178a7e35c8a4118d3553f77d2ae65ca692c2e32b649a1e7dc3",
    },
}
APPLIED_NIH_NATIVE_POLICY_SHA256 = {
    "config/intelligence/daily-policy-receipts.json": (
        "a27b57db0d84536cc1108b74368cafd3cd8171b39cb15d4fd025a9104e21aaf4"
    ),
    "config/intelligence/pilot-policy-receipts.json": (
        "9b678391edcbccd5aeebf28a362bfb1130eff48c0e88b3e28605f68ba7bf1b8d"
    ),
}


def _source(source_id: str = "nih-news-releases") -> dict:
    return json.loads((ROOT / f"config/intelligence/{source_id}-source-v2.json").read_text())


def _policy(raw: bytes, source: dict, **overrides: object) -> NativeMetadataPolicy:
    fields = frozenset(inventory_feed(raw, source))
    values: dict = {
        "policy_ref": f"{source['source_id']}-native-metadata-v1",
        "source_sha256": identity_hash(source),
        "inventory": fields,
        "permitted_paths": frozenset(
            path for path in fields if "description" not in path and path != "item/source"
        ),
        "published_path": "item/pubDate",
        "published_format": "nih_drupal_wallclock",
        "published_timezone": NIH_PUBLISHED_TIMEZONE,
        "required_paths": frozenset(),
    }
    values.update(overrides)
    if values["published_format"] == "rfc822":
        values["published_timezone"] = None
    return NativeMetadataPolicy(**values)


def _item(pub_date: str, **overrides: object) -> dict:
    source = _source()
    raw = (
        "<rss version='2.0'><channel><title>NIH News Releases</title>"
        "<link>https://www.nih.gov/</link><language>en</language><item>"
        "<title>Example release</title>"
        "<link>https://www.nih.gov/news-events/news-releases/example</link>"
        f"<pubDate>{pub_date}</pubDate></item></channel></rss>"
    ).encode()
    policy = _policy(raw, source, **overrides)
    parsed = parse_native_feed(raw, source, policy)[0]
    item = normalize_native_item(
        source=source,
        transport=source["transport"],
        fetched_at="2026-10-25T16:00:00Z",
        provenance={
            "run_id": "fixture-run",
            "artifact_id": "fixture-artifact",
            "artifact_sha256": "a" * 64,
            "parser_version": "rss-atom-native-v2",
            "fetch_version": "fixture-v1",
        },
        **parsed,
    )
    verify_native_item(item, policy, source)
    return item


@pytest.mark.parametrize(
    ("pub_date", "normalized"),
    [
        ("Fri, 10/23/2026 - 13:00\n", "2026-10-23T17:00:00Z"),
        ("Wed, 01/13/2027 - 13:00", "2027-01-13T18:00:00Z"),
        ("Sun, 11/01/2026 - 00:59", "2026-11-01T04:59:00Z"),
        ("Sun, 11/01/2026 - 02:00", "2026-11-01T07:00:00Z"),
        ("Sun, 03/14/2027 - 03:00", "2027-03-14T07:00:00Z"),
    ],
)
def test_eastern_wall_clock_converts_to_utc(pub_date: str, normalized: str) -> None:
    assert parse_nih_drupal_wallclock(pub_date, NIH_PUBLISHED_TIMEZONE) == normalized
    item = _item(pub_date)
    assert item["published_at"] == normalized
    assert item["field_states"]["published_at"] == "present"
    stored = item["native_metadata"]["publisher_dates"]["published_at"]
    assert stored["raw"] == pub_date
    assert stored["normalized"] == normalized
    assert stored["parser"] == "nih_drupal_wallclock"
    assert item["excerpt"] is None


@pytest.mark.parametrize(
    "pub_date",
    [
        "Sun, 11/01/2026 - 01:30",
        "Sun, 03/14/2027 - 02:30",
        "Thu, 10/23/2026 - 13:00",
        "Fri, 13/01/2026 - 13:00",
        "Fri, 10/23/2026 - 24:00",
        "Fri, 10/23/2026",
        "Fri, 10/23/2026 - 13:00 extra",
    ],
)
def test_ambiguous_missing_and_malformed_wall_clocks_stay_invalid(pub_date: str) -> None:
    assert parse_nih_drupal_wallclock(pub_date, NIH_PUBLISHED_TIMEZONE) is None
    item = _item(pub_date)
    assert item["published_at"] is None
    assert item["field_states"]["published_at"] == "invalid"
    stored = item["native_metadata"]["publisher_dates"]["published_at"]
    assert stored["raw"] == pub_date
    assert stored["normalized"] is None
    assert stored["state"] == "invalid"


def test_rfc822_leaves_the_drupal_wall_clock_invalid() -> None:
    pub_date = "Fri, 10/23/2026 - 13:00"
    item = _item(pub_date, published_format="rfc822")
    assert item["published_at"] is None
    assert item["field_states"]["published_at"] == "invalid"
    assert item["native_metadata"]["publisher_dates"]["published_at"]["raw"] == pub_date


@pytest.mark.parametrize(
    ("source_id", "published_format", "timezone"),
    [
        ("nih-news-releases", "nih_drupal_wallclock", None),
        ("nih-news-releases", "nih_drupal_wallclock", "Not/AZone"),
        ("nih-news-releases", "nih_drupal_wallclock", "US/Eastern"),
        ("nih-news-releases", "nih_drupal_wallclock", "UTC"),
        ("cdc-mmwr", "nih_drupal_wallclock", NIH_PUBLISHED_TIMEZONE),
        ("nih-news-releases", "rfc822", NIH_PUBLISHED_TIMEZONE),
        ("cdc-mmwr", "rfc822", NIH_PUBLISHED_TIMEZONE),
        ("nih-news-releases", "iso8601", NIH_PUBLISHED_TIMEZONE),
    ],
)
def test_settings_reject_the_dialect_outside_nih_eastern(
    source_id: str, published_format: str, timezone: str | None
) -> None:
    source = _source(source_id)
    policy = NativeMetadataPolicy(
        policy_ref=f"{source_id}-native-metadata-v1",
        source_sha256=identity_hash(source),
        inventory=frozenset({"item/pubDate", "item/title"}),
        permitted_paths=frozenset({"item/pubDate", "item/title"}),
        published_path="item/pubDate",
        published_format=published_format,
        published_timezone=timezone,
    )
    with pytest.raises(ValueError, match="INTELLIGENCE_NATIVE_POLICY_INVALID"):
        policy.validate(source)


def test_nih_settings_accept_the_eastern_dialect() -> None:
    source = _source()
    policy = NativeMetadataPolicy(
        policy_ref="nih-news-releases-native-metadata-v1",
        source_sha256=identity_hash(source),
        inventory=frozenset({"item/pubDate", "item/title"}),
        permitted_paths=frozenset({"item/pubDate", "item/title"}),
        published_path="item/pubDate",
        published_format="nih_drupal_wallclock",
        published_timezone=NIH_PUBLISHED_TIMEZONE,
    )
    policy.validate(source)
    document = policy.document()
    assert document["published_format"] == "nih_drupal_wallclock"
    assert document["published_timezone"] == NIH_PUBLISHED_TIMEZONE


def _load_policy(document: dict) -> NativeMetadataPolicy:
    return NativeMetadataPolicy(
        **{
            **document,
            **{
                key: frozenset(document[key])
                for key in ("inventory", "permitted_paths", "required_paths")
            },
        }
    )


def test_applied_rfc822_receipt_hashes_are_unchanged() -> None:
    for path in APPLIED_RECEIPTS:
        receipts = json.loads(path.read_text(encoding="utf-8"))["receipts"]
        for source_id in RFC822_SOURCES:
            native = next(row for row in receipts if row["source_id"] == source_id)["native_policy"]
            assert native["published_format"] == "rfc822"
            assert "published_timezone" not in native
            policy = _load_policy(native)
            expected = APPLIED_RFC822_NATIVE_POLICY_SHA256[path.relative_to(ROOT).as_posix()][
                source_id
            ]
            assert identity_hash(policy.document()) == expected
            assert identity_hash(native) == expected
        nih = next(row for row in receipts if row["source_id"] == "nih-news-releases")
        assert nih["native_policy"]["published_format"] == "rfc822"
        assert "published_timezone" not in nih["native_policy"]
        assert (
            identity_hash(nih["native_policy"])
            == APPLIED_NIH_NATIVE_POLICY_SHA256[path.relative_to(ROOT).as_posix()]
        )


def test_prepared_nih_receipt_is_not_applied() -> None:
    prepared = json.loads(PREPARED.read_text(encoding="utf-8"))
    assert prepared["status"] == "PREPARED_NOT_APPLIED"
    assert prepared["decision"]["decided_on"] == "2026-10-25"
    assert prepared["decision"]["published_timezone"] == NIH_PUBLISHED_TIMEZONE
    native = prepared["receipt"]["native_policy"]
    policy = _load_policy(native)
    assert policy.published_format == "nih_drupal_wallclock"
    assert policy.published_timezone == NIH_PUBLISHED_TIMEZONE
    assert "published_timezone" in policy.document()
    assert identity_hash(policy.document()) == prepared["settings_document_sha256"]
    assert (
        identity_hash(policy.document())
        != APPLIED_NIH_NATIVE_POLICY_SHA256["config/intelligence/daily-policy-receipts.json"]
    )
    assert runtime.DAILY_RECEIPTS.name == "daily-policy-receipts.json"
    assert runtime.RECEIPTS.name == "pilot-policy-receipts.json"
    applied = json.loads(runtime.DAILY_RECEIPTS.read_text(encoding="utf-8"))["receipts"]
    applied_nih = next(row for row in applied if row["source_id"] == "nih-news-releases")
    assert applied_nih["native_policy"]["published_format"] == "rfc822"


def test_live_sample_items_match_the_channel_instant() -> None:
    source = _source()
    raw = FIXTURE.read_bytes()
    observed = inventory_feed(raw, source, base_url=source["fetch_location"])
    prepared = json.loads(PREPARED.read_text(encoding="utf-8"))["receipt"]["native_policy"]
    assert set(observed) <= set(prepared["inventory"])
    policy = _load_policy(prepared)
    assert policy.source_sha256 == identity_hash(source)
    parsed = parse_native_feed(raw, source, policy, base_url=source["fetch_location"])
    items = [
        normalize_native_item(
            source=source,
            transport=source["transport"],
            fetched_at="2026-10-25T16:00:00Z",
            provenance={
                "run_id": "fixture-run",
                "artifact_id": "fixture-artifact",
                "artifact_sha256": "b" * 64,
                "parser_version": "rss-atom-native-v2",
                "fetch_version": "fixture-v1",
            },
            **entry,
        )
        for entry in parsed
    ]
    assert len(items) == 10
    channel = ET.fromstring(raw).findtext("channel/pubDate")
    assert channel is not None
    channel_instant = parsedate_to_datetime(channel).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert channel_instant == "2026-10-23T17:00:00Z"
    assert items[0]["published_at"] == channel_instant
    assert max(item["published_at"] for item in items) == channel_instant
    for item in items:
        assert item["field_states"]["published_at"] == "present"
        assert item["excerpt"] is None
        description = next(
            node for node in item["native_metadata"]["item"] if node["name"] == "description"
        )
        assert description["value"] is None
        assert description["state"] == "withheld"
    verify_native_item(items[0], policy, source)


def _prod_settings() -> PipelineSettings:
    return PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        spaces_bucket="one-health-lyme-gap-atlas-data-prod",
        spaces_prefix="prod",
        spaces_region="sfo3",
        spaces_endpoint="https://sfo3.digitaloceanspaces.com",
    )


def _compose(source_id: str, mutate: Callable[[dict], None]):
    receipts = json.loads((ROOT / "config/intelligence/daily-policy-receipts.json").read_text())[
        "receipts"
    ]
    receipts = json.loads(json.dumps(receipts))
    native = next(row for row in receipts if row["source_id"] == source_id)["native_policy"]
    mutate(native)
    definition = load_source_definition(ROOT / runtime.PROD_SOURCE_DEFINITIONS[source_id])
    return runtime.compose_pilot(
        definition,
        receipts=receipts,
        connection_factory=lambda: pytest.fail("format guard must precede SQL"),
        settings=_prod_settings(),
        registry_version=2,
    )


def test_prod_guard_accepts_applied_rfc822_and_reviewed_nih_dialect() -> None:
    source = _source()
    receipts = json.loads((ROOT / "config/intelligence/daily-policy-receipts.json").read_text())[
        "receipts"
    ]
    definition = load_source_definition(ROOT / runtime.PROD_SOURCE_DEFINITIONS["nih-news-releases"])
    ledger = AcquisitionLedger()
    ledger.database = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    ledger.role = "OH_LYME_PROD_RUNTIME"
    ledger.sources = [source]
    runtime.compose_pilot(
        definition,
        receipts=receipts,
        connection_factory=lambda: PilotConnection(ledger),
        settings=_prod_settings(),
        registry_version=2,
    )
    reviewed = json.loads(json.dumps(receipts))
    native = next(row for row in reviewed if row["source_id"] == "nih-news-releases")[
        "native_policy"
    ]
    native["published_format"] = "nih_drupal_wallclock"
    native["published_timezone"] = NIH_PUBLISHED_TIMEZONE
    runtime.compose_pilot(
        definition,
        receipts=reviewed,
        connection_factory=lambda: PilotConnection(ledger),
        settings=_prod_settings(),
        registry_version=2,
    )
    assert not ledger.requests


@pytest.mark.parametrize("source_id", RFC822_SOURCES)
def test_prod_guard_rejects_non_rfc822_formats_for_other_sources(source_id: str) -> None:
    def mutate(native: dict) -> None:
        native["published_format"] = "nih_drupal_wallclock"
        native["published_timezone"] = NIH_PUBLISHED_TIMEZONE

    with pytest.raises(PermissionError, match="INTELLIGENCE_PROD_NATIVE_POLICY_REQUIRED"):
        _compose(source_id, mutate)


def _iso8601(native: dict) -> None:
    native["published_format"] = "iso8601"


def _dialect_without_zone(native: dict) -> None:
    native["published_format"] = "nih_drupal_wallclock"


def _dialect_with_utc(native: dict) -> None:
    native["published_format"] = "nih_drupal_wallclock"
    native["published_timezone"] = "UTC"


def _rfc822_with_zone(native: dict) -> None:
    native["published_format"] = "rfc822"
    native["published_timezone"] = NIH_PUBLISHED_TIMEZONE


@pytest.mark.parametrize(
    "mutate",
    [_iso8601, _dialect_without_zone, _dialect_with_utc, _rfc822_with_zone],
)
def test_prod_guard_rejects_unreviewed_nih_date_settings(mutate: Callable[[dict], None]) -> None:
    with pytest.raises(PermissionError, match="INTELLIGENCE_PROD_NATIVE_POLICY_REQUIRED"):
        _compose("nih-news-releases", mutate)
