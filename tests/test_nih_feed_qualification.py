"""Minimal actual NIH metadata; no admission or retained article content."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from lyme_gap_atlas_data.ingestion.intelligence_feed import parse_feed
from lyme_gap_atlas_data.intelligence_items import normalize_item, validate_record

ROOT = Path(__file__).parent / "fixtures/intelligence"
PACKET = json.loads((ROOT / "nih-news-qualification.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", PACKET["samples"])
def test_actual_nih_metadata_preserves_unknown_chronology_and_provenance(sample):
    evidence = PACKET["evidence"]
    source = json.loads((ROOT / "v1/candidate-source.json").read_text())
    source.update(
        source_id="nih-news-releases",
        organization="NIH",
        family="nih_niaid",
        fetch_location=evidence["endpoint"],
        canonical_location=evidence["endpoint"],
        approved_hosts=["www.nih.gov"],
    )
    validate_record("source", source)
    assert source["state"] == "candidate" and source["approval"]["status"] == "pending"
    assert evidence["raw_transport_retained"] is False
    assert evidence["descriptions_retained"] is False
    assert evidence["sample_count"] < evidence["item_count"]
    root = ET.Element("rss", version="2.0")
    item = ET.SubElement(ET.SubElement(root, "channel"), "item")
    for name, value in sample["publisher_fields"].items():
        if value is not None:
            ET.SubElement(item, name).text = value
    parsed = parse_feed(ET.tostring(root), source)[0]
    provenance = {
        "run_id": "offline-nih-qualification",
        "artifact_id": "metadata-fixture-nih",
        "artifact_sha256": evidence["transport_sha256"],
        "parser_version": "rss-atom-v1",
        "fetch_version": "offline-fixture-v1",
    }
    normalized = normalize_item(
        source=source,
        transport="rss",
        fetched_at=evidence["captured_at"],
        provenance=provenance,
        **parsed,
    )
    assert normalized["title"] == sample["publisher_fields"]["title"].strip()
    assert normalized["canonical_url"] == sample["publisher_fields"]["link"].strip()
    assert normalized["published_at"] == sample["expected_published_at"]
    assert normalized["field_states"]["published_at"] == sample["expected_published_at_state"]
    assert normalized["fetched_at"] == evidence["captured_at"]
    assert normalized["excerpt"] is None and normalized["field_states"]["excerpt"] == "withheld"
    assert normalized["geographies"] == [] and normalized["event_at"] is None
    assert normalized["provenance"]["artifact_sha256"] == evidence["transport_sha256"]
    assert normalized["provenance"]["run_id"] == "offline-nih-qualification"
    assert (
        normalize_item(
            source=source,
            transport="rss",
            fetched_at=evidence["captured_at"],
            provenance=provenance,
            **parsed,
        )["revision_id"]
        == normalized["revision_id"]
    )
