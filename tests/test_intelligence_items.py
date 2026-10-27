import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.intelligence_items import (
    REVISION_CONTENT_FIELDS,
    canonical_timestamp,
    canonical_url,
    identity_hash,
    item_identities,
    normalize_item,
    revision_content,
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


def test_revision_content_fields_keep_golden_hashes() -> None:
    """Moving the hash basis into one constant must not change fixture digests."""
    assert REVISION_CONTENT_FIELDS == (
        "title",
        "excerpt",
        "published_at",
        "updated_at",
        "event_at",
        "contract_version",
        "publisher_metadata",
        "native_metadata",
    )
    golden = (
        "1394a4e1c0bf2a6d258e57a05268114a6251f69983549366fdda5fa3c57239ea",
        "10512ab0027ff5194f0b068f6b82263b9b030f89f87dee63a949236aa0571f3d",
        "65bd8e397012ea11086b55589339e8c3086bed4788f5e81eb9429e2e0ec4bab9",
    )
    for name in ("rss-item.json", "atom-item.json", "email-item.json", "web-item.json"):
        fixture = json.loads((ROOT / "tests/fixtures/intelligence/v1" / name).read_text())
        assert item_identities(fixture) == golden
        assert (fixture["item_id"], fixture["content_sha256"], fixture["revision_id"]) == golden
        assert set(revision_content(fixture)) == {
            "title",
            "excerpt",
            "published_at",
            "updated_at",
            "event_at",
        }


def test_rss_fixture_documents_keep_main_hashes_without_matched_queries() -> None:
    """RSS fixtures have no matched_queries, so the hash basis stays byte-identical."""
    paths = sorted((ROOT / "tests/fixtures/intelligence").rglob("*-item.json"))
    assert [path.name for path in paths] == [
        "atom-item.json",
        "email-item.json",
        "rss-item.json",
        "web-item.json",
    ]
    for path in paths:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert "matched_queries" not in json.dumps(fixture)
        assert item_identities(fixture) == (
            fixture["item_id"],
            fixture["content_sha256"],
            fixture["revision_id"],
        )
        content = revision_content(fixture)
        assert "publisher_metadata" not in content or "matched_queries" not in content.get(
            "publisher_metadata", {}
        )


def test_matched_queries_do_not_change_the_revision_hash() -> None:
    native = {
        "inventory": ["item/title"],
        "item": {"title": "t"},
        "item_attributes": {},
        "publisher_dates": {},
    }
    publisher = {"description": "one", "categories": ["a"], "journal": "Lancet"}
    base = {
        "contract_version": "2.0.0",
        "title": "t",
        "excerpt": None,
        "published_at": None,
        "updated_at": None,
        "event_at": None,
        "publisher_metadata": publisher,
        "native_metadata": native,
    }
    labeled = {
        **base,
        "publisher_metadata": {
            **publisher,
            "matched_queries": ["pubmed-lyme-borrelia", "pubmed-tick-borne"],
        },
    }
    assert revision_content(base)["publisher_metadata"] == publisher
    assert "matched_queries" not in revision_content(labeled)["publisher_metadata"]
    assert identity_hash(revision_content(base)) == identity_hash(revision_content(labeled))
    changed = {**base, "title": "changed"}
    assert identity_hash(revision_content(base)) != identity_hash(revision_content(changed))


def test_contract_2_hash_covers_publisher_metadata_whole() -> None:
    native = {
        "inventory": ["item/title", "feed/title"],
        "item": {"title": "t"},
        "item_attributes": {},
        "publisher_dates": {},
    }
    base = {
        "contract_version": "2.0.0",
        "title": "t",
        "excerpt": None,
        "published_at": None,
        "updated_at": None,
        "event_at": None,
        "publisher_metadata": {"description": "one", "categories": ["a"]},
        "native_metadata": native,
    }
    changed = {
        **base,
        "publisher_metadata": {"description": "two", "categories": ["a"]},
    }
    assert identity_hash(revision_content(base)) != identity_hash(revision_content(changed))
    stored = revision_content(base)
    assert stored["native_metadata"]["inventory"] == ["item/title"]
    assert "feed/title" not in stored["native_metadata"]["inventory"]


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
