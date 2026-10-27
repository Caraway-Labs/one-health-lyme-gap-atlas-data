"""Registry v3 receipts for the five live feeds. Offline fixtures only."""

from __future__ import annotations

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_intelligence_recovery import AcquisitionLedger
from test_intelligence_runtime import PilotConnection

from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.intelligence_items import identity_hash, permitted_text
from lyme_gap_atlas_data.intelligence_metadata import NativeMetadataPolicy, parse_native_feed
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).parents[1]
LIVE = (
    "cdc-eid-ahead-of-print",
    "cdc-eid-expedited",
    "cdc-mmwr",
    "cdc-outbreaks",
    "nih-news-releases",
)
FIXTURE = ROOT / "tests/fixtures/intelligence/publisher-descriptions/2026-10-25/cdc-mmwr.xml"
RECORDED = ROOT / "tests/fixtures/intelligence/native-captures/cdc-mmwr.json"
CONDITION = (
    "Publish title, link, language, publisher date, publisher description "
    "(verbatim plain text) and publisher category labels, with attribution, "
    "non-endorsement and link back. No article text, image values, image bytes or logos."
)
MEDIA = "{http://search.yahoo.com/mrss/}content"


def _documents() -> dict[tuple[str, int], dict]:
    found = {}
    for source_id in LIVE:
        for version in (2, 3):
            path = ROOT / f"config/intelligence/{source_id}-source-v{version}.json"
            found[(source_id, version)] = json.loads(path.read_text(encoding="utf-8"))
    return found


def _receipts() -> list[dict]:
    packet = json.loads(
        (ROOT / "config/intelligence/daily-policy-receipts.json").read_text(encoding="utf-8")
    )
    return packet["receipts"]


def _policy(receipt: dict) -> NativeMetadataPolicy:
    native = receipt["native_policy"]
    return NativeMetadataPolicy(
        **{
            **native,
            **{
                key: frozenset(native[key])
                for key in ("inventory", "permitted_paths", "required_paths")
            },
        }
    )


def test_v3_registry_versions_record_the_reviewed_condition_and_fetch_url() -> None:
    documents = _documents()
    receipts = _receipts()
    for source_id in LIVE:
        current = documents[(source_id, 3)]
        previous = documents[(source_id, 2)]
        assert current["registry_version"] == 3
        assert current["access_use"]["excerpt_max_chars"] == 0
        assert current["access_use"]["public_excerpt_permitted"] is False
        assert current["limits"]["maximum_bytes"] == 2_097_152
        assert CONDITION in current["access_use"]["conditions"]
        assert current["approval"]["decision_ref"] == runtime.PROD_V3_DECISION
        assert identity_hash(current) == runtime.PROD_V3_SOURCE_SHA256[source_id]
        assert previous["fetch_location"] == runtime.ENDPOINTS[source_id]
        if source_id == "cdc-mmwr":
            assert current["fetch_location"] == runtime.ENDPOINTS[source_id] + "?max=250"
            assert current["canonical_location"] == runtime.ENDPOINTS[source_id]
        else:
            assert current["fetch_location"] == previous["fetch_location"]
        if source_id == "nih-news-releases":
            assert (
                current["access_use"]["terms_location"]
                == "https://www.nih.gov/web-policies-notices"
            )
            assert previous["access_use"]["terms_location"] == "https://www.nih.gov/web-policies"
        else:
            assert (
                current["access_use"]["terms_location"] == previous["access_use"]["terms_location"]
            )
    newsroom = list((ROOT / "config/intelligence").glob("*newsroom*"))
    assert newsroom == []
    assert all(receipt["source_id"] != "cdc-newsroom" for receipt in receipts)


def test_reviewed_package_loads_each_v3_source() -> None:
    spec = importlib.util.spec_from_file_location(
        "register_eid_expedited_dev",
        ROOT / "scripts/register_eid_expedited_dev.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for source_id in LIVE:
        source, checksum = module.reviewed_package(source_id, 3)
        assert source["registry_version"] == 3
        assert checksum == runtime.PROD_V3_SOURCE_SHA256[source_id]
        assert checksum == identity_hash(source)


def test_v3_receipts_add_only_the_reviewed_paths() -> None:
    by_version: dict[tuple[str, int], dict] = {}
    for receipt in _receipts():
        by_version[(receipt["source_id"], receipt["registry_version"])] = receipt
    for source_id in LIVE:
        receipt = by_version[(source_id, 3)]
        permitted = set(receipt["native_policy"]["permitted_paths"])
        assert permitted <= runtime.PROD_NATIVE_PATH_SUPERSET
        assert "item/description" in permitted
        assert ("item/category" in permitted) is (source_id in {"cdc-mmwr", "cdc-outbreaks"})
        assert ("item/guid" in permitted) is (
            source_id in {"cdc-mmwr", "cdc-outbreaks", "nih-news-releases"}
        )
        assert not any(
            "enclosure" in path or "mrss" in path or "copyright" in path for path in permitted
        )
        assert receipt["source_sha256"] == runtime.PROD_V3_SOURCE_SHA256[source_id]
        assert receipt["decision_ref"] == runtime.PROD_V3_DECISION
        prior = by_version[(source_id, 2)]
        assert "item/description" not in prior["native_policy"]["permitted_paths"]


def test_mmwr_v3_receipt_records_the_d2_and_d3r_decisions() -> None:
    receipt = next(
        row
        for row in _receipts()
        if row["source_id"] == "cdc-mmwr" and row["registry_version"] == 3
    )
    recorded = {row["id"]: row for row in receipt["decisions"]}
    assert recorded["D2"]["choice"] == "B"
    assert recorded["D2"]["issue"] == 812
    assert "2026-10-24 10:52 PM MT" in recorded["D2"]["recorded"]
    assert recorded["D3-R"]["choice"] == "approved"
    assert "2026-10-24 10:53 PM MT" in recorded["D3-R"]["recorded"]
    assert recorded["D2"]["owner"] == "MATTHEWCARAWAY"
    assert recorded["D3-R"]["owner"] == "MATTHEWCARAWAY"


def test_recorded_mmwr_fixture_is_under_the_byte_cap_without_a_live_fetch() -> None:
    evidence = json.loads(RECORDED.read_text(encoding="utf-8"))["evidence"]
    assert evidence["endpoint"] == "https://tools.cdc.gov/api/v2/resources/media/342778.rss"
    assert "?max=250" not in evidence["endpoint"]
    assert evidence["transport_bytes"] == 1_943_224
    assert evidence["item_count"] == 2332
    assert evidence["transport_bytes"] < 2_097_152
    source = _documents()[("cdc-mmwr", 3)]
    assert source["limits"]["maximum_bytes"] == 2_097_152
    assert FIXTURE.stat().st_size < 2_097_152


def test_v3_mmwr_receipt_maps_the_recorded_fixture() -> None:
    source = _documents()[("cdc-mmwr", 3)]
    receipt = next(
        row
        for row in _receipts()
        if row["source_id"] == "cdc-mmwr" and row["registry_version"] == 3
    )
    policy = _policy(receipt)
    raw = FIXTURE.read_bytes().replace(
        b"</item>",
        (
            b'<enclosure url="https://tools.cdc.gov/podcast.mp3" length="1" type="audio/mpeg"/>'
            b'<media:content url="https://tools.cdc.gov/logo.png" type="image/png" '
            b'width="1" height="1"/>'
            b"</item>"
        ),
        1,
    )
    mapped = parse_native_feed(raw, source, policy, base_url=source["fetch_location"])
    channel = ET.fromstring(raw).find("channel")
    assert channel is not None
    items = channel.findall("item")
    assert len(mapped) == len(items)
    saw_description = False
    for item, entry in zip(items, mapped, strict=True):
        publisher = entry["publisher_metadata"]
        labels: list[str] = []
        for category in item.findall("category"):
            label = permitted_text(category.text, 4096)
            if label and label not in labels:
                labels.append(label)
        assert publisher["categories"] == labels
        assert publisher["media"] == []
        description = item.findtext("description")
        if description and description.strip():
            saw_description = True
            assert publisher["description"]["state"] == "present"
            assert publisher["description"]["origin"] == "publisher"
            assert publisher["description"]["format"] == "plain_text"
        retained = _retained_values(entry["native_metadata"]["item"], "item")
        assert all(value is None for path, value in retained if _withheld(path))
        feed_values = _retained_values(entry["native_metadata"]["feed"], "feed")
        assert all(value is None for path, value in feed_values if path == "feed/copyright")
    assert saw_description


def _withheld(path: str) -> bool:
    return "enclosure" in path or MEDIA in path or path == "feed/copyright"


def _retained_values(nodes: list[dict], prefix: str) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []

    def walk(children: list[dict], current: str) -> None:
        for node in children:
            path = current + "/" + node["name"]
            found.append((path, node["value"]))
            for attribute in node["attributes"]:
                found.append((path + "/@" + attribute["name"], attribute["value"]))
            walk(node["children"], path)

    walk(nodes, prefix)
    return found


def test_prod_validation_rejects_an_enclosure_path_and_accepts_the_v3_receipt() -> None:
    source = _documents()[("cdc-mmwr", 3)]
    receipt = next(
        row
        for row in _receipts()
        if row["source_id"] == "cdc-mmwr" and row["registry_version"] == 3
    )
    configured = load_source_definition(ROOT / "config/sources/intelligence_cdc_mmwr.yml")
    settings = PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        spaces_bucket="one-health-lyme-gap-atlas-data-prod",
        spaces_prefix="prod",
        spaces_region="sfo3",
        spaces_endpoint="https://sfo3.digitaloceanspaces.com",
    )
    ledger = AcquisitionLedger()
    ledger.database = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    ledger.role = "OH_LYME_PROD_RUNTIME"
    ledger.sources = [source]
    _, loaded = runtime.compose_pilot(
        configured,
        receipts=[receipt],
        connection_factory=lambda: PilotConnection(ledger),
        settings=settings,
        registry_version=3,
    )
    assert loaded.endpoint_template == source["fetch_location"]
    assert loaded.endpoint_template.endswith("?max=250")
    assert not ledger.requests and not ledger.captures
    changed = json.loads(json.dumps(receipt))
    changed["native_policy"]["permitted_paths"] = [
        *changed["native_policy"]["permitted_paths"],
        "item/enclosure/@url",
    ]
    with pytest.raises(PermissionError, match="INTELLIGENCE_PROD_NATIVE_POLICY_REQUIRED"):
        runtime.compose_pilot(
            configured,
            receipts=[changed],
            connection_factory=lambda: pytest.fail("enclosure policy must precede SQL"),
            settings=settings,
            registry_version=3,
        )
