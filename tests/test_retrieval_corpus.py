"""Unit tests for deterministic retrieval-corpus chunking and eligibility gates."""

from __future__ import annotations

import hashlib

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    load_migrations,
    migration_plan,
    render_migration,
)
from lyme_gap_atlas_data.pmc_graph import admit_pmc_open_access
from lyme_gap_atlas_data.retrieval_corpus import (
    CORPUS_RULES_VERSION,
    CorpusRules,
    EligiblePaper,
    chunk_paper_sections,
    corpus_content_sha256,
    extract_section_texts,
)


def _jats(body: str) -> bytes:
    return f"""<article xml:lang="en" xmlns:xlink="http://www.w3.org/1999/xlink">
      <front><article-meta><article-id pub-id-type="pmc">PMC999</article-id>
      <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/" />
      </permissions></article-meta></front>
      <body>{body}</body>
    </article>""".encode()


def _paper(**overrides: object) -> EligiblePaper:
    values = {
        "pmid": "42472018",
        "pmcid": "PMC999",
        "artifact_id": "artifact-1",
        "object_key": "dev/pmc_full_text/42472018/abc.bin",
        "jats_sha256": "a" * 64,
        "text_sha256": "b" * 64,
        "contribution_sha256": "c" * 64,
    }
    values.update(overrides)
    return EligiblePaper(**values)  # type: ignore[arg-type]


def test_section_extraction_and_chunking_are_deterministic() -> None:
    jats = _jats(
        "<sec><title>Methods</title><p>" + ("Reviewed Lyme evidence sentence. " * 80) + "</p></sec>"
        "<sec><title>Results</title><p>Stable finding one. Stable finding two.</p></sec>"
    )
    admitted = admit_pmc_open_access(jats)
    sections = extract_section_texts(jats)
    assert sections[0][0] == "Methods"
    paper = _paper(jats_sha256=admitted.jats_sha256, text_sha256=admitted.text_sha256)
    first, metrics = chunk_paper_sections(sections, paper=paper, rules=CorpusRules())
    second, _ = chunk_paper_sections(sections, paper=paper, rules=CorpusRules())
    assert metrics.missing_provenance_rejections == 0
    assert first
    assert [unit.unit_id for unit in first] == [unit.unit_id for unit in second]
    assert corpus_content_sha256(first) == corpus_content_sha256(second)
    assert all(unit.pmid == "42472018" for unit in first)
    assert all(unit.contribution_sha256 == "c" * 64 for unit in first)


def test_missing_provenance_is_rejected() -> None:
    units, metrics = chunk_paper_sections(
        [("body", "Enough characters to form a valid chunk of evidence text.")],
        paper=_paper(artifact_id=""),
        rules=CorpusRules(),
    )
    assert units == []
    assert metrics.missing_provenance_rejections == 1


def test_duplicate_chunk_text_is_rejected_once() -> None:
    text = "Deterministic duplicate chunk text for QC coverage."
    units, metrics = chunk_paper_sections(
        [("A", text), ("B", text)],
        paper=_paper(),
        rules=CorpusRules(target_chars=200, overlap_chars=0, min_chunk_chars=10),
    )
    assert len(units) == 1
    assert metrics.duplicate_chunk_rejections == 1


def test_v065_retrieval_corpus_is_dev_only_and_queryable() -> None:
    migration = next(item for item in load_migrations() if item.version == "V065")
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V065" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    rendered = render_migration(migration, DEV_DATABASE)
    assert "RETRIEVAL_CORPUS_UNITS" in rendered
    assert "V_RETRIEVAL_CORPUS_BUILD_METRICS" in rendered
    assert "OH_LYME_DEV_PIPELINE_RUNTIME" in rendered
    assert "OH_LYME_DEV_PMC_AUDITOR" in rendered
    assert "DELETE ON TABLE KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS" in rendered
    assert CORPUS_RULES_VERSION == "retrieval-corpus-v1"
    assert len(hashlib.sha256(CorpusRules().sha256().encode()).hexdigest()) == 64
