"""Deterministic PMC retrieval-corpus chunking and DEV rebuild."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .pmc_graph import admit_pmc_open_access
from .settings import PipelineSettings

logger = logging.getLogger(__name__)

CORPUS_RULES_VERSION = "retrieval-corpus-v1"
TARGET_CHARS = 1200
OVERLAP_CHARS = 200
MIN_CHUNK_CHARS = 40
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class CorpusRules:
    rules_version: str = CORPUS_RULES_VERSION
    target_chars: int = TARGET_CHARS
    overlap_chars: int = OVERLAP_CHARS
    min_chunk_chars: int = MIN_CHUNK_CHARS

    def sha256(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class EligiblePaper:
    pmid: str
    pmcid: str
    artifact_id: str
    object_key: str
    jats_sha256: str
    text_sha256: str
    contribution_sha256: str


@dataclass(frozen=True)
class CorpusUnit:
    unit_id: str
    pmid: str
    pmcid: str
    artifact_id: str
    object_key: str
    jats_sha256: str
    text_sha256: str
    contribution_sha256: str
    chunk_index: int
    char_start: int
    char_end: int
    section_label: str
    unit_text: str
    unit_text_sha256: str


@dataclass(frozen=True)
class ChunkMetrics:
    empty_chunk_rejections: int = 0
    duplicate_chunk_rejections: int = 0
    missing_provenance_rejections: int = 0


class ArtifactStore(Protocol):
    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _normalize(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def extract_section_texts(jats: bytes) -> list[tuple[str, str]]:
    """Return ordered (section_label, normalized_text) pairs from JATS body."""
    root = ET.fromstring(jats)
    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), None)
    if body is None:
        return []
    sections: list[tuple[str, str]] = []
    for section in body.iter():
        if _local_name(section.tag) != "sec":
            continue
        title_node = next(
            (child for child in list(section) if _local_name(child.tag) == "title"), None
        )
        label = _normalize("".join(title_node.itertext())) if title_node is not None else "section"
        # Direct paragraph text under this section, excluding nested sec bodies.
        parts: list[str] = []
        for child in list(section):
            name = _local_name(child.tag)
            if name == "title":
                continue
            if name == "sec":
                continue
            parts.append(_normalize("".join(child.itertext())))
        text = _normalize(" ".join(part for part in parts if part))
        if text:
            sections.append((label or "section", text))
    if sections:
        return sections
    # Fallback: whole body text when the article has no sec wrappers.
    body_text = _normalize(" ".join(body.itertext()))
    return [("body", body_text)] if body_text else []


def _window_text(
    text: str, *, target_chars: int, overlap_chars: int, min_chunk_chars: int
) -> list[tuple[int, int, str]]:
    if len(text) <= target_chars:
        return [(0, len(text), text)] if len(text) >= min_chunk_chars else []
    windows: list[tuple[int, int, str]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + target_chars, length)
        if end < length:
            # Prefer breaking on whitespace so rebuilds stay stable.
            break_at = text.rfind(" ", start + min_chunk_chars, end + 1)
            if break_at > start:
                end = break_at
        chunk = text[start:end].strip()
        if len(chunk) >= min_chunk_chars:
            # Map stripped chunk back to original offsets conservatively.
            rel = text[start:end].find(chunk)
            chunk_start = start + max(rel, 0)
            chunk_end = chunk_start + len(chunk)
            windows.append((chunk_start, chunk_end, chunk))
        if end >= length:
            break
        next_start = max(end - overlap_chars, start + 1)
        if next_start <= start:
            next_start = end
        start = next_start
    return windows


def chunk_paper_sections(
    sections: list[tuple[str, str]],
    *,
    paper: EligiblePaper,
    rules: CorpusRules,
) -> tuple[list[CorpusUnit], ChunkMetrics]:
    """Build deterministic corpus units; reject empty or duplicate chunk hashes."""
    if not all(
        [
            paper.pmid,
            paper.pmcid,
            paper.artifact_id,
            paper.object_key,
            paper.jats_sha256,
            paper.text_sha256,
            paper.contribution_sha256,
        ]
    ):
        return [], ChunkMetrics(missing_provenance_rejections=1)

    units: list[CorpusUnit] = []
    seen_hashes: set[str] = set()
    empty = 0
    duplicates = 0
    chunk_index = 0
    cursor = 0
    for section_label, section_text in sections:
        windows = _window_text(
            section_text,
            target_chars=rules.target_chars,
            overlap_chars=rules.overlap_chars,
            min_chunk_chars=rules.min_chunk_chars,
        )
        if not windows and section_text.strip():
            empty += 1
        for local_start, local_end, chunk in windows:
            unit_hash = hashlib.sha256(chunk.encode()).hexdigest()
            if unit_hash in seen_hashes:
                duplicates += 1
                continue
            seen_hashes.add(unit_hash)
            unit_id = hashlib.sha256(
                f"{rules.rules_version}|{paper.pmid}|{chunk_index}|{unit_hash}".encode()
            ).hexdigest()
            units.append(
                CorpusUnit(
                    unit_id=unit_id,
                    pmid=paper.pmid,
                    pmcid=paper.pmcid,
                    artifact_id=paper.artifact_id,
                    object_key=paper.object_key,
                    jats_sha256=paper.jats_sha256,
                    text_sha256=paper.text_sha256,
                    contribution_sha256=paper.contribution_sha256,
                    chunk_index=chunk_index,
                    char_start=cursor + local_start,
                    char_end=cursor + local_end,
                    section_label=section_label,
                    unit_text=chunk,
                    unit_text_sha256=unit_hash,
                )
            )
            chunk_index += 1
        cursor += len(section_text) + 1
    return units, ChunkMetrics(
        empty_chunk_rejections=empty,
        duplicate_chunk_rejections=duplicates,
    )


def corpus_content_sha256(units: list[CorpusUnit]) -> str:
    """Hash the ordered unit identities for deterministic rebuild verification."""
    return corpus_content_sha256_from_rows(
        [(unit.pmid, unit.chunk_index, unit.unit_id, unit.unit_text_sha256) for unit in units]
    )


def corpus_content_sha256_from_rows(
    rows: list[tuple[str, int, str, str]],
) -> str:
    material = "\n".join(
        f"{pmid}:{chunk_index}:{unit_id}:{unit_hash}"
        for pmid, chunk_index, unit_id, unit_hash in sorted(
            rows, key=lambda item: (item[0], item[1])
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _spaces_client(settings: PipelineSettings) -> Any:
    assert settings.spaces_access_key_id is not None
    assert settings.spaces_secret_access_key is not None
    return boto3.client(
        "s3",
        endpoint_url=settings.spaces_endpoint,
        aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        region_name=settings.spaces_region,
        config=Config(signature_version="s3v4"),
    )


def _load_eligible_papers(cursor: Any, pmid: str | None) -> tuple[list[EligiblePaper], int]:
    """Return admitted processed papers and the count of excluded candidates.

    Steward approval is enforced by requiring ``processed`` plus a recorded
    ``final_review_decision_id``. Pipeline runtime cannot read review-decision
    rows directly; rejected papers never reach ``processed``.
    """
    cursor.execute(
        """
        SELECT p.pmid,
               COALESCE(a.pmcid, p.pmcid) AS pmcid,
               a.artifact_id,
               a.object_key,
               a.jats_sha256,
               a.text_sha256,
               r.contribution_sha256,
               p.state,
               p.final_review_decision_id
          FROM KNOWLEDGE_GRAPH.PAPERS p
          LEFT JOIN KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS a
            ON a.pmid = p.pmid
          LEFT JOIN KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
            ON r.pmid = p.pmid
         WHERE (%s IS NULL OR p.pmid = %s)
         ORDER BY p.pmid, r.published_at DESC NULLS LAST
        """,
        (pmid, pmid),
    )
    rows = cursor.fetchall()
    admitted: list[EligiblePaper] = []
    excluded = 0
    seen: set[str] = set()
    for row in rows:
        (
            paper_pmid,
            pmcid,
            artifact_id,
            object_key,
            jats_sha256,
            text_sha256,
            contribution_sha256,
            state,
            final_review_decision_id,
        ) = row
        if paper_pmid in seen:
            continue
        seen.add(paper_pmid)
        eligible = (
            state == "processed"
            and final_review_decision_id
            and artifact_id
            and object_key
            and jats_sha256
            and text_sha256
            and contribution_sha256
            and pmcid
        )
        if not eligible:
            excluded += 1
            continue
        admitted.append(
            EligiblePaper(
                pmid=str(paper_pmid),
                pmcid=str(pmcid),
                artifact_id=str(artifact_id),
                object_key=str(object_key),
                jats_sha256=str(jats_sha256),
                text_sha256=str(text_sha256),
                contribution_sha256=str(contribution_sha256),
            )
        )
    return admitted, excluded


def build_retrieval_corpus(
    *,
    settings: PipelineSettings | None = None,
    pmid: str | None = None,
    rules: CorpusRules | None = None,
    artifact_store: ArtifactStore | None = None,
) -> dict[str, object]:
    """Rebuild the DEV retrieval corpus from approved PMC artifacts only."""
    settings = settings or PipelineSettings()
    if settings.topx_env != "dev":
        raise ValueError("Retrieval corpus builds are DEV-only")
    rules = rules or CorpusRules()
    store = artifact_store or _spaces_client(settings)
    build_id = str(uuid.uuid4())
    rules_hash = rules.sha256()

    with connect(SnowflakeSettings()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS
              (build_id, corpus_rules_version, rules_sha256, status)
            VALUES (%s, %s, %s, 'running')
            """,
            (build_id, rules.rules_version, rules_hash),
        )
        try:
            papers, excluded = _load_eligible_papers(cursor, pmid)
            all_units: list[CorpusUnit] = []
            empty = 0
            duplicates = 0
            missing = 0
            for paper in papers:
                payload = store.get_object(Bucket=settings.spaces_bucket, Key=paper.object_key)[
                    "Body"
                ].read()
                admitted = admit_pmc_open_access(payload)
                if (
                    admitted.jats_sha256 != paper.jats_sha256
                    or admitted.text_sha256 != paper.text_sha256
                    or admitted.pmcid != paper.pmcid
                ):
                    missing += 1
                    continue
                sections = extract_section_texts(payload)
                units, metrics = chunk_paper_sections(sections, paper=paper, rules=rules)
                empty += metrics.empty_chunk_rejections
                duplicates += metrics.duplicate_chunk_rejections
                missing += metrics.missing_provenance_rejections
                all_units.extend(units)

            cursor.execute(
                """
                DELETE FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS
                 WHERE corpus_rules_version = %s
                   AND (%s IS NULL OR pmid = %s)
                """,
                (rules.rules_version, pmid, pmid),
            )
            for unit in all_units:
                cursor.execute(
                    """
                    INSERT INTO KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS (
                      unit_id, corpus_rules_version, build_id, pmid, pmcid, artifact_id,
                      object_key, jats_sha256, text_sha256, contribution_sha256, chunk_index,
                      char_start, char_end, section_label, unit_text, unit_text_sha256
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        unit.unit_id,
                        rules.rules_version,
                        build_id,
                        unit.pmid,
                        unit.pmcid,
                        unit.artifact_id,
                        unit.object_key,
                        unit.jats_sha256,
                        unit.text_sha256,
                        unit.contribution_sha256,
                        unit.chunk_index,
                        unit.char_start,
                        unit.char_end,
                        unit.section_label,
                        unit.unit_text,
                        unit.unit_text_sha256,
                    ),
                )
            cursor.execute(
                """
                SELECT pmid, chunk_index, unit_id, unit_text_sha256
                  FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS
                 WHERE corpus_rules_version = %s
                 ORDER BY pmid, chunk_index
                """,
                (rules.rules_version,),
            )
            content_hash = corpus_content_sha256_from_rows(
                [(str(row[0]), int(row[1]), str(row[2]), str(row[3])) for row in cursor.fetchall()]
            )
            cursor.execute(
                """
                UPDATE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS
                   SET status = 'completed',
                       papers_considered = %s,
                       papers_admitted = %s,
                       papers_excluded_unapproved = %s,
                       chunks_written = %s,
                       empty_chunk_rejections = %s,
                       duplicate_chunk_rejections = %s,
                       missing_provenance_rejections = %s,
                       corpus_content_sha256 = %s,
                       finished_at = CURRENT_TIMESTAMP()
                 WHERE build_id = %s
                """,
                (
                    len(papers) + excluded,
                    len(papers),
                    excluded,
                    len(all_units),
                    empty,
                    duplicates,
                    missing,
                    content_hash,
                    build_id,
                ),
            )
            connection.commit()
        except Exception as error:
            connection.rollback()
            with connect(SnowflakeSettings()) as fail_connection:
                fail_cursor = fail_connection.cursor()
                fail_cursor.execute(
                    """
                    UPDATE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS
                       SET status = 'failed',
                           redacted_error = %s,
                           finished_at = CURRENT_TIMESTAMP()
                     WHERE build_id = %s
                    """,
                    (type(error).__name__, build_id),
                )
                fail_connection.commit()
            raise

    result = {
        "status": "completed",
        "build_id": build_id,
        "corpus_rules_version": rules.rules_version,
        "rules_sha256": rules_hash,
        "papers_considered": len(papers) + excluded,
        "papers_admitted": len(papers),
        "papers_excluded_unapproved": excluded,
        "chunks_written": len(all_units),
        "empty_chunk_rejections": empty,
        "duplicate_chunk_rejections": duplicates,
        "missing_provenance_rejections": missing,
        "corpus_content_sha256": content_hash,
    }
    logger.info(
        "retrieval_corpus.build_completed build_id=%s rules=%s chunks=%s",
        build_id,
        rules.rules_version,
        len(all_units),
    )
    return result
