from __future__ import annotations

# ruff: noqa: E501
from pathlib import Path

import yaml

from lyme_gap_atlas_data.literature import HistoryCursor
from lyme_gap_atlas_data.pubmed_pipeline import (
    PubmedDiscoveryWorker,
    PubmedPaper,
    StoredArtifact,
    parse_pubmed_efetch,
)


def _efetch_xml() -> bytes:
    return b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
    <Article><Journal><JournalIssue><PubDate><Year>2025</Year><Month>7</Month></PubDate></JournalIssue>
    <Title>Journal of Lyme</Title></Journal><ArticleTitle>Lyme evidence <i>review</i></ArticleTitle>
    <Abstract><AbstractText Label='BACKGROUND'>First finding.</AbstractText><AbstractText>Second finding.</AbstractText></Abstract>
    <Language>eng</Language><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
    </Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType='pmc'>PMC456</ArticleId></ArticleIdList>
    </PubmedData></PubmedArticle></PubmedArticleSet>"""


def test_parses_permitted_citation_fields_from_efetch() -> None:
    papers = parse_pubmed_efetch(_efetch_xml())
    assert papers == [
        PubmedPaper(
            pmid="123",
            pmcid="PMC456",
            title="Lyme evidence review",
            journal="Journal of Lyme",
            publication_date="2025-07",
            publication_types=("Journal Article",),
            language="eng",
            abstract="First finding. Second finding.",
        )
    ]


class _Client:
    def start(self, family: str) -> HistoryCursor:
        assert family == "vector_host_pathogen"
        return HistoryCursor(family, "history", "1", 1, 0, 200)

    def fetch(self, cursor: HistoryCursor) -> bytes:
        assert cursor.retstart == 0
        return _efetch_xml()


class _Artifacts:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def put(
        self, *, resource_key: str, run_id: str, payload: bytes, media_type: str
    ) -> StoredArtifact:
        assert resource_key == "pubmed:vector_host_pathogen"
        assert media_type == "application/xml"
        self.payloads.append(payload)
        return StoredArtifact(
            "artifact-1",
            "s3://private/artifact.xml",
            "private/artifact.xml",
            "a" * 64,
            len(payload),
        )


class _Ledger:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.recorded: list[list[PubmedPaper]] = []

    def begin(self, **kwargs: object) -> None:
        assert kwargs["query"]

    def record_batch(self, **kwargs: object) -> None:
        self.recorded.append(list(kwargs["papers"]))  # type: ignore[arg-type]

    def finish(self, *, run_id: str, status: str) -> None:
        self.statuses.append(status)


def test_discovery_worker_persists_raw_response_before_review_queue_normalization() -> None:
    artifacts, ledger = _Artifacts(), _Ledger()
    result = PubmedDiscoveryWorker(_Client(), artifacts, ledger).run("vector_host_pathogen")
    assert result["status"] == "COMPLETED"
    assert artifacts.payloads == [_efetch_xml()]
    assert ledger.recorded[0][0].pmid == "123"
    assert ledger.statuses == ["COMPLETED"]


def test_production_spec_schedules_each_pubmed_family_and_single_extractor() -> None:
    spec = yaml.safe_load(Path(".do/app.prod.yaml").read_text(encoding="utf-8"))
    dev_spec = yaml.safe_load(Path(".do/app.yaml").read_text(encoding="utf-8"))
    expected_vpc_id = "a937d8dd-4ee9-4de2-a8df-b32e7ad4098e"
    assert spec["vpc"]["id"] == expected_vpc_id
    assert dev_spec["vpc"]["id"] == expected_vpc_id
    jobs = {job["name"]: job for job in spec["jobs"]}
    commands = [
        "surveillance_epidemiology",
        "vector_host_pathogen",
        "environment_exposure",
        "diagnostics_interventions_outcomes",
    ]
    for family in commands:
        assert any(f"--family {family}" in job["run_command"] for job in jobs.values())
    extraction = jobs["approved-paper-extraction"]
    assert extraction["run_command"].endswith("extract-approved-paper")
    envs = {entry["key"]: entry for entry in extraction["envs"]}
    assert set(envs).issuperset(
        {
            "NEO4J_URI",
            "NEO4J_RUNTIME_USER",
            "GROQ_API_KEY",
            "OPENAI_API_KEY",
            "SPACES_ACCESS_KEY_ID",
        }
    )
    assert envs["NEO4J_URI"]["value"] == "bolt://10.116.0.3:7687"
    assert envs["NEO4J_RUNTIME_USER"]["value"] == "graph_runtime"
    assert envs["NEO4J_RUNTIME_PASSWORD"]["type"] == "SECRET"
