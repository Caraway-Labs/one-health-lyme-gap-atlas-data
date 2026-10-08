"""Regression against genuine bounded CDC metadata captures, not raw feed copies."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from lyme_gap_atlas_data.intelligence_items import identity_hash, permitted_text, validate_record
from lyme_gap_atlas_data.intelligence_metadata import (
    NativeMetadataPolicy,
    inventory_feed,
    parse_native_feed,
)

ROOT = Path(__file__).parent / "fixtures/intelligence/native-captures"
SOURCES = (
    "cdc-mmwr",
    "cdc-eid-ahead-of-print",
    "cdc-eid-expedited",
    "cdc-outbreaks",
    "cdc-newsroom",
)


def _element(value: dict) -> ET.Element:
    node = ET.Element(value["name"])
    node.text = value["value"]
    node.tail = value["tail"]["value"]
    for attribute in value["attributes"]:
        # Withheld attribute shape survives without inventing its original value.
        node.set(attribute["name"], attribute["value"] or "")
    for child in value["children"]:
        node.append(_element(child))
    return node


@pytest.mark.parametrize("source_id", SOURCES)
def test_actual_source_inventory_mapping_and_drift(source_id: str) -> None:
    packet = json.loads((ROOT / (source_id + ".json")).read_text(encoding="utf-8"))
    evidence = packet["evidence"]
    assert evidence["status"] == 200
    assert evidence["mode"] == "metadata_fixture_only"
    assert evidence["raw_transport_retained"] is False
    assert evidence["uncovered_paths"] == []
    assert len(evidence["transport_sha256"]) == 64
    source = packet["source_candidate"]
    validate_record("source", source)
    assert source["state"] == "candidate" and source["approval"]["status"] == "pending"
    document = packet["mapping_policy_candidate"]
    for field in ("inventory", "permitted_paths", "required_paths"):
        document[field] = frozenset(document[field])
    policy = NativeMetadataPolicy(**document)
    covered = set()
    for sample in packet["samples"]:
        root = ET.Element("rss", version="2.0")
        parent = ET.SubElement(root, "channel")
        native = sample["native_metadata"]
        for attribute in native["feed_attributes"]:
            parent.set(attribute["name"], attribute["value"] or "")
        for value in native["feed"]:
            parent.append(_element(value))
        entry = ET.SubElement(parent, "item")
        for attribute in native["item_attributes"]:
            entry.set(attribute["name"], attribute["value"] or "")
        for value in native["item"]:
            entry.append(_element(value))
        xml = ET.tostring(root)
        covered.update(inventory_feed(xml, source, base_url=evidence["endpoint"]))
        mapped = parse_native_feed(xml, source, policy, base_url=evidence["endpoint"])[0]
        assert mapped["publisher_metadata"] == sample["publisher_metadata"]
        assert mapped["native_metadata"]["inventory"] == native["inventory"]
        for name in ("publisher_identity", "url", "title", "published_at", "updated_at"):
            value = permitted_text(mapped[name], 1000) if name == "title" else mapped[name]
            assert value == sample["canonical"][name]
        ET.SubElement(entry, "unexpectedNativeField").text = "publisher changed"
        with pytest.raises(ValueError, match="SCHEMA_DRIFT"):
            parse_native_feed(ET.tostring(root), source, policy, base_url=evidence["endpoint"])
    assert covered == set(evidence["observed_inventory"])


def test_unresolved_approved_sources_have_no_invented_capture() -> None:
    for source_id in ("pubmed-lyme-borrelia", "pubmed-tick-borne", "nih-news-releases"):
        assert not (ROOT / (source_id + ".json")).exists()


def test_eid_exact_conservative_candidate_withholds_unlicensed_values() -> None:
    packet = json.loads((ROOT / "cdc-eid-expedited.json").read_text(encoding="utf-8"))
    candidate = json.loads(
        (
            Path(__file__).parent.parent
            / "docs/delivery/eid-expedited-receipt-candidate-2026-10-07.json"
        ).read_text(encoding="utf-8-sig")
    )
    source = packet["source_candidate"]
    proposed = candidate["native_policy"]
    policy = NativeMetadataPolicy(
        policy_ref="eid-exact-candidate-test-only",
        source_sha256=identity_hash(source),
        inventory=frozenset(proposed["inventory"]),
        permitted_paths=frozenset(proposed["permitted_paths"]),
        required_paths=frozenset(proposed["required_paths"]),
        published_path=proposed["published_path"],
        published_format=proposed["published_format"],
        updated_path=proposed["updated_path"],
        updated_format=proposed["updated_format"],
    )
    assert policy.permitted_paths == frozenset(
        {"feed/language", "feed/link", "feed/title", "item/link", "item/pubDate", "item/title"}
    )
    sample = packet["samples"][0]["native_metadata"]
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    for value in sample["feed"]:
        channel.append(_element(value))
    item = ET.SubElement(channel, "item")
    for value in sample["item"]:
        item.append(_element(value))
    mapped = parse_native_feed(
        ET.tostring(root), source, policy, base_url=packet["evidence"]["endpoint"]
    )[0]
    expected = packet["samples"][0]["canonical"]
    assert mapped["title"] == expected["title"]
    assert mapped["url"] == expected["url"]
    assert mapped["published_at"] == expected["published_at"]
    assert mapped["excerpt"] is None
    assert mapped["publisher_metadata"]["language"] == "en-us"
    assert mapped["publisher_metadata"]["media"] == []
    assert mapped["publisher_metadata"]["date_states"]["updated_at"] == "not_provided"
    assert mapped["updated_at"] is None
    native = mapped["native_metadata"]
    image = next(node for node in native["feed"] if node["name"] == "image")
    assert image["value"] is None
    assert all(child["value"] is None for child in image["children"])
    description = next(node for node in native["item"] if node["name"] == "description")
    assert description["value"] is None

    item.remove(next(node for node in item if node.tag == "pubDate"))
    missing = parse_native_feed(
        ET.tostring(root), source, policy, base_url=packet["evidence"]["endpoint"]
    )[0]
    assert missing["published_at"] is None
    assert missing["publisher_metadata"]["date_states"]["published_at"] == "not_provided"
    ET.SubElement(item, "unexpectedNativeField").text = "publisher changed"
    with pytest.raises(ValueError, match="SCHEMA_DRIFT"):
        parse_native_feed(
            ET.tostring(root), source, policy, base_url=packet["evidence"]["endpoint"]
        )
