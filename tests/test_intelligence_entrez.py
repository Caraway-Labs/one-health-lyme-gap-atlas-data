"""Recorded-fixture tests for the draft PubMed Entrez adapter."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.intelligence_entrez import (
    BATCH_SIZE,
    ENTREZ_TOOL,
    ESEARCH_URL,
    MAX_ITEMS,
    MAX_RESPONSE_BYTES,
    EntrezResponse,
    EntryDateLedger,
    RevisionLedger,
    entry_window,
    live_entrez_get,
    mesh_refresh_candidates,
    refresh_pubmed_mesh,
    run_pubmed_daily,
)
from lyme_gap_atlas_data.ingestion.intelligence_feed import adapter_for_source
from lyme_gap_atlas_data.intelligence_retention import PROD_METADATA_FEED_IDS
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
        expect_api_key: bool = True,
    ) -> None:
        self.searches = searches
        self.overlap_xml = overlap_xml
        self.status = status
        self.oversized = oversized
        self.expect_api_key = expect_api_key
        self.calls: list[dict[str, str]] = []
        self.urls: list[str] = []
        self.contacts: list[bool] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> EntrezResponse:
        assert timeout <= 30
        self.urls.append(url)
        self.contacts.append(
            params.get("tool") == ENTREZ_TOOL
            and params.get("email") == EMAIL
            and ("api_key" in params) is self.expect_api_key
        )
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


def test_draft_sources_stay_out_of_prod_registration() -> None:
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(runtime.ENDPOINTS)
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(runtime.PROD_DAILY_SOURCE_SHA256)
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(runtime.PROD_SOURCE_DEFINITIONS)
    assert runtime.PUBMED_DRAFT_SOURCE_IDS.isdisjoint(PROD_METADATA_FEED_IDS)
    assert runtime.PUBMED_ESEARCH_ENDPOINT == ESEARCH_URL
    register = Path(".github/workflows/register-prod-eid.yml").read_text(encoding="utf-8")
    daily = Path("scripts/deploy_intelligence_daily.py").read_text(encoding="utf-8")
    assert "pubmed" not in register
    assert "NCBI_EMAIL" not in daily
    assert "NCBI_API_KEY" not in daily
    for source_id in runtime.PUBMED_DRAFT_SOURCE_IDS:
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
        assert call["sort"] == "most+recent"
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
            assert "api_key" not in params or params["api_key"] != ""
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
    for status, code in ((403, "FEED_HTTP_403"), (429, "FEED_RATE_LIMITED")):
        transport = FixtureTransport(_search_file("esearch_overlap.json"), status=status)
        with pytest.raises(Exception, match=code) as caught:
            _run(transport)
        assert getattr(caught.value, "code", None) == code
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
    refused, _sleeps = _run(LongTransport(long_searches))
    assert refused.items == []
    assert refused.refused_abstracts == 1


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
