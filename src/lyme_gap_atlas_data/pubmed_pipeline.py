"""Executable, provenance-preserving PubMed discovery worker.

The worker deliberately stops at the steward review boundary.  It stores the
raw EFetch response before normalising a batch, so an operator can reproduce a
paper record from its query, History cursor, and immutable source artifact.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .artifacts import create_artifact
from .literature import EntrezHistoryClient, HistoryCursor, build_pubmed_query
from .settings import PipelineSettings


@dataclass(frozen=True)
class PubmedPaper:
    pmid: str
    pmcid: str | None
    title: str
    journal: str | None
    publication_date: str | None
    publication_types: tuple[str, ...]
    language: str
    abstract: str | None


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    uri: str
    object_key: str
    sha256: str
    byte_count: int


class ArtifactStore(Protocol):
    def put(
        self, *, resource_key: str, run_id: str, payload: bytes, media_type: str
    ) -> StoredArtifact: ...


class DiscoveryLedger(Protocol):
    def begin(self, *, run_id: str, family: str, cursor: HistoryCursor, query: str) -> None: ...

    def record_batch(
        self,
        *,
        run_id: str,
        cursor: HistoryCursor,
        artifact: StoredArtifact,
        papers: Iterable[PubmedPaper],
        configuration_version: str,
    ) -> None: ...

    def finish(self, *, run_id: str, status: str) -> None: ...


def _text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    value = " ".join("".join(node.itertext()).split())
    return value or None


def _publication_date(article: ET.Element) -> str | None:
    date = article.find(".//JournalIssue/PubDate")
    if date is None:
        return None
    year = _text(date.find("Year"))
    month = _text(date.find("Month"))
    day = _text(date.find("Day"))
    if not year:
        medline = _text(date.find("MedlineDate"))
        return medline[:4] if medline else None
    parts = [year]
    if month and month.isdigit():
        parts.append(month.zfill(2))
    if day and day.isdigit():
        parts.append(day.zfill(2))
    return "-".join(parts)


def parse_pubmed_efetch(payload: bytes) -> list[PubmedPaper]:
    """Normalise the small, permitted citation subset from an EFetch XML batch."""
    root = ET.fromstring(payload)
    papers: list[PubmedPaper] = []
    for citation in root.findall(".//PubmedArticle"):
        medline = citation.find("MedlineCitation")
        article = citation.find("MedlineCitation/Article")
        if medline is None or article is None:
            continue
        pmid = _text(medline.find("PMID"))
        title = _text(article.find("ArticleTitle"))
        if not pmid or not title:
            continue
        ids = {
            item.attrib.get("IdType", "").lower(): _text(item)
            for item in citation.findall("PubmedData/ArticleIdList/ArticleId")
        }
        abstract = (
            " ".join(
                value
                for value in (_text(item) for item in article.findall("Abstract/AbstractText"))
                if value
            )
            or None
        )
        papers.append(
            PubmedPaper(
                pmid=pmid,
                pmcid=ids.get("pmc"),
                title=title,
                journal=_text(article.find("Journal/Title")),
                publication_date=_publication_date(article),
                publication_types=tuple(
                    value
                    for value in (
                        _text(item)
                        for item in article.findall("PublicationTypeList/PublicationType")
                    )
                    if value
                ),
                language=_text(article.find("Language")) or "unknown",
                abstract=abstract,
            )
        )
    return papers


class SpacesArtifactStore:
    """Private Spaces storage with a checksum verification read after upload."""

    def __init__(self, settings: PipelineSettings) -> None:
        if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
            raise ValueError("Spaces credentials are required")
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.spaces_endpoint,
            aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
            region_name=settings.spaces_region,
            config=Config(signature_version="s3v4"),
        )

    def put(
        self, *, resource_key: str, run_id: str, payload: bytes, media_type: str
    ) -> StoredArtifact:
        artifact = create_artifact(
            payload=payload,
            environment=self._settings.topx_env,
            resource_key=resource_key,
            run_id=run_id,
        )
        key = f"{self._settings.spaces_prefix}/{artifact.object_key}"
        self._client.put_object(
            Bucket=self._settings.spaces_bucket, Key=key, Body=payload, ContentType=media_type
        )
        stored = self._client.get_object(Bucket=self._settings.spaces_bucket, Key=key)[
            "Body"
        ].read()
        if hashlib.sha256(stored).hexdigest() != artifact.sha256:
            raise RuntimeError("immutable PubMed artifact checksum verification failed")
        return StoredArtifact(
            artifact_id=str(uuid.uuid4()),
            uri=f"s3://{self._settings.spaces_bucket}/{key}",
            object_key=key,
            sha256=artifact.sha256,
            byte_count=artifact.byte_count,
        )


class SnowflakeDiscoveryLedger:
    """Write only the literature ledgers owned by the pipeline runtime."""

    def __init__(self, settings: SnowflakeSettings) -> None:
        self._settings = settings

    def begin(self, *, run_id: str, family: str, cursor: HistoryCursor, query: str) -> None:
        with connect(self._settings) as connection, connection.cursor() as cursor_db:
            cursor_db.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
                (discovery_run_id, family, query_text, query_sha256, webenv, query_key, result_count,
                 next_retstart, batch_size, status, request_evidence)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, 'RUNNING', PARSE_JSON(%s)""",
                (
                    run_id,
                    family,
                    query,
                    hashlib.sha256(query.encode()).hexdigest(),
                    cursor.webenv,
                    cursor.query_key,
                    cursor.count,
                    cursor.retstart,
                    cursor.batch_size,
                    json.dumps(
                        {"source": "NCBI E-utilities", "operation": "esearch", "usehistory": True}
                    ),
                ),
            )

    def record_batch(
        self,
        *,
        run_id: str,
        cursor: HistoryCursor,
        artifact: StoredArtifact,
        papers: Iterable[PubmedPaper],
        configuration_version: str,
    ) -> None:
        batch = list(papers)
        with connect(self._settings) as connection:
            connection.autocommit(False)
            try:
                with connection.cursor() as cursor_db:
                    cursor_db.execute(
                        """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                        (artifact_id, ingestion_run_id, artifact_uri, artifact_type, media_type, byte_count, sha256, created_at)
                        VALUES (%s, %s, %s, 'PUBMED_EFETCH_XML', 'application/xml', %s, %s, %s)""",
                        (
                            artifact.artifact_id,
                            run_id,
                            artifact.uri,
                            artifact.byte_count,
                            artifact.sha256,
                            datetime.now(UTC),
                        ),
                    )
                    for paper in batch:
                        cursor_db.execute(
                            """MERGE INTO KNOWLEDGE_GRAPH.PAPERS target USING
                            (SELECT %s pmid, %s pmcid, %s title, %s journal, TO_DATE(%s) publication_date,
                                    PARSE_JSON(%s) publication_types, %s language, %s abstract, %s configuration_version) source
                            ON target.pmid = source.pmid
                            WHEN MATCHED THEN UPDATE SET pmcid=source.pmcid, title=source.title, journal=source.journal,
                              publication_date=source.publication_date, publication_types=source.publication_types,
                              language=source.language, abstract=source.abstract, configuration_version=source.configuration_version,
                              updated_at=CURRENT_TIMESTAMP()
                            WHEN NOT MATCHED THEN INSERT
                              (pmid,pmcid,title,journal,publication_date,publication_types,language,abstract,state,configuration_version)
                              VALUES (source.pmid,source.pmcid,source.title,source.journal,source.publication_date,
                                      source.publication_types,source.language,source.abstract,'awaiting_review',source.configuration_version)""",
                            (
                                paper.pmid,
                                paper.pmcid,
                                paper.title,
                                paper.journal,
                                paper.publication_date,
                                json.dumps(paper.publication_types),
                                paper.language,
                                paper.abstract,
                                configuration_version,
                            ),
                        )
                        cursor_db.execute(
                            """MERGE INTO KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES target USING
                            (SELECT %s pmid, %s family, %s query_sha256, %s discovery_run_id) source
                            ON target.pmid=source.pmid AND target.family=source.family AND target.query_sha256=source.query_sha256
                            WHEN NOT MATCHED THEN INSERT (query_match_id,pmid,family,query_sha256,discovery_run_id)
                              VALUES (%s,source.pmid,source.family,source.query_sha256,source.discovery_run_id)""",
                            (
                                paper.pmid,
                                cursor.family,
                                hashlib.sha256(
                                    build_pubmed_query(cursor.family).encode()
                                ).hexdigest(),
                                run_id,
                                str(uuid.uuid4()),
                            ),
                        )
                    cursor_db.execute(
                        """UPDATE KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
                        SET raw_artifact_id=%s, next_retstart=%s WHERE discovery_run_id=%s""",
                        (artifact.artifact_id, cursor.retstart + cursor.batch_size, run_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def finish(self, *, run_id: str, status: str) -> None:
        with connect(self._settings) as connection, connection.cursor() as cursor_db:
            cursor_db.execute(
                "UPDATE KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS SET status=%s, finished_at=%s WHERE discovery_run_id=%s",
                (status, datetime.now(UTC), run_id),
            )


class PubmedDiscoveryWorker:
    def __init__(
        self, client: EntrezHistoryClient, artifacts: ArtifactStore, ledger: DiscoveryLedger
    ) -> None:
        self._client = client
        self._artifacts = artifacts
        self._ledger = ledger

    def run(self, family: str, *, maximum_batches: int | None = None) -> dict[str, object]:
        if maximum_batches is not None and maximum_batches < 1:
            raise ValueError("maximum_batches must be positive")
        cursor = self._client.start(family)
        run_id = str(uuid.uuid4())
        query = build_pubmed_query(family)
        self._ledger.begin(run_id=run_id, family=family, cursor=cursor, query=query)
        processed = 0
        try:
            while cursor.retstart < cursor.count and (
                maximum_batches is None or processed < maximum_batches
            ):
                payload = self._client.fetch(cursor)
                artifact = self._artifacts.put(
                    resource_key=f"pubmed:{family}",
                    run_id=run_id,
                    payload=payload,
                    media_type="application/xml",
                )
                papers = parse_pubmed_efetch(payload)
                self._ledger.record_batch(
                    run_id=run_id,
                    cursor=cursor,
                    artifact=artifact,
                    papers=papers,
                    configuration_version="kg-v1.0.0",
                )
                processed += 1
                cursor = HistoryCursor(
                    family=cursor.family,
                    webenv=cursor.webenv,
                    query_key=cursor.query_key,
                    count=cursor.count,
                    retstart=cursor.retstart + cursor.batch_size,
                    batch_size=cursor.batch_size,
                )
            status = "COMPLETED" if cursor.retstart >= cursor.count else "PARTIAL"
            self._ledger.finish(run_id=run_id, status=status)
            return {
                "discovery_run_id": run_id,
                "family": family,
                "batches": processed,
                "status": status,
            }
        except Exception:
            self._ledger.finish(run_id=run_id, status="FAILED")
            raise
