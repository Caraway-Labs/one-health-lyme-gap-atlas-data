# ruff: noqa: E501  # compact XML fixture remains intentionally source-faithful.
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from lyme_gap_atlas_data import pubmed_discovery as module
from lyme_gap_atlas_data.literature import HistoryCursor
from lyme_gap_atlas_data.pubmed_discovery import (
    MAX_RECORDS_PER_RUN,
    discover_pubmed,
    normalize_efetch_xml,
)
from lyme_gap_atlas_data.settings import PipelineSettings

EFETCH = b"""<?xml version='1.0'?><PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Lyme &amp; ticks</ArticleTitle>
<Journal><Title>Test Journal</Title><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue></Journal>
<Language>eng</Language><Abstract><AbstractText>Metadata abstract.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType='pmc'>PMC123</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


@pytest.mark.parametrize("failures", [0, 1, 2, 3])
def test_existing_metadata_retry_is_bounded_with_deterministic_backoff(
    failures: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    delays: list[float] = []
    monkeypatch.setattr(module.time, "sleep", delays.append)

    def fetch() -> bytes:
        nonlocal calls
        calls += 1
        if calls <= failures:
            raise RuntimeError("fixture-transient")
        return EFETCH

    if failures == 3:
        with pytest.raises(RuntimeError, match="fixture-transient"):
            module._retry(fetch)
    else:
        assert module._retry(fetch) == EFETCH
    assert calls == min(failures + 1, module.MAX_RETRIES)
    assert delays == [
        module.MIN_REQUEST_INTERVAL_SECONDS * index for index in range(1, min(failures, 2) + 1)
    ]


def test_normalize_efetch_metadata_without_full_text() -> None:
    records = normalize_efetch_xml(EFETCH)
    assert records[0].pmid == "123"
    assert records[0].pmcid == "PMC123"
    assert records[0].publication_date == "2025-01-01"
    assert records[0].abstract == "Metadata abstract."


def test_discovery_persists_artifact_before_normalizing_and_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    statements: list[tuple[str, object]] = []
    calls = 0

    class Client:
        def start(self, family: str) -> HistoryCursor:
            assert family == "vector_host_pathogen"
            return HistoryCursor(family, "history", "1", 10, 0)

        def fetch(self, cursor: HistoryCursor) -> bytes:
            nonlocal calls
            calls += 1
            events.append("fetch")
            assert cursor.retstart == 0
            assert cursor.batch_size == 1
            if calls == 1:
                raise RuntimeError("transient")
            return EFETCH

    class Store:
        def put_object(self, **kwargs: object) -> None:
            events.append("artifact")
            assert kwargs["ContentType"] == "application/xml"

    class Cursor:
        def execute(self, query: str, values: object = None) -> None:
            statements.append((query, values))
            events.append("raw" if "RAW_ARTIFACTS" in query else "sql")

    class Connection:
        def autocommit(self, enabled: bool) -> None:
            assert not enabled

        @contextmanager
        def cursor(self):
            yield Cursor()

        def commit(self) -> None:
            events.append("commit")

    @contextmanager
    def fake_connect(_: object):
        yield Connection()

    monkeypatch.setattr("lyme_gap_atlas_data.pubmed_discovery.connect", fake_connect)
    monkeypatch.setattr("lyme_gap_atlas_data.pubmed_discovery.time.sleep", lambda _: None)
    result = discover_pubmed(
        "vector_host_pathogen",
        maximum_records=1,
        batch_size=1,
        settings=PipelineSettings(ncbi_email="steward@example.org"),
        client=Client(),
        s3=Store(),
    )
    assert result["status"] == "COMPLETED"
    assert result["record_count"] == 1
    assert calls == 2
    assert events.count("artifact") == 1
    assert sum("MERGE INTO KNOWLEDGE_GRAPH.PAPERS " in sql for sql, _values in statements) == 1
    assert (
        sum("MERGE INTO KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES " in sql for sql, _values in statements)
        == 1
    )
    assert events.index("artifact") < events.index("raw")
    evidence_statement = next(
        statement for statement, _ in statements if "PUBMED_DISCOVERY_RUNS" in statement
    )
    request_statement = next(
        statement for statement, _ in statements if "INGESTION_REQUESTS" in statement
    )
    assert "OBJECT_CONSTRUCT" not in evidence_statement
    assert "OBJECT_CONSTRUCT" not in request_statement
    assert "PARSE_JSON" in evidence_statement
    assert "PARSE_JSON" in request_statement
    assert "SELECT" in evidence_statement
    assert "SELECT" in request_statement
    assert "created_at" in request_statement
    assert "started_at" not in request_statement
    assert "finished_at" not in request_statement


def test_discovery_rejects_unbounded_or_non_review_execution() -> None:
    with pytest.raises(ValueError, match="maximum_records"):
        discover_pubmed("vector_host_pathogen", maximum_records=MAX_RECORDS_PER_RUN + 1)
    with pytest.raises(ValueError, match="HUMAN_REVIEW"):
        discover_pubmed(
            "vector_host_pathogen",
            maximum_records=1,
            settings=PipelineSettings(
                ncbi_email="steward@example.org", papers_require_human_review=False
            ),
        )


def test_repeated_discovery_retains_membership_in_each_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence: dict[str, list[str]] = {}

    class Client:
        def start(self, family: str) -> HistoryCursor:
            return HistoryCursor(family, "history", "1", 1, 0)

        def fetch(self, _cursor: HistoryCursor) -> bytes:
            return EFETCH

    class Store:
        def put_object(self, **_kwargs: object) -> None:
            return None

    class Cursor:
        def execute(self, query: str, values: object = None) -> None:
            if "request_evidence = PARSE_JSON" in query:
                assert isinstance(values, tuple)
                evidence[values[3]] = json.loads(values[2])["pmids"]

    class Connection:
        def autocommit(self, _enabled: bool) -> None:
            return None

        @contextmanager
        def cursor(self):
            yield Cursor()

        def commit(self) -> None:
            return None

    @contextmanager
    def fake_connect(_settings: object):
        yield Connection()

    monkeypatch.setattr("lyme_gap_atlas_data.pubmed_discovery.connect", fake_connect)
    monkeypatch.setattr("lyme_gap_atlas_data.pubmed_discovery.time.sleep", lambda _x: None)
    settings = PipelineSettings(ncbi_email="reader@example.test")
    first = discover_pubmed(
        "vector_host_pathogen",
        maximum_records=1,
        batch_size=1,
        settings=settings,
        client=Client(),
        s3=Store(),
    )
    second = discover_pubmed(
        "vector_host_pathogen",
        maximum_records=1,
        batch_size=1,
        settings=settings,
        client=Client(),
        s3=Store(),
    )
    assert first["discovery_run_id"] != second["discovery_run_id"]
    assert evidence == {first["discovery_run_id"]: ["123"], second["discovery_run_id"]: ["123"]}


def test_dev_job_is_bounded_and_uses_runtime_contact_secret() -> None:
    spec = yaml.safe_load(Path(".do/app.yaml").read_text(encoding="utf-8"))
    job = next(item for item in spec["jobs"] if item["name"] == "pubmed-discovery-vector-host")
    assert job["run_command"].endswith(
        "--family vector_host_pathogen --max-records 25 --batch-size 25"
    )
    assert job["github"]["branch"] == "main"
    assert {item["key"] for item in job["envs"] if item.get("type") == "SECRET"} >= {
        "NCBI_EMAIL",
        "SNOWFLAKE_PRIVATE_KEY_B64",
        "SPACES_SECRET_ACCESS_KEY",
    }
