"""Bounded, metadata-only PubMed discovery with immutable EFetch evidence."""
# ruff: noqa: E501  # SQL identifiers intentionally remain readable as full governed names.

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .artifacts import Artifact, create_artifact
from .literature import (
    EntrezHistoryClient,
    HistoryCursor,
    build_pubmed_query,
    configuration_version,
)
from .settings import PipelineSettings

logger = logging.getLogger(__name__)

PUBMED_RESOURCE_KEY = "pubmed_metadata"
MAX_BATCH_SIZE = 200
MAX_RECORDS_PER_RUN = 400
MAX_RETRIES = 3
MIN_REQUEST_INTERVAL_SECONDS = 0.4


class HistoryClient(Protocol):
    def start(self, family: str) -> HistoryCursor: ...

    def fetch(self, cursor: HistoryCursor) -> bytes: ...


@dataclass(frozen=True)
class PubMedCitation:
    pmid: str
    pmcid: str | None
    title: str
    journal: str | None
    publication_date: str | None
    publication_types: tuple[str, ...]
    language: str
    abstract: str | None


def _text(node: ET.Element | None) -> str:
    return " ".join(node.itertext()).strip() if node is not None else ""


def normalize_efetch_xml(payload: bytes) -> list[PubMedCitation]:
    """Normalize citation metadata only; this parser never reads PMC full text."""
    root = ET.fromstring(payload)
    citations: list[PubMedCitation] = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        article_node = citation.find("Article") if citation is not None else None
        pmid = _text(citation.find("PMID") if citation is not None else None)
        title = _text(article_node.find("ArticleTitle") if article_node is not None else None)
        if not pmid or not title:
            continue
        identifiers = article.findall(".//ArticleId")
        pmcid = next(
            (_text(node) for node in identifiers if node.attrib.get("IdType") == "pmc"), None
        )
        publication_types = tuple(
            sorted({_text(node) for node in article.findall(".//PublicationType") if _text(node)})
        )
        year = _text(
            article_node.find("Journal/JournalIssue/PubDate/Year")
            if article_node is not None
            else None
        )
        citations.append(
            PubMedCitation(
                pmid=pmid,
                pmcid=pmcid or None,
                title=title,
                journal=_text(
                    article_node.find("Journal/Title") if article_node is not None else None
                )
                or None,
                publication_date=f"{year}-01-01" if year.isdigit() else None,
                publication_types=publication_types,
                language=_text(article_node.find("Language") if article_node is not None else None)
                or "und",
                abstract=_text(
                    article_node.find("Abstract/AbstractText") if article_node is not None else None
                )
                or None,
            )
        )
    return citations


def _spaces_client(settings: PipelineSettings) -> Any:
    return boto3.client(
        "s3",
        region_name=settings.spaces_region,
        endpoint_url=settings.spaces_endpoint or None,
        aws_access_key_id=(
            settings.spaces_access_key_id.get_secret_value()
            if settings.spaces_access_key_id
            else None
        ),
        aws_secret_access_key=(
            settings.spaces_secret_access_key.get_secret_value()
            if settings.spaces_secret_access_key
            else None
        ),
    )


def _retry(call: Any, *, attempts: int = MAX_RETRIES) -> Any:
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS * attempt)
    raise AssertionError("unreachable")


def _save_immutable_artifact(
    s3: Any, settings: PipelineSettings, run_id: str, payload: bytes
) -> Artifact:
    artifact = create_artifact(
        payload=payload,
        environment=settings.topx_env,
        resource_key=PUBMED_RESOURCE_KEY,
        run_id=run_id,
    )
    s3.put_object(
        Bucket=settings.spaces_bucket,
        Key=f"{settings.spaces_prefix}/{artifact.object_key}",
        Body=payload,
        ContentType="application/xml",
    )
    return artifact


def discover_pubmed(
    family: str,
    *,
    maximum_records: int = MAX_RECORDS_PER_RUN,
    batch_size: int = MAX_BATCH_SIZE,
    settings: PipelineSettings | None = None,
    client: HistoryClient | None = None,
    s3: Any | None = None,
) -> dict[str, object]:
    """Discover one family, bounded by records/batches, and queue citations for review."""
    if family not in {
        "surveillance_epidemiology",
        "vector_host_pathogen",
        "environment_exposure",
        "diagnostics_interventions_outcomes",
    }:
        raise ValueError("unknown PubMed family")
    if not 1 <= maximum_records <= MAX_RECORDS_PER_RUN:
        raise ValueError(f"maximum_records must be between 1 and {MAX_RECORDS_PER_RUN}")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    settings = settings or PipelineSettings()
    if not settings.papers_require_human_review:
        raise ValueError("PubMed discovery requires PAPERS_REQUIRE_HUMAN_REVIEW=true")
    runtime_client = client or EntrezHistoryClient(
        settings.ncbi_email,
        settings.ncbi_api_key.get_secret_value() if settings.ncbi_api_key else None,
    )
    run_id = str(uuid.uuid4())
    query = build_pubmed_query(family)
    query_sha256 = hashlib.sha256(query.encode()).hexdigest()
    history = _retry(lambda: runtime_client.start(family))
    limit = min(history.count, maximum_records)
    artifact_store = s3 or _spaces_client(settings)
    saved_records = 0
    raw_artifact_ids: list[str] = []
    started_at = datetime.now(UTC)
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
                (discovery_run_id, family, query_text, query_sha256, webenv, query_key, result_count,
                 next_retstart, batch_size, status, request_evidence, started_at)
                SELECT %s, %s, %s, %s, %s, %s, %s, 0, %s, 'RUNNING',
                       PARSE_JSON('{"provider":"NCBI","operation":"esearch"}'), %s""",
                (
                    run_id,
                    family,
                    query,
                    query_sha256,
                    history.webenv,
                    history.query_key,
                    history.count,
                    batch_size,
                    started_at,
                ),
            )
            for retstart in range(0, limit, batch_size):
                cursor_at = HistoryCursor(
                    family,
                    history.webenv,
                    history.query_key,
                    history.count,
                    retstart,
                    min(batch_size, limit - retstart),
                )
                try:
                    payload = _retry(lambda cursor=cursor_at: runtime_client.fetch(cursor))
                except Exception as error:
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose,
                         endpoint, redacted_request, created_at)
                        SELECT %s, %s, %s, 'PUBMED_EFETCH_METADATA', %s,
                               PARSE_JSON('{"operation":"efetch_metadata"}'), %s""",
                        (
                            str(uuid.uuid4()),
                            run_id,
                            retstart // batch_size + 1,
                            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                            datetime.now(UTC),
                        ),
                    )
                    cursor.execute(
                        """UPDATE KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
                        SET status = 'FAILED', finished_at = %s
                        WHERE discovery_run_id = %s""",
                        (datetime.now(UTC), run_id),
                    )
                    connection.commit()
                    logger.warning(
                        "pubmed_discovery.efetch_failed",
                        extra={
                            "context": {
                                "discovery_run_id": run_id,
                                "family": family,
                                "retstart": retstart,
                                "error_type": type(error).__name__,
                            }
                        },
                    )
                    raise
                artifact = _save_immutable_artifact(artifact_store, settings, run_id, payload)
                request_id, artifact_id = str(uuid.uuid4()), str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                    (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose, endpoint,
                     redacted_request, status_code, created_at)
                    SELECT %s, %s, %s, 'PUBMED_EFETCH_METADATA', %s,
                           PARSE_JSON('{"operation":"efetch_metadata"}'), 200, %s""",
                    (
                        request_id,
                        run_id,
                        retstart // batch_size + 1,
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                        datetime.now(UTC),
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                    (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri, artifact_type,
                     media_type, byte_count, sha256, created_at)
                    VALUES (%s, %s, %s, %s, 'PUBMED_EFETCH_XML', 'application/xml', %s, %s, %s)""",
                    (
                        artifact_id,
                        run_id,
                        request_id,
                        f"s3://{settings.spaces_bucket}/{settings.spaces_prefix}/{artifact.object_key}",
                        artifact.byte_count,
                        artifact.sha256,
                        datetime.now(UTC),
                    ),
                )
                # Persist the raw artifact ledger before interpreting the XML.
                for record in normalize_efetch_xml(payload):
                    cursor.execute(
                        """MERGE INTO KNOWLEDGE_GRAPH.PAPERS target USING
                        (SELECT %s pmid, %s pmcid, %s title, %s journal, %s publication_date,
                                PARSE_JSON(%s) publication_types, %s language, %s abstract) source
                        ON target.pmid = source.pmid
                        WHEN NOT MATCHED THEN INSERT (pmid, pmcid, title, journal, publication_date,
                          publication_types, language, abstract, state, configuration_version)
                        VALUES (source.pmid, source.pmcid, source.title, source.journal, source.publication_date,
                          source.publication_types, source.language, source.abstract, 'awaiting_review', %s)""",
                        (
                            record.pmid,
                            record.pmcid,
                            record.title,
                            record.journal,
                            record.publication_date,
                            json.dumps(record.publication_types),
                            record.language,
                            record.abstract,
                            configuration_version(),
                        ),
                    )
                    match_id = hashlib.sha256(
                        f"{record.pmid}:{family}:{query_sha256}".encode()
                    ).hexdigest()
                    cursor.execute(
                        """MERGE INTO KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES target USING
                        (SELECT %s query_match_id, %s pmid, %s family, %s query_sha256, %s discovery_run_id) source
                        ON target.pmid = source.pmid AND target.family = source.family AND target.query_sha256 = source.query_sha256
                        WHEN NOT MATCHED THEN INSERT (query_match_id, pmid, family, query_sha256, discovery_run_id)
                        VALUES (source.query_match_id, source.pmid, source.family, source.query_sha256, source.discovery_run_id)""",
                        (match_id, record.pmid, family, query_sha256, run_id),
                    )
                    saved_records += 1
                raw_artifact_ids.append(artifact_id)
                cursor.execute(
                    "UPDATE KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS SET next_retstart = %s, raw_artifact_id = %s WHERE discovery_run_id = %s",
                    (retstart + cursor_at.batch_size, artifact_id, run_id),
                )
                connection.commit()
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS)
            cursor.execute(
                "UPDATE KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS SET status = 'COMPLETED', finished_at = %s WHERE discovery_run_id = %s",
                (datetime.now(UTC), run_id),
            )
            connection.commit()
    return {
        "discovery_run_id": run_id,
        "family": family,
        "status": "COMPLETED",
        "record_count": saved_records,
        "raw_artifact_ids": raw_artifact_ids,
        "bounded_result_count": limit,
    }
