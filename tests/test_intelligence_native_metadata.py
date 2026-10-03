"""Synthetic independent boundary tests; these are NOT real-source fixtures."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_intelligence_feed import approved, definition, fetch_adapter
from test_intelligence_storage import Ledger

from lyme_gap_atlas_data.ingestion.intelligence_feed import FeedResponse
from lyme_gap_atlas_data.intelligence_items import identity_hash, permitted_text, validate_record
from lyme_gap_atlas_data.intelligence_metadata import (
    NativeMetadataPolicy,
    inventory_feed,
    normalize_native_item,
    parse_native_feed,
    verify_native_item,
)
from lyme_gap_atlas_data.intelligence_storage import IntelligenceStore, WriteReceipt

RAW = b"""<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:media="http://search.yahoo.com/mrss/"><channel><title>Test publisher</title>
 <language>en-US</language><item><guid isPermaLink="false">native id 1</guid>
 <title>Test update</title><link>https://example.org/article/1</link>
 <pubDate>Wed, 30 Sep 2026 10:00:00 -0400</pubDate><author>Test Author</author>
 <category domain="test taxonomy">Tick borne disease</category><category>Research</category>
 <description>Rights-restricted article text</description>
 <media:thumbnail url="https://example.org/image.png" width="400"/>
 </item></channel></rss>"""


def test_sanitizer_flushes_real_cdc_query_links_without_losing_buffered_text() -> None:
    url = "https://tools.cdc.gov/api/embed/downloader/download.asp?m=342778&c=766563"
    assert permitted_text(url, 4096) == url


def policy(raw: bytes = RAW, source: dict | None = None) -> NativeMetadataPolicy:
    source = source or approved()
    fields = frozenset(inventory_feed(raw, source))
    return NativeMetadataPolicy(
        policy_ref="SYNTHETIC_FIXTURE_ONLY",
        source_sha256=identity_hash(source),
        inventory=fields,
        permitted_paths=fields - {"item/description"},
        published_path="item/pubDate",
        published_format="rfc822",
        required_paths=frozenset({"item/guid", "item/title", "item/link"}),
    )


def records(
    raw: bytes = RAW, source: dict | None = None, receipt: NativeMetadataPolicy | None = None
) -> list[dict]:
    source = source or approved()
    return [
        normalize_native_item(
            source=source,
            transport=source["transport"],
            fetched_at="2026-10-01T00:00:00Z",
            provenance={
                "run_id": "fixture-run",
                "artifact_id": "fixture-artifact",
                "artifact_sha256": "a" * 64,
                "parser_version": "rss-atom-native-v2",
                "fetch_version": "fixture-v1",
            },
            **entry,
        )
        for entry in parse_native_feed(raw, source, receipt or policy(raw, source))
    ]


def test_native_mapping_preserves_namespaces_attributes_and_non_token_categories() -> None:
    document = records()[0]
    native = document["native_metadata"]
    publisher = document["publisher_metadata"]
    assert publisher["source_item_id"] == "native id 1"
    assert publisher["authors"] == ["Test Author"]
    assert publisher["categories"] == ["Tick borne disease", "Research"]
    assert publisher["language"] == "en-US"
    assert publisher["media"] == [{"url": "https://example.org/image.png", "origin": "publisher"}]
    assert "item/guid/@isPermaLink" in native["inventory"]
    assert "item/{http://search.yahoo.com/mrss/}thumbnail/@width" in native["inventory"]
    guid = next(node for node in native["item"] if node["name"] == "guid")
    assert guid["attributes"] == [{"name": "isPermaLink", "value": "false", "state": "present"}]
    assert "Rights-restricted article text" not in json.dumps(native)
    assert document["derived_metadata"] == {}
    assert native["publisher_dates"]["published_at"]["raw"] == "Wed, 30 Sep 2026 10:00:00 -0400"
    assert document["published_at"] == "2026-09-30T14:00:00Z"
    verify_native_item(document, policy(), approved())


@pytest.mark.parametrize(
    "date,state,normalized",
    [
        ("Wed, 30 Sep 2026 10:00:00", "invalid", None),
        ("not a date", "invalid", None),
        ("", "not_provided", None),
    ],
)
def test_raw_dates_survive_invalid_or_unknown_without_invented_timezone(
    date: str, state: str, normalized: str | None
) -> None:
    raw = RAW.replace(b"Wed, 30 Sep 2026 10:00:00 -0400", date.encode())
    document = records(raw)[0]
    assert document["published_at"] == normalized
    assert document["field_states"]["published_at"] == state
    assert document["native_metadata"]["publisher_dates"]["published_at"]["raw"] == (date or None)


def test_reviewed_source_aware_iso_date_in_rss_namespace() -> None:
    raw = RAW.replace(
        b"<pubDate>Wed, 30 Sep 2026 10:00:00 -0400</pubDate>",
        b"<dc:date>2026-09-30T10:00:00-04:00</dc:date>",
    )
    receipt = replace(
        policy(raw),
        published_path="item/{http://purl.org/dc/elements/1.1/}date",
        published_format="iso8601",
    )
    document = records(raw, receipt=receipt)[0]
    assert document["published_at"] == "2026-09-30T14:00:00Z"
    assert document["native_metadata"]["publisher_dates"]["published_at"]["parser"] == "iso8601"


def test_unreviewed_native_field_and_required_field_loss_are_drift() -> None:
    for raw in (
        RAW.replace(b"</item>", b"<newField>unknown</newField></item>"),
        RAW.replace(b"<title>Test update</title>", b""),
    ):
        with pytest.raises(ValueError, match="SCHEMA_DRIFT"):
            parse_native_feed(raw, approved(), policy())


def test_quiet_native_feed_is_not_required_item_field_failure() -> None:
    start, end = RAW.index(b"<item>"), RAW.index(b"</item>") + len(b"</item>")
    assert parse_native_feed(RAW[:start] + RAW[end:], approved(), policy()) == []


def test_metadata_only_revision_and_overlapping_guid_items_are_not_dropped() -> None:
    changed = RAW.replace(
        b"<category>Research</category>", b"<category>Updated research</category>"
    )
    first, second = records()[0], records(changed)[0]
    assert first["item_id"] == second["item_id"]
    assert first["revision_id"] != second["revision_id"]
    # Same URL/title/dates but different source native IDs in a single capture.
    start, end = RAW.index(b"<item>"), RAW.index(b"</item>") + len(b"</item>")
    repeated = RAW[:end] + RAW[start:end].replace(b"native id 1", b"native id 2") + RAW[end:]
    documents = records(repeated)
    assert len({doc["revision_id"] for doc in documents}) == 2


def test_writer_resolves_native_rights_independently_and_stores_full_metadata() -> None:
    ledger = Ledger()
    document = records()[0]
    args = dict(
        source_id="synthetic-publication",
        registry_version=1,
        resource_key="synthetic-publication",
        run_id="fixture-run",
        items=[document],
    )
    rejected = IntelligenceStore(
        connection_factory=ledger.connect, retention_allowed=lambda ref: True
    )
    with pytest.raises(PermissionError, match="NATIVE_RIGHTS_REQUIRED"):
        rejected.write(**args)
    assert ledger.captures == {}
    store = IntelligenceStore(
        connection_factory=ledger.connect,
        retention_allowed=lambda ref: True,
        native_policy_lookup=lambda source, version: policy(),
    )
    assert store.write(**args) == WriteReceipt(1, 1, 0)
    assert store.write(**args) == WriteReceipt(0, 0, 1)
    captured = json.loads(next(iter(ledger.captures.values()))[1])
    assert captured["native_metadata"] == document["native_metadata"]
    revision = json.loads(next(iter(ledger.revisions.values()))[1])
    assert revision["native_metadata"]["item"] == document["native_metadata"]["item"]
    assert "feed" not in revision["native_metadata"]


def test_forged_public_publisher_fields_or_enrichment_fail_closed() -> None:
    forged = deepcopy(records()[0])
    forged["publisher_metadata"]["authors"] = ["Unattributed fabricated author"]
    with pytest.raises(PermissionError, match="MAPPING_INVALID"):
        verify_native_item(forged, policy(), approved())
    forged = deepcopy(records()[0])
    forged["derived_metadata"] = {"urgency": "high"}
    with pytest.raises(ValueError, match="INVALID_INTELLIGENCE_RECORD"):
        validate_record("item", forged)


def test_feed_refresh_timestamp_is_capture_evidence_not_an_article_revision() -> None:
    first = RAW.replace(
        b"<language>", b"<lastBuildDate>Wed, 30 Sep 2026 14:00:00 GMT</lastBuildDate><language>"
    )
    second = first.replace(b"Wed, 30 Sep 2026 14:00:00 GMT", b"Thu, 01 Oct 2026 14:00:00 GMT")
    before, after = records(first)[0], records(second)[0]
    assert before["native_metadata"] != after["native_metadata"]
    assert before["revision_id"] == after["revision_id"]


def test_denied_description_cannot_be_reintroduced_in_native_tree() -> None:
    forged = deepcopy(records()[0])
    node = next(node for node in forged["native_metadata"]["item"] if node["name"] == "description")
    node.update(value="Rights-restricted article text", state="present")
    with pytest.raises(PermissionError, match="NATIVE_RIGHTS_REQUIRED"):
        verify_native_item(forged, policy(), approved())


def test_adapter_keeps_two_native_variants_of_one_canonical_url() -> None:
    start, end = RAW.index(b"<item>"), RAW.index(b"</item>") + len(b"</item>")
    raw = RAW[:end] + RAW[start:end].replace(b"native id 1", b"native id 2") + RAW[end:]
    source = approved()
    receipt = policy(raw, source)
    adapter, _ = fetch_adapter(
        source, [FeedResponse(200, {}, raw)], native_policy_lookup=lambda sid, version: receipt
    )
    payload = adapter.acquire(definition(source)).payload
    payload["_acquisition_lineage"] = {
        "ingestion_run_id": "fixture-run",
        "artifact_id": "fixture-artifact",
    }
    result = adapter.normalize(definition(source), payload)
    assert len(result.records) == 2 and result.detail["duplicate_items"] == 0
    assert all(record["contract_version"] == "2.0.0" for record in result.records)


def test_atom_native_author_language_id_category_and_update_date() -> None:
    raw = b"""<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
    <author><name>Publisher Name</name></author><entry>
    <id>tag:example.org,2026:item-1</id><title>Publisher title</title>
    <link href="https://example.org/article/1"/>
    <published>2026-09-30T10:00:00-04:00</published>
    <updated>2026-10-01T01:02:03Z</updated>
    <category term="Tick borne disease" scheme="https://example.org/taxonomy"
    label="Publisher category"/></entry></feed>"""
    source = approved()
    source["transport"] = "atom"
    fields = frozenset(inventory_feed(raw, source))
    receipt = NativeMetadataPolicy(
        policy_ref="SYNTHETIC_FIXTURE_ONLY",
        source_sha256=identity_hash(source),
        inventory=fields,
        permitted_paths=fields,
        published_path="item/{http://www.w3.org/2005/Atom}published",
        published_format="iso8601",
        updated_path="item/{http://www.w3.org/2005/Atom}updated",
    )
    document = records(raw, source, receipt)[0]
    assert document["publisher_metadata"]["authors"] == ["Publisher Name"]
    assert document["publisher_metadata"]["categories"] == ["Tick borne disease"]
    assert document["publisher_metadata"]["language"] == "en"
    assert document["updated_at"] == "2026-10-01T01:02:03Z"
    assert (
        "item/{http://www.w3.org/2005/Atom}category/@scheme"
        in document["native_metadata"]["inventory"]
    )
    verify_native_item(document, receipt, source)
