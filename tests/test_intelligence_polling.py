"""Daily selection preserves authority, isolation and per-source progress."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_intelligence_feed import approved

from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_polling import prepare_daily_sources


def test_configured_pubmed_queries_cover_named_genus_and_disease_terms() -> None:
    selection = json.loads(
        (Path(__file__).parents[1] / "config/intelligence/feed-selection-v1.json").read_text()
    )
    rows = {row["source_id"]: row for row in selection["sources"]}
    broad = rows["pubmed-tick-borne"]
    assert broad["query_version"] == "pubmed-tick-borne-v2"
    for term in ("Babesia", "babesiosis", "Ehrlichia", "ehrlichiosis", "Powassan"):
        assert f"{term}[Title/Abstract]" in broad["query"]
    for source_id in ("pubmed-tick-borne", "pubmed-lyme-borrelia"):
        row = rows[source_id]
        assert row["query_sha256"] == identity_hash(
            {"query_version": row["query_version"], "query": row["query"]}
        )
        assert row["fetch_location"] is None  # No guessed generated feed token.


def _source(source_id: str) -> dict:
    source = approved()
    source.update(source_id=source_id, state="active")
    source["cadence"]["poll_seconds"] = 86400
    source["access_use"]["content_retention_policy_ref"] = "synthetic-retention-v1"
    return source


def _selection() -> dict:
    return {
        "contract_version": "intelligence-selection-v1",
        "poll_seconds": 86400,
        "sources": [
            {
                "source_id": "first",
                "decision": "approved",
                "fetch_location": "https://example.org/feed.xml",
            },
            {
                "source_id": "second",
                "decision": "approved",
                "fetch_location": "https://example.org/feed.xml",
            },
            {"source_id": "deferred", "decision": "deferred", "fetch_location": None},
        ],
    }


def _prepare(selection: dict, sources: dict, **kwargs: object) -> list:
    options = {
        "expected_selection_sha256": identity_hash(selection),
        "registry_versions": {key: 1 for key in sources},
        "registry_lookup": lambda source_id, version: sources[source_id],
        "retention_allowed": lambda policy: policy == "synthetic-retention-v1",
        "artifact_policy": "SYNTHETIC_FIXTURE_ONLY",
    }
    options.update(kwargs)
    return prepare_daily_sources(selection, **options)


def test_blocked_source_does_not_prevent_ready_source_or_activate_deferred() -> None:
    sources = {source_id: _source(source_id) for source_id in ("first", "second")}
    sources["first"]["access_use"]["content_retention_policy_ref"] = "unapproved-policy"
    selection = _selection()
    before = deepcopy(sources)
    result = _prepare(selection, sources)
    assert [entry.outcome for entry in result] == ["RETENTION_UNRESOLVED", "READY", "DEFERRED"]
    definition = result[1].definition
    assert definition.resource_key == definition.source_id == "second"
    assert definition.expected_refresh_cadence == "P1D"
    assert definition.extra["intelligence_registry"] == sources["second"]
    assert sources == before
    assert result[0].definition is result[2].definition is None


def test_new_row_requires_new_reviewed_selection_digest() -> None:
    selection = _selection()
    digest = identity_hash(selection)
    selection["sources"].append({"source_id": "new", "decision": "approved"})
    with pytest.raises(ValueError, match="SELECTION_INVALID"):
        _prepare(selection, {}, expected_selection_sha256=digest)


@pytest.mark.parametrize("change", ["endpoint", "cadence", "paused"])
def test_registry_cannot_silently_change_endpoint_cadence_or_activation(change: str) -> None:
    source = _source("first")
    if change == "endpoint":
        source["fetch_location"] = "https://example.org/different.xml"
    elif change == "cadence":
        source["cadence"]["poll_seconds"] = 3600
    else:
        source["state"] = "paused"
    result = _prepare(_selection(), {"first": source})
    assert result[0].outcome == "REGISTRY_POLICY_MISMATCH"
    assert all(entry.definition is None for entry in result)


def test_provider_errors_are_redacted_and_other_sources_continue() -> None:
    def lookup(source_id: str, version: int) -> dict:
        if source_id == "first":
            raise RuntimeError("private provider endpoint and token")
        return _source(source_id)

    result = _prepare(_selection(), {"first": {}, "second": {}}, registry_lookup=lookup)
    assert [entry.outcome for entry in result] == ["REGISTRY_LOOKUP_FAILED", "READY", "DEFERRED"]
    assert "private" not in repr(result)
