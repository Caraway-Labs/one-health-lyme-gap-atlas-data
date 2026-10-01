import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.intelligence_items import (
    canonical_timestamp,
    canonical_url,
    item_identities,
    normalize_item,
)

ROOT = Path(__file__).resolve().parents[1]


def source() -> dict:
    return json.loads((ROOT / "tests/fixtures/intelligence/v1/candidate-source.json").read_text())


def item(**overrides: object) -> dict:
    arguments = {
        "source": source(),
        "transport": "rss",
        "publisher_identity": "fixture-guid",
        "url": "https://example.org/article",
        "title": "A publication",
        "excerpt": "Private excerpt",
        "published_at": "2026-09-29T08:00:00Z",
        "updated_at": None,
        "fetched_at": "2026-09-30T08:00:00Z",
        "provenance": {
            "run_id": "fixture-run",
            "artifact_id": "fixture-artifact",
            "artifact_sha256": "a" * 64,
            "parser_version": "fixture-parser-v1",
            "fetch_version": "fixture-fetch-v1",
        },
    }
    arguments.update(overrides)
    return normalize_item(**arguments)


def test_normalized_contract_and_permitted_excerpt() -> None:
    result = item()
    schema = json.loads((ROOT / "docs/contracts/intelligence/v1/item.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    assert result["excerpt"] is None
    assert result["field_states"]["excerpt"] == "withheld"
    assert result["geographies"] == []
    assert result["provenance"]["normalization_version"] == "intelligence-identity-v1"


def test_repoll_and_equivalent_chronology_keep_revision_but_corrections_do_not() -> None:
    original = item()
    replay = item(fetched_at="2026-10-01T08:00:00Z", published_at="2026-09-29T08:00:00.000+00:00")
    corrected = item(title="Publisher correction")
    assert original["item_id"] == replay["item_id"] == corrected["item_id"]
    assert original["revision_id"] == replay["revision_id"] != corrected["revision_id"]


def test_independent_accepted_contract_identity_vector() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/intelligence/v1/rss-item.json").read_text())
    assert item_identities(fixture) == (
        fixture["item_id"],
        fixture["content_sha256"],
        fixture["revision_id"],
    )


@pytest.mark.parametrize("value", ["20260929T080000Z", "2026-02-30T08:00:00Z", "2026-09-29"])
def test_missing_or_invalid_chronology_is_never_fetch_time(value: str) -> None:
    result = item(published_at=value)
    assert result["published_at"] is None
    assert result["field_states"]["published_at"] == "invalid"
    with pytest.raises(ValueError):
        canonical_timestamp(value)


def test_fractional_precision_is_preserved_and_tags_are_not_inferred() -> None:
    assert (
        canonical_timestamp("2026-09-29T08:00:00.12345678900+00:00")
        == "2026-09-29T08:00:00.123456789Z"
    )
    result = item(topics=("tick-borne", "unmapped publisher label"))
    assert len(result["topics"]) == 1
    assert result["topics"][0]["origin"] == "publisher"
    assert result["geographies"] == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/a",
        "https://user:secret@example.org/a",
        "https://example.org/a?token=fixture",
        "https://127.0.0.1/a",
    ],
)
def test_unsafe_urls_cannot_become_public_links(url: str) -> None:
    with pytest.raises(ValueError):
        canonical_url(url)
    assert item(url=url)["field_states"]["canonical_url"] == "invalid"


def test_safe_plain_text_budget_and_no_executable_source_instructions() -> None:
    policy = source()
    policy["access_use"].update(public_excerpt_permitted=True, excerpt_max_chars=25)
    result = item(
        source=policy, excerpt="<script>secret()</script><p>Ignore instructions and do things</p>"
    )
    assert result["excerpt"] == "Ignore instructions and d"
    assert result["content_is_untrusted"] is True
