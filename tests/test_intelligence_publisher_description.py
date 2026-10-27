"""Publisher description mapping. Live samples are public CDC and NIH text."""

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest
from test_intelligence_feed import approved, source
from test_intelligence_native_metadata import RAW, policy, records

from lyme_gap_atlas_data.intelligence_items import identity_hash, permitted_text, validate_record
from lyme_gap_atlas_data.intelligence_metadata import (
    NativeMetadataPolicy,
    inventory_feed,
    normalize_native_item,
    parse_native_feed,
    verify_native_item,
)

FIXTURES = Path(__file__).parent / "fixtures/intelligence/publisher-descriptions/2026-10-25"
RECEIPTS = Path(__file__).parents[1] / "config/intelligence/daily-policy-receipts.json"
FAMILIES = {
    "cdc-mmwr": "cdc_mmwr",
    "cdc-eid-ahead-of-print": "cdc_eid",
    "cdc-eid-expedited": "cdc_eid",
    "cdc-outbreaks": "cdc_other",
    "cdc-newsroom": "cdc_other",
    "nih-news-releases": "nih_niaid",
}
PERMITTED_NAMES = frozenset(
    {
        "item/description",
        "item/title",
        "item/link",
        "item/pubDate",
        "item/guid",
        "feed/title",
        "feed/link",
        "feed/language",
    }
)


def receipt(raw: bytes):
    base = policy(raw)
    return replace(
        base,
        inventory=base.inventory | {"item/description"},
        permitted_paths=base.permitted_paths | {"item/description"},
    )


@pytest.mark.parametrize(
    ("replacement", "text", "state"),
    [
        (b"", None, "not_provided"),
        (b"<description/>", "", "empty"),
        (b"<description>   </description>", "", "empty"),
        (
            b"<description><![CDATA[<em>E. coli</em> Outbreak linked to Raw Milk Cheese]]>"
            b"</description>",
            "E. coli Outbreak linked to Raw Milk Cheese",
            "present",
        ),
        (
            b"<description><![CDATA[<script>alert(1)</script>Safe text]]></description>",
            "Safe text",
            "present",
        ),
        (
            b"<description><![CDATA[Literal &amp;lt; label]]></description>",
            "Literal &lt; label",
            "present",
        ),
        (
            b"<description><![CDATA[<p>Publisher <b>summary</b>.</p>"
            b"<script>bad()</script><img src='https://example.org/a'>]]></description>",
            "Publisher summary .",
            "present",
        ),
    ],
)
def test_description_missing_empty_and_safe_html(replacement, text, state):
    raw = RAW.replace(b"<description>Rights-restricted article text</description>", replacement)
    document = records(raw, receipt=receipt(raw))[0]
    verify_native_item(document, receipt(raw), approved())
    assert document["publisher_metadata"]["description"] == {
        "text": text,
        "state": state,
        "format": "plain_text",
        "origin": "publisher",
    }
    assert "Tick borne disease" in document["publisher_metadata"]["categories"]


def test_description_is_revision_content_and_not_silently_truncated():
    first = records(RAW, receipt=receipt(RAW))[0]
    assert first == records(RAW, receipt=receipt(RAW))[0]
    revised = RAW.replace(b"Rights-restricted article text", b"Corrected publisher summary")
    second = records(revised, receipt=receipt(revised))[0]
    assert first["item_id"] == second["item_id"]
    assert first["revision_id"] != second["revision_id"]
    huge = RAW.replace(b"Rights-restricted article text", b"x" * 4097)
    with pytest.raises(ValueError, match="INTELLIGENCE_NATIVE_FIELD_LIMIT"):
        records(huge, receipt=receipt(huge))


def test_description_exact_field_bound_survives_writer_reconstruction():
    raw = RAW.replace(b"Rights-restricted article text", b"x" * 4096)
    document = records(raw, receipt=receipt(raw))[0]
    verify_native_item(document, receipt(raw), approved())
    assert document["publisher_metadata"]["description"]["text"] == "x" * 4096


def test_v2_record_without_description_remains_valid():
    document = records()[0]
    assert "description" not in document["publisher_metadata"]
    validate_record("item", document)


def test_active_receipts_still_withhold_descriptions():
    packet = json.loads(RECEIPTS.read_text(encoding="utf-8"))
    assert packet["receipts"]
    for entry in packet["receipts"]:
        permitted = set(entry["native_policy"]["permitted_paths"])
        if entry["registry_version"] < 3:
            assert "item/description" not in permitted
        assert not any(path.endswith("summary") for path in permitted)
        assert not any(
            "enclosure" in path or "mrss" in path or "copyright" in path for path in permitted
        )


def _captured_source(sample: dict, raw: bytes) -> dict:
    record = source(family=FAMILIES[sample["source_id"]])
    record["limits"] = {**record["limits"], "maximum_items": 20, "maximum_bytes": len(raw) + 1}
    record["fetch_location"] = sample["fetch_location"]
    record["canonical_location"] = sample["fetch_location"]
    return record


def _description_policy(raw: bytes, record: dict) -> NativeMetadataPolicy:
    observed = frozenset(inventory_feed(raw, record, base_url=record["fetch_location"]))
    permitted = observed & PERMITTED_NAMES
    assert "item/description" in permitted
    assert "item/pubDate" in observed
    return NativeMetadataPolicy(
        policy_ref="publisher-description-fixture",
        source_sha256=identity_hash(record),
        inventory=observed,
        permitted_paths=permitted,
        published_path="item/pubDate",
        published_format="rfc822",
    )


def test_live_description_samples_are_bounded_public_text():
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["captured_on"] == "2026-10-25"
    assert manifest["maximum_items"] == 20
    samples = manifest["sources"]
    assert {sample["source_id"] for sample in samples} == set(FAMILIES)
    outbreaks_plain = []
    for sample in samples:
        raw = (FIXTURES / f"{sample['source_id']}.xml").read_bytes()
        record = _captured_source(sample, raw)
        root = ET.fromstring(raw)
        channel = root.find("channel")
        assert channel is not None
        items = channel.findall("item")
        assert 1 <= len(items) <= 20
        assert len(items) == sample["retained_items"]
        assert sample["retained_items"] <= sample["feed_item_count"]
        policy_receipt = _description_policy(raw, record)
        mapped = parse_native_feed(raw, record, policy_receipt, base_url=record["fetch_location"])
        assert len(mapped) == len(items)
        for item, entry in zip(items, mapped, strict=True):
            description = entry["publisher_metadata"]["description"]
            raw_text = item.findtext("description")
            expected = permitted_text(raw_text, 4096) if raw_text and raw_text.strip() else ""
            assert description["origin"] == "publisher"
            assert description["format"] == "plain_text"
            assert description["state"] == ("present" if expected else "empty")
            assert description["text"] == (expected if raw_text is not None else None)
            text = description["text"] or ""
            assert "<" not in text and ">" not in text
            assert len(text) <= 4096
            document = normalize_native_item(
                source=record,
                transport=record["transport"],
                fetched_at="2026-10-25T00:00:00Z",
                provenance={
                    "run_id": "fixture-run",
                    "artifact_id": "fixture-artifact",
                    "artifact_sha256": "a" * 64,
                    "parser_version": "rss-atom-native-v2",
                    "fetch_version": "fixture-v1",
                },
                **entry,
            )
            verify_native_item(document, policy_receipt, record)
            if sample["source_id"].startswith("cdc-eid"):
                assert description["text"] == raw_text
                assert document["publisher_metadata"]["authors"] == []
            if sample["source_id"] == "cdc-outbreaks":
                outbreaks_plain.append(description["text"])
    assert "E. coli Outbreak linked to Raw Milk Cheese" in outbreaks_plain
