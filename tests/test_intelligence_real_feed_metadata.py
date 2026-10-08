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


def test_eid_six_path_policy_withholds_populated_description() -> None:
    packet = json.loads((ROOT / "cdc-eid-expedited.json").read_text(encoding="utf-8"))
    source = packet["source_candidate"]
    candidate = packet["mapping_policy_candidate"]
    policy = NativeMetadataPolicy(
        policy_ref="eid-six-path-negative-test",
        source_sha256=identity_hash(source),
        inventory=frozenset(candidate["inventory"]),
        permitted_paths=frozenset(
            {"feed/language", "feed/link", "feed/title", "item/link", "item/pubDate", "item/title"}
        ),
        required_paths=frozenset(),
        published_path="item/pubDate",
        published_format="rfc822",
        updated_path=None,
        updated_format="iso8601",
    )
    sample = packet["samples"][0]
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    for value in sample["native_metadata"]["feed"]:
        channel.append(_element(value))
    item = ET.SubElement(channel, "item")
    for value in sample["native_metadata"]["item"]:
        item.append(_element(value))
    next(node for node in item if node.tag == "description").text = "Populated article description"
    mapped = parse_native_feed(
        ET.tostring(root), source, policy, base_url=packet["evidence"]["endpoint"]
    )[0]
    assert mapped["excerpt"] is None
    assert (
        next(node for node in mapped["native_metadata"]["item"] if node["name"] == "description")[
            "value"
        ]
        is None
    )
    assert mapped["title"] == sample["canonical"]["title"]
    assert mapped["url"] == sample["canonical"]["url"]
    assert mapped["published_at"] == sample["canonical"]["published_at"]
    assert mapped["publisher_metadata"]["language"] == "en-us"
