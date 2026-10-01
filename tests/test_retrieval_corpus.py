"""Unit tests for deterministic retrieval-corpus chunking and eligibility gates."""

from __future__ import annotations

import hashlib
import uuid

import pytest

from lyme_gap_atlas_data import retrieval_corpus as module
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
    _load_eligible_papers,
    chunk_paper_sections,
    corpus_content_sha256,
    extract_section_texts,
)
from lyme_gap_atlas_data.settings import PipelineSettings


def test_batch_scoped_eligibility_uses_discovery_run_id() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.sql = ""
            self.args: object = None

        def execute(self, sql: str, args: object) -> None:
            self.sql, self.args = sql, args

        def fetchall(self) -> list[object]:
            return []

    cursor = Cursor()
    assert _load_eligible_papers(cursor, None, "run-1") == ([], 0)
    assert "ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids)" in cursor.sql
    assert cursor.args == (None, None, "run-1", "run-1")


def test_failed_corpus_build_retains_committed_discovery_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted: dict[str, tuple[str, str]] = {}
    actions: list[str] = []

    class Cursor:
        def execute(self, sql: str, args: tuple[object, ...]) -> None:
            if "INSERT INTO KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS" in sql:
                persisted[str(args[0])] = (str(args[3]), "running")
            elif "SET status = 'failed'" in sql:
                build_id = str(args[1])
                persisted[build_id] = (persisted[build_id][0], "failed")

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            actions.append("commit")

        def rollback(self) -> None:
            actions.append("rollback")

    def fail(*_args: object) -> None:
        raise RuntimeError("SECRET_ARTICLE_SENTINEL")

    monkeypatch.setattr(module, "connect", lambda _settings: Connection())
    monkeypatch.setattr(module, "_load_eligible_papers", fail)
    run_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="SECRET_ARTICLE_SENTINEL"):
        module.build_retrieval_corpus(
            discovery_run_id=run_id, settings=PipelineSettings(), artifact_store=object()
        )
    assert list(persisted.values()) == [(run_id, "failed")]
    assert actions == ["commit", "rollback", "commit"]


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


def test_v066_retrieval_corpus_is_env_neutral_with_api_lookup() -> None:
    migration = next(item for item in load_migrations() if item.version == "V066")
    prod = render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V066" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")}
    assert "SP_LOOKUP_RETRIEVAL_CORPUS_PROVENANCE" in prod
    assert "OH_LYME_PROD_PIPELINE_RUNTIME" in prod
    assert "OH_LYME_PROD_API_RUNTIME" in prod
    assert "OH_LYME_PROD_PMC_AUDITOR" in prod
    assert "unit_text" not in migration.source.split("CREATE OR REPLACE PROCEDURE", 1)[1]


def test_v067_kg_chat_budget_and_persist_fixes_are_env_neutral() -> None:
    migration = next(item for item in load_migrations() if item.version == "V067")
    prod = render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V067" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")}
    assert "INSERT INTO GOVERNANCE.LLM_BUDGET_USAGE (" in prod
    assert "SELECT UUID_STRING()" in prod
    assert "GET(value:passage_ids, 0)" in prod
    assert "OH_LYME_API_READER" in prod
    assert "OH_LYME_PROD_API_RUNTIME" in prod


@pytest.mark.parametrize("fail_batch", [False, True])
def test_corpus_batches_are_atomic_and_keep_durable_failure_history(
    monkeypatch: pytest.MonkeyPatch, fail_batch: bool
) -> None:
    from io import BytesIO

    actions: list[str] = []
    batches: list[list[tuple[object, ...]]] = []
    jats = _jats("<p>" + "Grounded Lyme evidence. " * 80 + "</p>")
    admitted = admit_pmc_open_access(jats)
    paper = _paper(jats_sha256=admitted.jats_sha256, text_sha256=admitted.text_sha256)
    units, _ = chunk_paper_sections(extract_section_texts(jats), paper=paper, rules=CorpusRules())
    assert len(units) > 1
    committed = [("old", 0, "old-unit", "old-hash")]
    pending: list[tuple[object, ...]] | None = None

    class Cursor:
        def execute(self, sql: str, args: object = None) -> None:
            nonlocal pending
            if sql == "BEGIN TRANSACTION":
                actions.append("begin")
                pending = list(committed)
            elif "DELETE FROM" in sql:
                assert pending is not None
                pending.clear()
                actions.append("delete")
            elif "INSERT INTO KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS" in sql:
                pytest.fail("per-unit inserts must not return")
            elif "SET status = 'failed'" in sql:
                assert args is not None and args[0] == "RuntimeError"
                actions.append("failed")

        def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
            assert "INSERT INTO KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS" in sql
            assert pending is not None
            batches.append(rows)
            if fail_batch and len(batches) == 2:
                raise RuntimeError("PRIVATE_SENTINEL")
            pending.extend((r[3], r[10], r[0], r[15]) for r in rows)

        def fetchall(self) -> list[tuple[object, ...]]:
            assert pending is not None
            return list(pending)

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            nonlocal pending
            actions.append("commit")
            if pending is not None:
                committed[:] = pending
                pending = None

        def rollback(self) -> None:
            nonlocal pending
            actions.append("rollback")
            pending = None

    class Store:
        def get_object(self, **_kwargs: object) -> dict[str, object]:
            return {"Body": BytesIO(jats)}

    monkeypatch.setattr(module, "connect", lambda _settings: Connection())
    monkeypatch.setattr(module, "_load_eligible_papers", lambda *_args: ([paper], 0))
    monkeypatch.setattr(module, "CORPUS_INSERT_BATCH_SIZE", 1)
    if fail_batch:
        with pytest.raises(RuntimeError, match="PRIVATE_SENTINEL"):
            module.build_retrieval_corpus(settings=PipelineSettings(), artifact_store=Store())
        assert committed == [("old", 0, "old-unit", "old-hash")]
        assert actions == ["commit", "begin", "delete", "rollback", "failed", "commit"]
    else:
        result = module.build_retrieval_corpus(settings=PipelineSettings(), artifact_store=Store())
        assert result["chunks_written"] == len(units)
        assert result["corpus_content_sha256"] == corpus_content_sha256(units)
        assert actions == ["commit", "begin", "delete", "commit"]
        assert [r[0] for batch in batches for r in batch] == [u.unit_id for u in units]
        assert all(len(batch) == 1 for batch in batches)
