"""Recorded-fixture tests for the draft PubMed Entrez adapter."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion import intelligence_entrez as entrez
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError
from lyme_gap_atlas_data.ingestion.checkpoints import (
    FileCheckpointStore,
    InMemoryCheckpointStore,
    SnowflakeCheckpointStore,
)
from lyme_gap_atlas_data.ingestion.intelligence_daily_run_ids import daily_run_id
from lyme_gap_atlas_data.ingestion.intelligence_entrez import (
    BATCH_SIZE,
    ENTREZ_DAILY_RESOURCE,
    ENTREZ_TOOL,
    ESEARCH_URL,
    MAX_ITEMS,
    MAX_RESPONSE_BYTES,
    SOURCE_ORDER,
    EntrezResponse,
    EntryDateLedger,
    RevisionLedger,
    encode_entrez_query,
    entrez_artifact_id,
    entry_dates_from_ledger,
    entry_window,
    execute_registered_entrez_daily,
    live_entrez_get,
    load_suppressions,
    mesh_refresh_candidates,
    read_bounded,
    refresh_pubmed_mesh,
    registered_entrez_sources,
    run_pubmed_daily,
    sanitize_abstract_text,
)
from lyme_gap_atlas_data.ingestion.intelligence_feed import adapter_for_source
from lyme_gap_atlas_data.ingestion.types import (
    RunState,
    RunStatus,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_raw_runtime import FeedRawRetention, SQLiteRawLedger
from lyme_gap_atlas_data.intelligence_retention import PROD_METADATA_FEED_IDS
from lyme_gap_atlas_data.intelligence_storage import IntelligenceStorageError
from lyme_gap_atlas_data.settings import PipelineSettings

FIXTURES = Path("tests/fixtures/pubmed")
TODAY = date(2026, 10, 25)
FETCHED_AT = "2026-10-25T12:00:00Z"
RUN_ID = "dev-pubmed-fixture"
EMAIL = "fixture@example.test"
OVERLAP_XML = (FIXTURES / "efetch_overlap.xml").read_bytes()


def _queries() -> dict[str, str]:
    document = json.loads(Path("config/intelligence/feed-selection-v1.json").read_text())
    return {
        entry["source_id"]: entry["query"]
        for entry in document["sources"]
        if entry["source_id"] in runtime.PUBMED_DRAFT_SOURCE_IDS
    }


def _settings(*, api_key: str | None = "fixture-key") -> PipelineSettings:
    return PipelineSettings(
        ncbi_email=EMAIL,
        ncbi_api_key=SecretStr(api_key) if api_key else None,
    )


def _article(pmid: str, entered: date) -> str:
    return (
        "<PubmedArticle><MedlineCitation>"
        f"<PMID>{pmid}</PMID><Article>"
        "<Journal><Title>Journal of Fixture Studies</Title><JournalIssue><PubDate>"
        f"<Year>{entered.year}</Year><Month>{entered.month}</Month><Day>{entered.day}</Day>"
        "</PubDate></JournalIssue></Journal>"
        f"<ArticleTitle>Recorded fixture {pmid}</ArticleTitle>"
        "<Abstract><AbstractText>Fixture abstract.</AbstractText></Abstract>"
        "<Language>eng</Language>"
        "<PublicationTypeList><PublicationType>Journal Article</PublicationType>"
        "</PublicationTypeList></Article>"
        "<MeshHeadingList><MeshHeading>"
        '<DescriptorName UI="D008193">Lyme Disease</DescriptorName>'
        "</MeshHeading></MeshHeadingList></MedlineCitation><PubmedData><History>"
        '<PubMedPubDate PubStatus="entrez">'
        f"<Year>{entered.year}</Year><Month>{entered.month}</Month><Day>{entered.day}</Day>"
        "</PubMedPubDate></History></PubmedData></PubmedArticle>"
    )


class FixtureTransport:
    def __init__(
        self,
        searches: dict[str, dict[str, Any]],
        *,
        overlap_xml: bytes | None = None,
        status: int | None = None,
        oversized: bool = False,
    ) -> None:
        self.searches = searches
        self.overlap_xml = overlap_xml
        self.status = status
        self.oversized = oversized
        self.calls: list[dict[str, str]] = []
        self.params: list[dict[str, str]] = []
        self.urls: list[str] = []
        self.contacts: list[bool] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
        assert timeout <= 30
        self.urls.append(url)
        self.params.append(dict(params))
        assert "api_key" not in params
        self.contacts.append(params.get("tool") == ENTREZ_TOOL and params.get("email") == EMAIL)
        hidden = {"tool", "email", "api_key"}
        self.calls.append({key: value for key, value in params.items() if key not in hidden})
        if self.status is not None and len(self.calls) == 1:
            return EntrezResponse(self.status, b"")
        if self.oversized and len(self.calls) == 1:
            return EntrezResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1))
        if url == ESEARCH_URL:
            found = self.searches[params["term"]]
            body = json.dumps(
                {"esearchresult": {"count": str(found["count"]), "idlist": found["idlist"]}}
            ).encode()
            return EntrezResponse(200, body)
        pmids = params["id"].split(",")
        if self.overlap_xml is not None and set(pmids) <= {"12345678", "23456789"}:
            return EntrezResponse(200, self.overlap_xml)
        parts = ["<PubmedArticleSet>"]
        for index, pmid in enumerate(pmids):
            entered = TODAY - timedelta(days=index)
            parts.append(_article(pmid, entered))
        parts.append("</PubmedArticleSet>")
        return EntrezResponse(200, "".join(parts).encode())


def _clock() -> tuple[list[float], Any, Any]:
    now = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    return sleeps, clock, sleep


def _run(
    transport: FixtureTransport,
    *,
    revisions: RevisionLedger | None = None,
    checkpoints: EntryDateLedger | None = None,
    request_limit: int = 5,
    settings: PipelineSettings | None = None,
    suppress_pmids: frozenset[str] | None = None,
    suppress_publishers: frozenset[str] | None = None,
) -> Any:
    sleeps, clock, sleep = _clock()
    budget = runtime.PilotBudget(clock, seconds=30, request_limit=request_limit)
    return run_pubmed_daily(
        today=TODAY,
        sender=transport,
        settings=settings or _settings(),
        budget=budget,
        fetched_at=FETCHED_AT,
        run_id=RUN_ID,
        clock=clock,
        sleep=sleep,
        checkpoints=checkpoints,
        revisions=revisions,
        suppress_pmids=suppress_pmids if suppress_pmids is not None else frozenset(),
        suppress_publishers=suppress_publishers if suppress_publishers is not None else frozenset(),
    ), sleeps


def _search_file(name: str) -> dict[str, dict[str, Any]]:
    raw = json.loads((FIXTURES / name).read_text())
    queries = _queries()
    return {queries[source_id]: value for source_id, value in raw.items()}


def test_registered_pubmed_sources_are_pinned_outside_the_rss_definitions() -> None:
    """Active PubMed documents are daily pins. They are not RSS source definitions."""
    assert runtime.PUBMED_SOURCE_IDS == runtime.PUBMED_DRAFT_SOURCE_IDS
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(runtime.ENDPOINTS)
    assert set(runtime.PROD_DAILY_SOURCE_SHA256) >= runtime.PUBMED_DRAFT_SOURCE_IDS
    assert set(runtime.PROD_SOURCE_SHA256) >= runtime.PUBMED_DRAFT_SOURCE_IDS
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(runtime.PROD_SOURCE_DEFINITIONS)
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(PROD_METADATA_FEED_IDS)
    assert set(runtime.PROD_SOURCE_DEFINITIONS) == (
        set(runtime.PROD_DAILY_SOURCE_SHA256) - set(runtime.PUBMED_SOURCE_IDS)
    )
    assert runtime.PUBMED_ESEARCH_ENDPOINT == ESEARCH_URL
    registered = registered_entrez_sources(runtime.PROD_DAILY_SOURCE_SHA256)
    assert [source["source_id"] for source in registered] == list(SOURCE_ORDER)
    for source_id in runtime.PUBMED_SOURCE_IDS:
        document = json.loads(
            Path(f"config/intelligence/{source_id}-source-v1.json").read_text(encoding="utf-8")
        )
        digest = identity_hash(document)
        assert document["state"] == "active"
        assert document["trust_classification"] == "research_index"
        assert document["cadence"]["poll_seconds"] == 86400
        assert digest == runtime.PROD_DAILY_SOURCE_SHA256[source_id]
        assert digest == runtime.PROD_SOURCE_SHA256[source_id]
        assert document["source_id"] not in runtime.PROD_SOURCE_DEFINITIONS
        assert adapter_for_source({"transport": "entrez", "source_id": source_id}) == "entrez"


def test_rss_composition_refuses_an_unregistered_pubmed_source() -> None:
    from dataclasses import replace

    from test_intelligence_runtime import selected

    configured, _source, receipts = selected()
    configured = replace(
        configured, source_id="pubmed-tick-borne", resource_key="pubmed-tick-borne"
    )
    with pytest.raises(PermissionError, match="PUBMED_DRAFT_UNREGISTERED"):
        runtime.compose_pilot(
            configured,
            receipts=receipts,
            connection_factory=lambda: pytest.fail("pubmed draft must not open a session"),
            settings=PipelineSettings(),
        )


def test_empty_watermark_uses_a_30_day_window_and_both_queries() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    outcome, sleeps = _run(transport, revisions=RevisionLedger(), checkpoints=EntryDateLedger())
    assert outcome.requests == 3
    assert outcome.requests <= 5
    assert len(outcome.items) == 2 <= MAX_ITEMS
    assert not outcome.truncated
    assert outcome.remaining == 0
    assert sleeps and all(gap >= 0.4 for gap in sleeps)
    assert len(sleeps) == outcome.requests - 1
    assert all(transport.contacts)
    searches = [call for call in transport.calls if call.get("db") == "pubmed" and "term" in call]
    assert len(searches) == 2
    assert {call["term"] for call in searches} == set(_queries().values())
    for call in searches:
        assert call["datetype"] == "edat"
        assert call["mindate"] == "2026/09/25"
        assert call["maxdate"] == "2026/10/25"
        assert int(call["retmax"]) <= 200
        assert call["usehistory"] == "n"
        assert call["retmode"] == "json"
        assert call["sort"] == "most recent"
    fetched = [call for call in transport.calls if "id" in call]
    assert len(fetched) == 1
    assert len(fetched[0]["id"].split(",")) <= BATCH_SIZE
    by_pmid = {item["publisher_metadata"]["source_item_id"]: item for item in outcome.items}
    shared = by_pmid["12345678"]
    alone = by_pmid["23456789"]
    assert shared["source_id"] == "pubmed-tick-borne"
    assert shared["publisher_metadata"]["matched_queries"] == [
        "pubmed-tick-borne",
        "pubmed-lyme-borrelia",
    ]
    assert shared["publisher_metadata"]["mesh"] == [{"name": "Lyme Disease", "ui": "D008193"}]
    assert shared["publisher_metadata"]["categories"] == ["Borrelia", "tick-borne"]
    assert shared["publisher_metadata"]["publication_types"] == ["Journal Article", "Review"]
    assert shared["publisher_metadata"]["authors"] == ["Ann Smith", "CDC Working Group"]
    assert shared["publisher_metadata"]["journal"] == "The Lancet Infectious Diseases"
    assert shared["publisher_metadata"]["doi"] == "10.1000/fixture.lyme"
    assert shared["excerpt"] is None
    abstract = shared["publisher_metadata"]["abstract"]
    assert abstract["state"] == "present"
    assert abstract["text"] == "RESULTS: Borrelia burgdorferi remains endemic."
    assert abstract["copyright_line"] == "© 2026 Elsevier B.V. All rights reserved."
    assert abstract["attribution"] == "Courtesy of the U.S. National Library of Medicine"
    assert shared["canonical_url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert shared["contract_version"] == "2.0.0"
    assert shared["transport"] == "entrez"
    assert alone["publisher_metadata"]["matched_queries"] == ["pubmed-tick-borne"]
    assert alone["publisher_metadata"]["mesh"] == []
    assert alone["publisher_metadata"]["abstract"]["text"] == "Results"
    assert alone["excerpt"] is None
    assert outcome.watermarks == {
        "pubmed-tick-borne": "2026-10-24",
        "pubmed-lyme-borrelia": "2026-10-24",
    }


def test_overlap_second_run_adds_no_revisions() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    revisions = RevisionLedger()
    checkpoints = EntryDateLedger()
    first, _sleeps = _run(transport, revisions=revisions, checkpoints=checkpoints)
    assert first.revisions_inserted == 2
    second, _sleeps = _run(transport, revisions=revisions, checkpoints=checkpoints)
    assert second.revisions_inserted == 0
    assert len(second.items) == 2
    assert len(revisions.keys) == 2
    assert second.windows["pubmed-tick-borne"][0] == "2026/10/22"
    assert {item["publisher_metadata"]["source_item_id"] for item in first.items} == {
        "12345678",
        "23456789",
    }


def test_union_of_195_uses_three_efetch_batches() -> None:
    transport = FixtureTransport(_search_file("esearch_union_195.json"))
    outcome, sleeps = _run(transport)
    assert outcome.requests == 5
    assert len(outcome.items) == 195
    assert not outcome.truncated
    assert outcome.remaining == 0
    batches = [len(call["id"].split(",")) for call in transport.calls if "id" in call]
    assert batches == [67, 67, 61]
    assert all(gap >= 0.4 for gap in sleeps)


def test_overflow_keeps_the_newest_200_and_reports_the_remainder() -> None:
    transport = FixtureTransport(_search_file("esearch_overflow.json"))
    checkpoints = EntryDateLedger()
    outcome, _sleeps = _run(transport, checkpoints=checkpoints)
    assert outcome.truncated is True
    assert outcome.remaining == 10
    assert len(outcome.items) == 200
    assert outcome.requests == 5
    batches = [len(call["id"].split(",")) for call in transport.calls if "id" in call]
    assert batches == [67, 67, 66]
    for source_id, watermark in outcome.watermarks.items():
        owned = [
            item["publisher_metadata"]["entry_date"]
            for item in outcome.items
            if source_id in item["publisher_metadata"]["matched_queries"]
            and item["publisher_metadata"]["entry_date"]
        ]
        assert watermark == min(owned)
        assert checkpoints.get(source_id) == date.fromisoformat(watermark)


def test_suppression_hides_abstract_text_and_keeps_the_item() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    outcome, _sleeps = _run(transport, suppress_pmids=frozenset({"12345678"}))
    shared = next(
        item for item in outcome.items if item["publisher_metadata"]["source_item_id"] == "12345678"
    )
    assert shared["publisher_metadata"]["abstract"]["state"] == "suppressed"
    assert shared["publisher_metadata"]["abstract"]["text"] is None
    assert shared["excerpt"] is None
    assert shared["title"] == "Lyme disease review"
    publisher = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    hidden, _sleeps = _run(
        publisher, suppress_publishers=frozenset({"The Lancet Infectious Diseases"})
    )
    again = next(
        item for item in hidden.items if item["publisher_metadata"]["source_item_id"] == "12345678"
    )
    assert again["publisher_metadata"]["abstract"]["state"] == "suppressed"
    assert again["publisher_metadata"]["abstract"]["text"] is None


def test_no_mesh_is_selected_by_the_later_refresh_pass() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    outcome, _sleeps = _run(transport)
    pending = mesh_refresh_candidates(outcome.items, today=TODAY)
    assert pending == ["23456789"]
    daily_requests = outcome.requests

    class RefreshTransport:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            self.calls += 1
            assert url.endswith("efetch.fcgi")
            assert "api_key" not in params
            xml = _article("23456789", date(2026, 10, 23)).encode()
            return EntrezResponse(200, b"<PubmedArticleSet>" + xml + b"</PubmedArticleSet>")

    refresh = RefreshTransport()
    _now, clock, sleep = _clock()
    budget = runtime.PilotBudget(clock, seconds=30, request_limit=3)
    found = refresh_pubmed_mesh(
        pending,
        sender=refresh,
        settings=_settings(api_key=None),
        budget=budget,
        clock=clock,
        sleep=sleep,
    )
    assert refresh.calls == 1
    assert budget.requests == 1
    assert daily_requests == 3
    assert found["23456789"] == [{"name": "Lyme Disease", "ui": "D008193"}]


def test_provider_errors_do_not_retry() -> None:
    for status, code in (
        (403, "FEED_HTTP_403"),
        (429, "FEED_RATE_LIMITED"),
        (500, "FEED_HTTP_FAILED"),
    ):
        transport = FixtureTransport(_search_file("esearch_overlap.json"), status=status)
        with pytest.raises(Exception, match=code) as caught:
            _run(transport)
        assert getattr(caught.value, "code", None) == code
        assert getattr(caught.value, "http_status", None) == status
        assert len(transport.calls) == 1
    oversized = FixtureTransport(_search_file("esearch_overlap.json"), oversized=True)
    with pytest.raises(Exception, match="FEED_TOO_LARGE"):
        _run(oversized)
    assert len(oversized.calls) == 1


def test_missing_contact_makes_no_request() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"))
    with pytest.raises(PermissionError, match="NCBI_CONTACT_REQUIRED"):
        _run(transport, settings=PipelineSettings(ncbi_email=""))
    assert transport.calls == []


def test_author_limit_and_overlong_abstract() -> None:
    authors = "".join(
        f"<Author><LastName>Author</LastName><ForeName>{index}</ForeName></Author>"
        for index in range(21)
    )
    xml = (
        "<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>30000001</PMID><Article>"
        "<Journal><Title>Journal</Title><JournalIssue><PubDate>"
        "<Year>2026</Year><Month>10</Month><Day>1</Day></PubDate></JournalIssue></Journal>"
        "<ArticleTitle>Many authors</ArticleTitle><AuthorList>"
        f"{authors}</AuthorList><Language>eng</Language></Article></MedlineCitation>"
        '<PubmedData><History><PubMedPubDate PubStatus="entrez">'
        "<Year>2026</Year><Month>10</Month><Day>24</Day></PubMedPubDate></History>"
        "</PubmedData></PubmedArticle></PubmedArticleSet>"
    ).encode()

    class AuthorTransport(FixtureTransport):
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            response = super().__call__(url, params, timeout)
            if "id" in params:
                return EntrezResponse(200, xml)
            return response

    searches = {
        _queries()["pubmed-tick-borne"]: {"count": 1, "idlist": ["30000001"]},
        _queries()["pubmed-lyme-borrelia"]: {"count": 0, "idlist": []},
    }
    outcome, _sleeps = _run(AuthorTransport(searches))
    assert outcome.items[0]["publisher_metadata"]["authors"][-1] == "et al."
    assert len(outcome.items[0]["publisher_metadata"]["authors"]) == 20

    long_xml = (
        "<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>30000002</PMID><Article>"
        "<Journal><Title>Journal</Title><JournalIssue><PubDate>"
        "<Year>2026</Year><Month>10</Month><Day>1</Day></PubDate></JournalIssue></Journal>"
        "<ArticleTitle>Long abstract</ArticleTitle>"
        f"<Abstract><AbstractText>{'a' * 6001}</AbstractText></Abstract>"
        "<Language>eng</Language></Article></MedlineCitation>"
        '<PubmedData><History><PubMedPubDate PubStatus="entrez">'
        "<Year>2026</Year><Month>10</Month><Day>24</Day></PubMedPubDate></History>"
        "</PubmedData></PubmedArticle></PubmedArticleSet>"
    ).encode()

    class LongTransport(FixtureTransport):
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            response = super().__call__(url, params, timeout)
            if "id" in params:
                return EntrezResponse(200, long_xml)
            return response

    long_searches = {
        _queries()["pubmed-tick-borne"]: {"count": 1, "idlist": ["30000002"]},
        _queries()["pubmed-lyme-borrelia"]: {"count": 0, "idlist": []},
    }
    kept, _sleeps = _run(LongTransport(long_searches))
    assert len(kept.items) == 1
    abstract = kept.items[0]["publisher_metadata"]["abstract"]
    assert abstract["state"] == "withheld"
    assert abstract["text"] is None
    assert "a" * 6001 not in json.dumps(kept.items)
    assert kept.withheld_abstracts == 1


def test_entrez_request_budget_stops_at_five() -> None:
    now = [0.0]
    budget = runtime.PilotBudget(lambda: now[0], seconds=30, request_limit=5)
    for _index in range(5):
        budget.reserve()
    with pytest.raises(PermissionError, match="REQUEST_LIMIT"):
        budget.reserve()


def test_first_window_is_thirty_days() -> None:
    assert entry_window(None, TODAY) == (date(2026, 9, 25), TODAY)
    assert entry_window(date(2026, 10, 24), TODAY) == (date(2026, 10, 22), TODAY)


def test_live_sender_rejects_a_non_entrez_host() -> None:
    with pytest.raises(Exception, match="FEED_HOST_NOT_APPROVED"):
        live_entrez_get("https://example.com/esearch.fcgi", {}, 1.0)


def test_abstract_keeps_comparisons_and_drops_script_content() -> None:
    assert sanitize_abstract_text("Mean age <65 years (p < 0.05)") == (
        "Mean age \uff1c65 years (p \uff1c 0.05)"
    )
    assert sanitize_abstract_text("CD4<CD8") == "CD4\uff1cCD8"
    assert sanitize_abstract_text("<script>x</script>Results") == "Results"
    xml = (
        b"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>30000003</PMID><Article>"
        b"<Journal><Title>Journal</Title><JournalIssue><PubDate>"
        b"<Year>2026</Year><Month>10</Month><Day>1</Day></PubDate></JournalIssue></Journal>"
        b"<ArticleTitle>Markup</ArticleTitle>"
        b"<Abstract><AbstractText><script>x</script>Results</AbstractText></Abstract>"
        b"<Language>eng</Language></Article></MedlineCitation>"
        b'<PubmedData><History><PubMedPubDate PubStatus="entrez">'
        b"<Year>2026</Year><Month>10</Month><Day>24</Day></PubMedPubDate></History>"
        b"</PubmedData></PubmedArticle></PubmedArticleSet>"
    )
    searches = {
        _queries()["pubmed-tick-borne"]: {"count": 1, "idlist": ["30000003"]},
        _queries()["pubmed-lyme-borrelia"]: {"count": 0, "idlist": []},
    }

    class ScriptTransport(FixtureTransport):
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            response = super().__call__(url, params, timeout)
            if "id" in params:
                return EntrezResponse(200, xml)
            return response

    outcome, _sleeps = _run(ScriptTransport(searches))
    assert outcome.items[0]["publisher_metadata"]["abstract"]["text"] == "Results"


def test_copyright_line_maps_angle_brackets() -> None:
    xml = (
        b"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>30000004</PMID><Article>"
        b"<Journal><Title>Journal</Title><JournalIssue><PubDate>"
        b"<Year>2026</Year><Month>10</Month><Day>1</Day></PubDate></JournalIssue></Journal>"
        b"<ArticleTitle>Copyright</ArticleTitle>"
        b"<Abstract><AbstractText>Results</AbstractText>"
        b"<CopyrightInformation>Copyright &lt;2026&gt; Holder</CopyrightInformation></Abstract>"
        b"<Language>eng</Language></Article></MedlineCitation>"
        b'<PubmedData><History><PubMedPubDate PubStatus="entrez">'
        b"<Year>2026</Year><Month>10</Month><Day>24</Day></PubMedPubDate></History>"
        b"</PubmedData></PubmedArticle></PubmedArticleSet>"
    )
    searches = {
        _queries()["pubmed-tick-borne"]: {"count": 1, "idlist": ["30000004"]},
        _queries()["pubmed-lyme-borrelia"]: {"count": 0, "idlist": []},
    }

    class CopyrightTransport(FixtureTransport):
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            response = super().__call__(url, params, timeout)
            if "id" in params:
                return EntrezResponse(200, xml)
            return response

    outcome, _sleeps = _run(CopyrightTransport(searches))
    line = outcome.items[0]["publisher_metadata"]["abstract"]["copyright_line"]
    assert line == "Copyright \uff1c2026\uff1e Holder"
    assert "<" not in line and ">" not in line


def test_search_sort_is_encoded_once_on_the_wire() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    _run(transport)
    search = next(call for call in transport.calls if call.get("sort"))
    wire = encode_entrez_query(search)
    request = httpx.Request("GET", ESEARCH_URL, params=search)
    for encoded in (wire, str(request.url)):
        assert "sort=most+recent" in encoded
        assert "most%2B" not in encoded
        assert "%252B" not in encoded
    assert parse_qs(urlsplit(str(request.url)).query)["sort"] == ["most recent"]


def test_whitespace_email_makes_no_request() -> None:
    transport = FixtureTransport(_search_file("esearch_overlap.json"))
    with pytest.raises(PermissionError, match="NCBI_CONTACT_REQUIRED"):
        _run(transport, settings=PipelineSettings(ncbi_email="   "))
    assert transport.calls == []


def test_response_cap_stops_while_streaming() -> None:
    pulled = {"n": 0}

    def chunks() -> Any:
        yield b"a" * MAX_RESPONSE_BYTES
        pulled["n"] += 1
        yield b"b"
        pulled["n"] += 1
        yield b"c"

    with pytest.raises(AcquisitionError, match="FEED_TOO_LARGE"):
        read_bounded(chunks())
    assert pulled["n"] == 1


def test_transport_error_hides_the_contact(caplog: pytest.LogCaptureFixture) -> None:
    email = "hidden-user@example.test"
    key = "hidden-key-value"

    class Boom:
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            assert "api_key" not in params
            raise httpx.ConnectError(f"{url}?email={params['email']}")

    with pytest.raises(Exception, match="FEED_NETWORK_FAILED") as caught:
        _run(
            Boom(),
            settings=PipelineSettings(ncbi_email=email, ncbi_api_key=SecretStr(key)),
        )
    assert email not in str(caught.value)
    assert key not in str(caught.value)
    assert email not in caplog.text
    assert key not in caplog.text

    class FakeStream:
        def __enter__(self) -> FakeStream:
            logging.getLogger("httpx").warning(
                "GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?email=%s&api_key=%s",
                email,
                key,
            )
            raise httpx.ConnectTimeout("timed out")

        def __exit__(self, *args: object) -> bool:
            return False

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def stream(self, *args: object, **kwargs: object) -> FakeStream:
            return FakeStream()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(httpx, "Client", FakeClient)
    caplog.set_level(logging.DEBUG, logger="httpx")
    try:
        with pytest.raises(Exception, match="FEED_TIMEOUT") as live:
            live_entrez_get(ESEARCH_URL, {"email": email, "api_key": key, "db": "pubmed"}, 5)
    finally:
        monkeypatch.undo()
    blob = str(live.value) + caplog.text
    assert email not in blob
    assert key not in blob


def _activated_sources() -> dict[str, Any]:
    sources = {}
    document = json.loads(Path("config/intelligence/pubmed-policy-receipts.json").read_text())
    for source_id in SOURCE_ORDER:
        source = json.loads(
            Path(f"config/intelligence/{source_id}-source-v1.json").read_text(encoding="utf-8")
        )
        source["state"] = "active"
        source["cadence"]["poll_seconds"] = 86400
        sources[source_id] = source
    for receipt in document["receipts"]:
        digest = identity_hash(sources[receipt["source_id"]])
        receipt["source_sha256"] = digest
        receipt["native_policy"]["source_sha256"] = digest
    return {
        "sources": sources,
        "receipts": document,
        "pinned": {source_id: identity_hash(source) for source_id, source in sources.items()},
    }


def test_registered_daily_run_writes_without_an_api_key() -> None:
    prepared = _activated_sources()
    checkpoints = InMemoryCheckpointStore()
    store_keys: set[tuple[str, str]] = set()
    writes: list[tuple[str, int]] = []

    class FakeStore:
        def write(
            self,
            *,
            source_id: str,
            registry_version: int,
            resource_key: str,
            run_id: str,
            items: list[dict[str, Any]],
        ) -> int:
            added = 0
            for item in items:
                key = (item["item_id"], item["revision_id"])
                if key not in store_keys:
                    store_keys.add(key)
                    added += 1
            writes.append((source_id, added))
            return added

    settings = PipelineSettings(ncbi_email=EMAIL, ncbi_api_key=None)
    first_sender = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    first = _daily(prepared, first_sender, checkpoints, FakeStore(), settings, run_id="pubmed-1")
    assert first["walked"] is True
    assert first["requests"] == 3
    assert first["windows"]["pubmed-tick-borne"] == ("2026/09/25", "2026/10/25")
    assert writes and writes[0][0] == "pubmed-tick-borne"
    assert all("api_key" not in call for call in first_sender.calls)
    load = checkpoints.load("pubmed-1")
    assert load is not None
    assert load.stages[0].detail["last_entry_date"]["pubmed-tick-borne"] == "2026-10-24"
    second_sender = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    before = len(writes)
    second = _daily(prepared, second_sender, checkpoints, FakeStore(), settings, run_id="pubmed-2")
    assert second["windows"]["pubmed-tick-borne"][0] == "2026/10/22"
    assert second_sender.calls[0]["mindate"] == "2026/10/22"
    assert all("api_key" not in call for call in second_sender.calls)
    assert writes[before:]
    assert all(added == 0 for _source_id, added in writes[before:])


def test_pubmed_reopen_walks_one_source_with_the_same_bounds() -> None:
    prepared = _activated_sources()
    checkpoints = InMemoryCheckpointStore()
    checkpoints.save(
        RunState(
            ingestion_run_id="prior-lyme",
            resource_key="pubmed-lyme-borrelia",
            source_definition_version=1,
            tier=Tier.C,
            status=RunStatus.SUCCEEDED,
            stages=[
                StageCheckpoint(
                    stage=Stage.LOAD,
                    status=StageStatus.COMPLETED,
                    detail={
                        "last_entry_date": {"pubmed-lyme-borrelia": "2026-10-01"},
                        "sequence": 4,
                    },
                )
            ],
        )
    )
    writes: list[str] = []

    class FakeStore:
        def write(self, *, source_id: str, items: list[dict[str, Any]], **_kwargs: Any) -> int:
            writes.append(source_id)
            return len(items)

    sender = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    _sleeps, clock, sleep = _clock()
    result = execute_registered_entrez_daily(
        pinned=prepared["pinned"],
        sender=sender,
        settings=PipelineSettings(ncbi_email=EMAIL, ncbi_api_key=None),
        budget=runtime.PilotBudget(clock, seconds=180, request_limit=5),
        checkpoints=checkpoints,
        store=FakeStore(),
        today=TODAY,
        run_id="unused",
        fetched_at=FETCHED_AT,
        clock=clock,
        sleep=sleep,
        sources=[prepared["sources"]["pubmed-tick-borne"]],
        receipt_document=prepared["receipts"],
        run_ids={"pubmed-tick-borne": "tick-reopen"},
        only_source_id="pubmed-tick-borne",
    )
    tick_term = _queries()["pubmed-tick-borne"]
    lyme_term = _queries()["pubmed-lyme-borrelia"]
    assert result["walked"] is True
    assert result["requests"] <= 5
    assert result["windows"] == {"pubmed-tick-borne": ("2026/09/25", "2026/10/25")}
    assert [call["term"] for call in sender.calls if "term" in call] == [tick_term]
    assert lyme_term not in json.dumps(sender.calls)
    assert writes == ["pubmed-tick-borne"]
    assert len(sender.calls) <= 5
    assert all(len(call.get("id", "").split(",")) <= BATCH_SIZE for call in sender.calls)
    saved = checkpoints.load("tick-reopen")
    assert saved is not None
    dates = saved.stages[0].detail["last_entry_date"]
    assert dates["pubmed-lyme-borrelia"] == "2026-10-01"
    assert "pubmed-tick-borne" in dates


def _daily(prepared, sender, checkpoints, store, settings, *, run_id: str) -> dict[str, Any]:
    _sleeps, clock, sleep = _clock()
    budget = runtime.PilotBudget(clock, seconds=30, request_limit=5)
    return execute_registered_entrez_daily(
        pinned=prepared["pinned"],
        sender=sender,
        settings=settings,
        budget=budget,
        checkpoints=checkpoints,
        store=store,
        today=TODAY,
        run_id=run_id,
        fetched_at=FETCHED_AT,
        clock=clock,
        sleep=sleep,
        sources=list(prepared["sources"].values()),
        receipt_document=prepared["receipts"],
    )


def test_unpinned_sources_are_not_fetched() -> None:
    def fail(url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
        raise AssertionError("unpinned sources must not be fetched")

    result = execute_registered_entrez_daily(
        pinned={},
        sender=fail,
        settings=PipelineSettings(ncbi_email=EMAIL),
        budget=runtime.PilotBudget(request_limit=5),
        checkpoints=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        today=TODAY,
        run_id="unused",
        fetched_at=FETCHED_AT,
        clock=lambda: 0.0,
        sleep=lambda _seconds: None,
    )
    assert result == {"walked": False, "requests": 0, "items": [], "windows": {}}


def test_entrez_daily_io_stays_closed_outside_prod() -> None:
    with pytest.raises(PermissionError, match="INTELLIGENCE_DAILY_PROD_REQUIRED"):
        polling.open_entrez_daily_io(PipelineSettings())


def test_candidate_documents_remain_loadable(monkeypatch: pytest.MonkeyPatch) -> None:
    original = entrez.json.loads

    def loads(text: str | bytes, *args: object, **kwargs: object) -> object:
        document = original(text, *args, **kwargs)
        if (
            isinstance(document, dict)
            and document.get("transport") == "entrez"
            and document.get("source_id") in SOURCE_ORDER
        ):
            document["state"] = "candidate"
            document["approval"]["status"] = "pending"
            document["approval"]["decision_ref"] = None
            document["approval"]["reviewed_at"] = None
            document["trust_review"]["status"] = "pending"
            document["trust_review"]["decision_ref"] = None
            document["trust_review"]["reviewed_at"] = None
            document["trust_classification"] = "unreviewed"
            document["cadence"]["poll_seconds"] = None
        return document

    monkeypatch.setattr(entrez.json, "loads", loads)
    loaded = entrez._load_sources()
    assert set(loaded) == set(SOURCE_ORDER)
    assert {source["state"] for source in loaded.values()} == {"candidate"}
    assert registered_entrez_sources(runtime.PROD_DAILY_SOURCE_SHA256) == []


def test_daily_job_calls_the_entrez_walk_only_when_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unregistered pubmed must not open a session")

    monkeypatch.setattr(polling, "registered_entrez_sources", lambda _pinned: [])
    monkeypatch.setattr(polling, "open_entrez_daily_io", fail_open)
    polling._walk_registered_entrez_daily(
        PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            intelligence_daily_enabled=True,
        ),
        "2026-10-25",
        preflight_only=False,
    )
    seen: dict[str, Any] = {}
    claims: list[tuple[str, str]] = []

    class Ledger:
        def claim_daily_run(self, run_id: str, source_id: str, source_sha256: str) -> bool:
            claims.append((run_id, source_id))
            return True

    ledger = Ledger()
    monkeypatch.setattr(
        polling,
        "registered_entrez_sources",
        lambda _pinned: [
            {"source_id": "pubmed-tick-borne"},
            {"source_id": "pubmed-lyme-borrelia"},
        ],
    )
    monkeypatch.setattr(
        polling, "open_entrez_daily_io", lambda _settings: ("store", ledger, "budget")
    )

    def execute(**kwargs: Any) -> dict[str, bool]:
        seen.update(kwargs)
        return {"walked": True}

    monkeypatch.setattr(polling, "execute_registered_entrez_daily", execute)
    polling._walk_registered_entrez_daily(
        PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            intelligence_daily_enabled=True,
        ),
        "2026-10-25",
        preflight_only=False,
        reopen_attempt=2,
    )
    assert seen["store"] == "store"
    assert seen["checkpoints"] is ledger
    assert seen["sender"] is live_entrez_get
    assert seen["run_ids"] == {
        source_id: daily_run_id(source_id, "2026-10-25", reopen_attempt=2)
        for source_id in ("pubmed-tick-borne", "pubmed-lyme-borrelia")
    }
    assert len(set(seen["run_ids"].values())) == 2
    assert [source_id for _run_id, source_id in claims] == [
        "pubmed-tick-borne",
        "pubmed-lyme-borrelia",
    ]


NCBI_DOCTYPE = (
    '<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" '
    '"https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">'
)


def _expect_efetch_invalid(body: str) -> None:
    with pytest.raises(AcquisitionError, match="FEED_EFETCH_PAYLOAD_INVALID") as caught:
        entrez._parse_efetch(body.encode())
    assert caught.value.code == "FEED_EFETCH_PAYLOAD_INVALID"


def test_ncbi_doctype_fixture_parses_real_field_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live header is removed before parse, so the DTD URL is never resolved."""
    xml = (FIXTURES / "efetch_ncbi_doctype.xml").read_bytes()
    assert xml.startswith(b'<?xml version="1.0" ?>\n' + NCBI_DOCTYPE.encode())
    seen: dict[str, bytes] = {}
    real_fromstring = entrez.ET.fromstring

    def capture(body: bytes) -> Any:
        seen["body"] = body
        return real_fromstring(body)

    monkeypatch.setattr(entrez.ET, "fromstring", capture)
    records = {record.pmid: record for record in entrez._parse_efetch(xml)}
    assert b"<!DOCTYPE" not in seen["body"]
    assert b"dtd.nlm.nih.gov" not in seen["body"]
    assert set(records) == {"31000001", "31000002", "31000003"}
    structured = records["31000001"]
    assert structured.title == "Tick Ixodes CO2 assay"
    assert structured.journal == "Wilderness & Environmental Medicine"
    assert structured.published_at == "2026-10-23T00:00:00Z"
    assert structured.entry_date == date(2026, 10, 24)
    assert structured.doi == "10.1000/fixture.1"
    assert structured.authors == ["Kai Ng"]
    assert structured.mesh == [{"name": "Lyme Disease", "ui": "D008193"}]
    assert structured.abstract_text == (
        "BACKGROUND: Caused by Borrelia when p \uff1c 0.05. METHODS: Given CO2 daily."
    )
    assert structured.copyright_line == "Copyright 2026 Holder"
    assert "<" not in (structured.abstract_text or "")
    medline = records["31000002"]
    assert medline.title == "Medline date without an abstract"
    assert medline.published_at is None
    assert medline.abstract_text is None
    assert medline.entry_date == date(2026, 10, 22)
    partial = records["31000003"]
    assert partial.title == "Range of Ixodes ticks"
    assert partial.published_at is None
    assert partial.abstract_text is None
    assert partial.entry_date == date(2026, 10, 21)


def test_ncbi_doctype_fixture_builds_feed_items() -> None:
    xml = (FIXTURES / "efetch_ncbi_doctype.xml").read_bytes()
    searches = {
        _queries()["pubmed-tick-borne"]: {
            "count": 3,
            "idlist": ["31000001", "31000002", "31000003"],
        },
        _queries()["pubmed-lyme-borrelia"]: {"count": 0, "idlist": []},
    }

    class HeaderTransport(FixtureTransport):
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            response = super().__call__(url, params, timeout)
            if "id" in params:
                return EntrezResponse(200, xml)
            return response

    outcome, _sleeps = _run(HeaderTransport(searches))
    by_pmid = {item["publisher_metadata"]["source_item_id"]: item for item in outcome.items}
    assert set(by_pmid) == {"31000001", "31000002", "31000003"}
    present = by_pmid["31000001"]["publisher_metadata"]["abstract"]
    assert present["state"] == "present"
    assert present["text"] == (
        "BACKGROUND: Caused by Borrelia when p \uff1c 0.05. METHODS: Given CO2 daily."
    )
    assert by_pmid["31000001"]["title"] == "Tick Ixodes CO2 assay"
    for pmid in ("31000002", "31000003"):
        abstract = by_pmid[pmid]["publisher_metadata"]["abstract"]
        assert abstract["state"] == "not_provided"
        assert abstract["text"] is None
        assert by_pmid[pmid]["field_states"]["published_at"] == "not_provided"


def test_realistic_esearch_shape_keeps_ids_and_ignores_the_warning_list() -> None:
    """Live esearch JSON: string count, header, translationset, and a warninglist."""
    warning = "Unknown sort schema 'most recent' ignored"
    body = json.dumps(
        {
            "header": {"type": "esearch", "version": "0.3"},
            "esearchresult": {
                "count": "1015",
                "retmax": "3",
                "retstart": "0",
                "idlist": ["42920256", "42905950", "0123"],
                "translationset": [{"from": "lyme disease", "to": "lyme disease[MeSH]"}],
                "querytranslation": "lyme disease",
                "warninglist": {
                    "phrasesignored": [],
                    "quotedphrasesnotfound": [],
                    "outputmessages": [warning],
                },
            },
        }
    ).encode()
    pmids, count = entrez._parse_esearch(body)
    assert count == 1015
    assert pmids == ["42920256", "42905950"]
    assert warning not in pmids
    with pytest.raises(AcquisitionError, match="FEED_ESEARCH_PAYLOAD_INVALID") as caught:
        entrez._parse_esearch(b'{"esearchresult": {"ERROR": "nope"}}')
    assert caught.value.code == "FEED_ESEARCH_PAYLOAD_INVALID"


@pytest.mark.parametrize(
    "body",
    [
        (
            '<?xml version="1.0" ?>\n'
            f"{NCBI_DOCTYPE[:-1]} [\n<!ELEMENT PubmedArticleSet ANY>\n]>\n"
            "<PubmedArticleSet></PubmedArticleSet>"
        ),
        (
            '<?xml version="1.0" ?>\n'
            f'{NCBI_DOCTYPE[:-1]} [\n<!ENTITY secret "expanded">\n]>\n'
            "<PubmedArticleSet>&secret;</PubmedArticleSet>"
        ),
        (
            '<?xml version="1.0" ?>\n'
            '<!DOCTYPE PubmedArticleSet SYSTEM "file:///etc/passwd">\n'
            "<PubmedArticleSet></PubmedArticleSet>"
        ),
        (
            '<?xml version="1.0" ?>\n'
            '<!DOCTYPE PubmedArticle PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" '
            '"https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">\n'
            "<PubmedArticleSet></PubmedArticleSet>"
        ),
        (
            '<?xml version="1.0" ?>\n'
            f"{NCBI_DOCTYPE}\n{NCBI_DOCTYPE}\n"
            "<PubmedArticleSet></PubmedArticleSet>"
        ),
        (
            '<?xml version="1.0" ?>\n'
            '<!DOCTYPE eEfetchResult PUBLIC "-//NLM//DTD efetch 20131226//EN" '
            '"https://eutils.ncbi.nlm.nih.gov/eutils/dtd/20131226/efetch.dtd">\n'
            "<eEfetchResult></eEfetchResult>"
        ),
    ],
)
def test_efetch_rejects_doctype_shapes_other_than_the_ncbi_header(body: str) -> None:
    _expect_efetch_invalid(body)


def test_pubmed_parse_failure_codes_stay_on_the_allowlist() -> None:
    for code in (entrez.ESEARCH_PAYLOAD_INVALID, entrez.EFETCH_PAYLOAD_INVALID):
        error = AcquisitionError(code, code=code)
        assert polling.allowlisted_error_code(error) == code
        assert polling.published_error_code(code) == code


def test_invalid_pmids_are_skipped() -> None:
    body = json.dumps(
        {
            "esearchresult": {
                "count": "4",
                "idlist": ["01234567", "12345678901", "", "34567890"],
            }
        }
    ).encode()
    pmids, count = entrez._parse_esearch(body)
    assert count == 4
    assert pmids == ["34567890"]
    xml = (
        "<PubmedArticleSet>"
        + _article("01234567", TODAY)
        + _article("12345678901", TODAY)
        + _article("", TODAY)
        + _article("34567890", TODAY)
        + "</PubmedArticleSet>"
    )
    records = entrez._parse_efetch(xml.encode())
    assert [record.pmid for record in records] == ["34567890"]

    fetched: list[str] = []

    class Refresh:
        def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
            assert "api_key" not in params
            fetched.extend(params["id"].split(","))
            article = _article("34567890", TODAY).encode()
            return EntrezResponse(200, b"<PubmedArticleSet>" + article + b"</PubmedArticleSet>")

    _now, clock, sleep = _clock()
    found = refresh_pubmed_mesh(
        ["01234567", "12345678901", "", "34567890"],
        sender=Refresh(),
        settings=_settings(),
        budget=runtime.PilotBudget(clock, seconds=30, request_limit=3),
        clock=clock,
        sleep=sleep,
    )
    assert fetched == ["34567890"]
    assert set(found) == {"34567890"}


def test_suppression_file_rejects_an_invalid_pmid(tmp_path: Path) -> None:
    path = tmp_path / "suppress.json"
    path.write_text(json.dumps({"pmids": ["0123"], "publishers": []}), encoding="utf-8")
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_SUPPRESSION_INVALID"):
        load_suppressions(path)
    path.write_text(json.dumps({"pmids": ["12345678901"], "publishers": []}), encoding="utf-8")
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_SUPPRESSION_INVALID"):
        load_suppressions(path)
    path.write_text(json.dumps({"pmids": [""], "publishers": []}), encoding="utf-8")
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_SUPPRESSION_INVALID"):
        load_suppressions(path)


def test_requests_never_include_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "env-secret-key")
    settings = PipelineSettings(ncbi_email=EMAIL)
    assert settings.ncbi_api_key is not None
    assert settings.ncbi_api_key.get_secret_value() == "env-secret-key"
    transport = FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML)
    _run(transport, settings=settings)
    assert transport.params
    rendered = json.dumps(transport.params)
    assert "api_key" not in rendered
    assert "env-secret-key" not in rendered


def test_load_sources_accepts_an_active_form(monkeypatch: pytest.MonkeyPatch) -> None:
    original = entrez.json.loads

    def loads(text: str | bytes, *args: object, **kwargs: object) -> object:
        document = original(text, *args, **kwargs)
        if (
            isinstance(document, dict)
            and document.get("transport") == "entrez"
            and document.get("source_id") in SOURCE_ORDER
        ):
            document["state"] = "active"
            document["approval"]["status"] = "approved"
            document["approval"]["decision_ref"] = "matthew-feed-selection-2026-10-03"
            document["approval"]["reviewed_at"] = "2026-10-03T00:00:00Z"
            document["trust_review"]["status"] = "approved"
            document["trust_review"]["decision_ref"] = "matthew-feed-selection-2026-10-03"
            document["trust_review"]["reviewed_at"] = "2026-10-03T00:00:00Z"
            document["trust_classification"] = "research_index"
            document["cadence"]["poll_seconds"] = 86400
        return document

    monkeypatch.setattr(entrez.json, "loads", loads)
    loaded = entrez._load_sources()
    assert set(loaded) == set(SOURCE_ORDER)
    assert {source["state"] for source in loaded.values()} == {"active"}


def test_registry_files_load_outside_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    loaded = entrez._load_sources()
    assert set(loaded) == set(SOURCE_ORDER)
    registered = registered_entrez_sources(runtime.PROD_DAILY_SOURCE_SHA256)
    assert [source["source_id"] for source in registered] == list(SOURCE_ORDER)


def _prod_daily_settings() -> PipelineSettings:
    return PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        intelligence_daily_enabled=True,
    )


def _succeeded_source(source_id: str, _path: str, **_kwargs: Any) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "outcome": "SUCCEEDED",
        "status": "COMPLETED",
        "failed_stage": None,
        "stage_timings_ms": {},
    }


class _ClaimLedger:
    def __init__(self) -> None:
        self.claims: list[tuple[str, str]] = []
        self.saved: list[Any] = []

    def claim_daily_run(self, run_id: str, source_id: str, source_sha256: str) -> bool:
        self.claims.append((run_id, source_id))
        return True

    def save(self, state: Any) -> None:
        self.saved.append(state)


def _patch_registered_pubmed(monkeypatch: pytest.MonkeyPatch, ledger: _ClaimLedger) -> None:
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _prod_daily_settings)
    monkeypatch.setattr(polling, "execute_daily_source", _succeeded_source)
    monkeypatch.setattr(
        polling,
        "registered_entrez_sources",
        lambda _pinned: [
            {"source_id": "pubmed-tick-borne"},
            {"source_id": "pubmed-lyme-borrelia"},
        ],
    )
    monkeypatch.setattr(
        polling, "open_entrez_daily_io", lambda _settings: ("store", ledger, "budget")
    )


def test_pubmed_failure_leaves_the_rss_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "hidden-query user@example.test"
    ledger = _ClaimLedger()
    _patch_registered_pubmed(monkeypatch, ledger)

    def boom(**_kwargs: Any) -> None:
        raise PermissionError(secret)

    monkeypatch.setattr(polling, "execute_registered_entrez_daily", boom)
    payload = polling.run_production_daily()
    rendered = json.dumps(payload)
    logged = capsys.readouterr().out
    assert payload["status"] == "SUCCEEDED"
    assert [row["source_id"] for row in payload["sources"]] == list(runtime.PROD_SOURCE_DEFINITIONS)
    assert all(row["outcome"] == "SUCCEEDED" for row in payload["sources"])
    assert secret not in rendered
    assert secret not in logged
    assert [row["source_id"] for row in payload["pubmed"]] == list(SOURCE_ORDER)
    assert {row["status"] for row in payload["pubmed"]} == {"FAILED"}
    assert {row["error_class"] for row in payload["pubmed"]} == {"PermissionError"}
    assert "pubmed-tick-borne" not in runtime.PROD_SOURCE_DEFINITIONS
    assert len(ledger.saved) == 2
    assert {state.status.value for state in ledger.saved} == {"FAILED"}
    assert {state.resource_key for state in ledger.saved} == set(SOURCE_ORDER)
    assert ledger.saved[0].ingestion_run_id != ledger.saved[1].ingestion_run_id
    assert "PermissionError" in logged
    assert "error_class" in logged


def test_rss_only_selection_does_not_claim_pubmed(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _ClaimLedger()
    _patch_registered_pubmed(monkeypatch, ledger)
    monkeypatch.setattr(
        polling,
        "execute_registered_entrez_daily",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("pubmed walk")),
    )
    source_id = next(iter(runtime.PROD_SOURCE_DEFINITIONS))
    payload = polling.run_production_daily(source_ids=(source_id,))
    assert ledger.claims == []
    assert "pubmed" not in payload
    assert payload["status"] == "SUCCEEDED"


def test_pubmed_walk_deadline_returns_the_rss_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _ClaimLedger()
    _patch_registered_pubmed(monkeypatch, ledger)
    monkeypatch.setattr(polling, "PUBMED_WALK_DEADLINE_SECONDS", 0.5)

    def hang(**_kwargs: Any) -> None:
        time.sleep(30)

    monkeypatch.setattr(polling, "execute_registered_entrez_daily", hang)
    started = time.monotonic()
    payload = polling.run_production_daily()
    elapsed = time.monotonic() - started
    capsys.readouterr()
    assert elapsed < 5
    assert payload["status"] == "SUCCEEDED"
    assert all(row["outcome"] == "SUCCEEDED" for row in payload["sources"])
    assert {row["error_class"] for row in payload["pubmed"]} == {"TimeoutError"}
    assert {state.status.value for state in ledger.saved} == {"FAILED"}


def test_cleared_alarm_is_rearmed_before_the_walk_continues(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import signal

    ledger = _ClaimLedger()
    _patch_registered_pubmed(monkeypatch, ledger)
    monkeypatch.setattr(polling, "PUBMED_WALK_DEADLINE_SECONDS", 0.4)

    def hang(**_kwargs: Any) -> None:
        # The Snowflake connector clears the one-shot timer inside a query.
        signal.setitimer(signal.ITIMER_REAL, 0)
        time.sleep(30)

    monkeypatch.setattr(polling, "execute_registered_entrez_daily", hang)
    started = time.monotonic()
    payload = polling.run_production_daily()
    elapsed = time.monotonic() - started
    capsys.readouterr()
    assert elapsed < 5
    assert {row["error_class"] for row in payload["pubmed"]} == {"TimeoutError"}
    assert {state.status.value for state in ledger.saved} == {"FAILED"}


def test_swallowed_alarm_cannot_extend_the_pubmed_walk(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _ClaimLedger()
    _patch_registered_pubmed(monkeypatch, ledger)
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", True)
    monkeypatch.setattr(polling, "PUBMED_WALK_DEADLINE_SECONDS", 0.8)
    monkeypatch.setattr(polling, "PUBMED_FAIL_SAVE_SECONDS", 0.3)
    saved: list[tuple[str, int]] = []

    def slow_save(
        day: str, reopen_attempt: int, source_ids: tuple[str, ...] = SOURCE_ORDER
    ) -> None:
        saved.append((day, reopen_attempt, source_ids))
        time.sleep(30)

    monkeypatch.setattr(polling, "_record_isolated_pubmed_failure", slow_save)
    monkeypatch.setenv("ATLAS_PUBMED_WALK_HANG", "swallow-alarm")
    started = time.monotonic()
    payload = polling.run_production_daily()
    elapsed = time.monotonic() - started
    capsys.readouterr()
    assert elapsed < 20
    assert saved
    assert payload["status"] == "SUCCEEDED"
    assert {row["error_class"] for row in payload["pubmed"]} == {"TimeoutError"}
    assert ledger.saved == []


def test_registered_capture_satisfies_write_references(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepared = _activated_sources()
    sources = prepared["sources"]
    retention = FeedRawRetention(
        SQLiteRawLedger(tmp_path / "ledger.sqlite"),
        environment="DEV",
        source_lookup=lambda source_id, version: sources[source_id],
        policy_lookup=lambda source: source["access_use"]["content_retention_policy_ref"],
        clock=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    class Ledger(InMemoryCheckpointStore):
        feed_retention = retention

        def __init__(self) -> None:
            super().__init__()
            self.claimed: dict[str, str] = {}

        def claim_daily_run(self, run_id: str, source_id: str, source_sha256: str) -> bool:
            if run_id in self.claimed:
                return False
            self.claimed[run_id] = source_id
            return source_sha256 == prepared["pinned"][source_id]

    requests: dict[str, dict[str, Any]] = {}
    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    revisions: set[tuple[str, str]] = set()
    added_counts: list[int] = []

    class Cursor:
        def execute(self, statement: str, params: tuple[Any, ...]) -> None:
            if "INGESTION_REQUESTS" in statement:
                requests[params[0]] = {
                    "run_id": params[1],
                    "endpoint": params[2],
                    "sha256": params[4],
                }
            elif "RAW_ARTIFACTS" in statement:
                artifacts[(params[0], params[1])] = {
                    "request_id": params[2],
                    "sha256": params[5],
                }

    class Store:
        @contextmanager
        def capture_session(self) -> Any:
            yield Cursor()

        def record_acquisition(self, **kwargs: Any) -> None:
            contexts[(kwargs["run_id"], kwargs["artifact_id"])] = kwargs["context"]

        def write(self, **kwargs: Any) -> int:
            run_id = kwargs["run_id"]
            source_id = kwargs["source_id"]
            if ledger.claimed.get(run_id) != source_id:
                raise IntelligenceStorageError("INTELLIGENCE_RUN_REFERENCE_INVALID")
            added = 0
            for item in kwargs["items"]:
                provenance = item["provenance"]
                artifact = artifacts.get((provenance["artifact_id"], run_id))
                request = requests.get(artifact["request_id"]) if artifact else None
                context = contexts.get((run_id, provenance["artifact_id"]))
                if artifact is None or artifact["sha256"] != provenance["artifact_sha256"]:
                    raise IntelligenceStorageError("INTELLIGENCE_ARTIFACT_REFERENCE_INVALID")
                if (
                    context is None
                    or request is None
                    or context["artifact_sha256"] != provenance["artifact_sha256"]
                    or context["effective_url"] != request["endpoint"]
                    or context["requested_url"] != ESEARCH_URL
                ):
                    raise IntelligenceStorageError("INTELLIGENCE_ACQUISITION_REFERENCE_INVALID")
                key = (item["item_id"], item["revision_id"])
                if key not in revisions:
                    revisions.add(key)
                    added += 1
            added_counts.append(added)
            return added

    ledger = Ledger()
    store = Store()
    settings = PipelineSettings(ncbi_email=EMAIL, ncbi_api_key=None)

    def open_io(_settings: object) -> tuple[Any, Any, Any]:
        return store, ledger, runtime.PilotBudget(seconds=30, request_limit=5)

    load_policies = entrez._load_policies
    monkeypatch.setattr(runtime, "PROD_DAILY_SOURCE_SHA256", prepared["pinned"])
    monkeypatch.setattr(
        entrez,
        "_load_policies",
        lambda loaded, document=None: load_policies(loaded, prepared["receipts"]),
    )
    monkeypatch.setattr(
        polling, "registered_entrez_sources", lambda _pinned: list(sources.values())
    )
    monkeypatch.setattr(polling, "open_entrez_daily_io", open_io)
    monkeypatch.setattr(
        polling,
        "live_entrez_get",
        FixtureTransport(_search_file("esearch_overlap.json"), overlap_xml=OVERLAP_XML),
    )
    polling._walk_registered_entrez_daily(settings, "2026-10-25", preflight_only=False)
    assert added_counts == [2]
    binding = retention.source_binding(next(iter(ledger.claimed)))
    assert binding is not None
    assert binding["parser_version"] == "entrez-efetch-v1"
    assert binding["fetch_version"] == "entrez-eutils-v1"
    sample_run = next(iter(ledger.claimed))
    assert entrez_artifact_id(sample_run) in {artifact_id for artifact_id, _run in artifacts}
    assert "pubmed-efetch" not in {artifact_id for artifact_id, _run in artifacts}
    policy = sources["pubmed-tick-borne"]["access_use"]["content_retention_policy_ref"]
    assert policy.endswith("metadata-raw-30d-v1")
    before = len(revisions)
    polling._walk_registered_entrez_daily(settings, "2026-10-26", preflight_only=False)
    assert len(revisions) == before
    assert added_counts[-1] == 0


def _watermark_state(run_id: str, resource_key: str, sequence: int, day: str) -> RunState:
    return RunState(
        ingestion_run_id=run_id,
        resource_key=resource_key,
        source_definition_version=1,
        tier=Tier.C,
        status=RunStatus.SUCCEEDED,
        stages=[
            StageCheckpoint(
                stage=Stage.LOAD,
                status=StageStatus.COMPLETED,
                detail={
                    "last_entry_date": {
                        "pubmed-tick-borne": day,
                        "pubmed-lyme-borrelia": day,
                    },
                    "sequence": sequence,
                },
            )
        ],
    )


def test_watermark_scan_reads_only_pubmed_resources(tmp_path: Path) -> None:
    memory = InMemoryCheckpointStore()
    for index in range(30):
        memory.save(_watermark_state(f"other-{index}", f"rss-{index}", 99, "1999-01-01"))
    memory.save(_watermark_state("pubmed-run", ENTREZ_DAILY_RESOURCE, 4, "2026-10-01"))

    def full_scan() -> list[RunState]:
        raise AssertionError("full list_runs")

    memory.list_runs = full_scan  # type: ignore[method-assign]
    ledger = entry_dates_from_ledger(memory)
    assert ledger.get("pubmed-tick-borne") == date(2026, 10, 1)
    assert ledger.get("pubmed-lyme-borrelia") == date(2026, 10, 1)

    files = FileCheckpointStore(tmp_path / "checkpoints")
    files.save(_watermark_state("other-file", "rss-file", 99, "1999-01-01"))
    files.save(_watermark_state("pubmed-file", "pubmed-tick-borne", 2, "2026-09-01"))
    matched = files.list_runs_for_resources((ENTREZ_DAILY_RESOURCE, *SOURCE_ORDER))
    assert [state.ingestion_run_id for state in matched] == ["pubmed-file"]

    detail = {
        "last_entry_date": {
            "pubmed-tick-borne": "2026-10-03",
            "pubmed-lyme-borrelia": "2026-10-04",
        },
        "sequence": 7,
    }
    pubmed_row = (
        "pubmed-run",
        ENTREZ_DAILY_RESOURCE,
        "C",
        "COMPLETED",
        1,
        "LOAD",
        "COMPLETED",
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        json.dumps(detail),
        None,
        None,
    )
    queries = {"count": 0}
    captured: dict[str, Any] = {}

    class Cursor:
        def execute(self, statement: str, params: object = None) -> None:
            queries["count"] += 1
            if queries["count"] >= 2500:
                raise PermissionError("INTELLIGENCE_PILOT_QUERY_LIMIT")
            captured["statement"] = statement
            captured["params"] = tuple(params) if isinstance(params, tuple) else ()
            self.rows: list[tuple[object, ...]] = (
                [pubmed_row]
                if "resource_key IN" in statement
                else [(f"other-{index}",) for index in range(3000)]
            )

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

    store = SnowflakeCheckpointStore(connection_factory=Connection)
    store.list_runs = full_scan  # type: ignore[method-assign]
    snowflake_ledger = entry_dates_from_ledger(store)
    assert queries["count"] == 1
    assert "resource_key IN" in captured["statement"]
    assert set(captured["params"]) == {ENTREZ_DAILY_RESOURCE, *SOURCE_ORDER}
    assert snowflake_ledger.get("pubmed-tick-borne") == date(2026, 10, 3)
    assert snowflake_ledger.get("pubmed-lyme-borrelia") == date(2026, 10, 4)
