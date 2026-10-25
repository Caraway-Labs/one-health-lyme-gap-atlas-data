"""Forward repair preserves the reviewed admission policy without correlation."""

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_CDC_MMWR_DAILY_ACTIVATION_MIGRATION,
    PROD_DATABASE,
    PROD_INTELLIGENCE_VIEW_COMPATIBILITY_MIGRATION,
    PROD_NIH_NEWS_DAILY_ACTIVATION_MIGRATION,
    migration_plan,
)

ROOT = Path(__file__).parents[1]


def test_forward_join_preserves_exact_admission_predicate_and_projection():
    old = (ROOT / "migrations/V164__prod_intelligence_daily_activation_view.sql").read_text()
    new = (
        ROOT / "migrations" / PROD_INTELLIGENCE_VIEW_COMPATIBILITY_MIGRATION["filename"]
    ).read_text()
    original = old.split("        AND NOT COALESCE((", 1)[1].split("        ),FALSE)", 1)[0]
    replacement = new.split("    WHERE NOT COALESCE((", 1)[1].split("        ),FALSE)", 1)[0]

    def normalize(value):
        return re.sub(r"\s+", "", value)

    assert normalize(original) == normalize(replacement)
    assert "NOT EXISTS" not in new
    assert "LEFT JOIN blocked_source_versions blocked" in new
    assert "AND blocked.source_id IS NULL" in new
    assert old.split("SELECT c.item_id", 1)[1].split("WHERE c.item_document", 1)[0] in new.replace(
        "LEFT JOIN blocked_source_versions blocked\n"
        "  ON blocked.source_id = s.source_id AND blocked.registry_version = s.registry_version\n",
        "",
    )
    assert old.split("QUALIFY ROW_NUMBER()", 1)[1] == new.split("QUALIFY ROW_NUMBER()", 1)[1]


def test_repair_is_append_only_pinned_and_prod_only():
    expected = PROD_INTELLIGENCE_VIEW_COMPATIBILITY_MIGRATION
    path = ROOT / "migrations" / expected["filename"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]
    assert expected in migration_plan(PROD_DATABASE)
    assert expected not in migration_plan(DEV_DATABASE)


def _daily_activation_predicate(sql: str) -> str:
    return sql.split("    WHERE NOT COALESCE((", 1)[1].split("        ),FALSE)", 1)[0]


def test_nih_activation_extends_v165_predicate_without_projection_drift():
    prior_path = ROOT / "migrations" / PROD_INTELLIGENCE_VIEW_COMPATIBILITY_MIGRATION["filename"]
    updated_path = ROOT / "migrations" / PROD_NIH_NEWS_DAILY_ACTIVATION_MIGRATION["filename"]
    prior = prior_path.read_text()
    updated = updated_path.read_text()
    prior_predicate = _daily_activation_predicate(prior)
    updated_predicate = _daily_activation_predicate(updated)

    def normalize(value):
        return re.sub(r"\s+", "", value)

    without_nih = re.sub(
        r" WHEN 'nih-news-releases' THEN '[0-9a-f]{64}'",
        "",
        updated_predicate,
    )

    assert normalize(without_nih) == normalize(prior_predicate)
    assert updated_predicate.count("nih-news-releases") == 2
    assert prior.split("SELECT c.item_id", 1)[1] == updated.split("SELECT c.item_id", 1)[1]


def test_nih_activation_migration_is_append_only_pinned_and_prod_only():
    expected = PROD_NIH_NEWS_DAILY_ACTIVATION_MIGRATION
    path = ROOT / "migrations" / expected["filename"]
    digest = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
    assert digest == expected["sha256"]
    assert expected in migration_plan(PROD_DATABASE)
    assert expected not in migration_plan(DEV_DATABASE)


def test_cdc_mmwr_activation_extends_v166_predicate_without_projection_drift():
    prior_path = ROOT / "migrations" / PROD_NIH_NEWS_DAILY_ACTIVATION_MIGRATION["filename"]
    updated_path = ROOT / "migrations" / PROD_CDC_MMWR_DAILY_ACTIVATION_MIGRATION["filename"]
    prior = prior_path.read_text()
    updated = updated_path.read_text()
    prior_predicate = _daily_activation_predicate(prior)
    updated_predicate = _daily_activation_predicate(updated)

    def normalize(value):
        return re.sub(r"\s+", "", value)

    without_mmwr = re.sub(
        r" WHEN 'cdc-mmwr' THEN '[0-9a-f]{64}'",
        "",
        updated_predicate,
    )

    assert normalize(without_mmwr) == normalize(prior_predicate)
    assert updated_predicate.count("cdc-mmwr") == 2
    assert prior.split("SELECT c.item_id", 1)[1] == updated.split("SELECT c.item_id", 1)[1]


_ABSTRACT_COLUMN = """       (
           pmid_suppression.pmid IS NOT NULL
           OR publisher_suppression.publisher IS NOT NULL
       ) AS abstract_suppressed,
"""
_ABSTRACT_KEYS = """,
           'abstract', IFF(
               pmid_suppression.pmid IS NOT NULL
               OR publisher_suppression.publisher IS NOT NULL,
               OBJECT_CONSTRUCT_KEEP_NULL(
                   'text', NULL,
                   'state', 'suppressed',
                   'copyright_line', NULL
               ),
               c.item_document:publisher_metadata:abstract
           ),
           'mesh', c.item_document:publisher_metadata:mesh,
           'publication_types', c.item_document:publisher_metadata:publication_types,
           'matched_queries', c.item_document:publisher_metadata:matched_queries,
           'abstract_suppressed',
               pmid_suppression.pmid IS NOT NULL
               OR publisher_suppression.publisher IS NOT NULL"""
_SUPPRESSION_JOINS = """LEFT JOIN (
    SELECT pmid
    FROM GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS
    WHERE scope = 'PMID'
      AND pmid IS NOT NULL
    GROUP BY pmid
) pmid_suppression
  ON pmid_suppression.pmid = c.item_document:publisher_metadata:source_item_id::VARCHAR
 AND c.item_document:publisher_metadata:source_family::VARCHAR = 'pubmed'
 AND c.item_document:publisher_metadata:source_item_id::VARCHAR RLIKE '^[1-9][0-9]{0,9}$'
LEFT JOIN (
    SELECT publisher
    FROM GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS
    WHERE scope = 'PUBLISHER'
      AND publisher IS NOT NULL
    GROUP BY publisher
) publisher_suppression
  ON publisher_suppression.publisher = c.item_document:publisher_metadata:journal::VARCHAR
 AND c.item_document:publisher_metadata:source_family::VARCHAR = 'pubmed'
"""


def _feed_view(filename: str) -> str:
    source = (ROOT / "migrations" / filename).read_text(encoding="utf-8")
    return source[source.index("CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2") :]


def test_v175_view_keeps_v173_body_and_one_active_activation_join():
    previous = _feed_view("V173__intelligence_feed_v2_description.sql")
    updated = _feed_view("V175__intelligence_abstract_suppressions_feed_v2.sql")
    assert updated.count("JOIN GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS") == 1
    assert updated.count("a.state = 'ACTIVE'") == 1
    assert "COPY GRANTS" in updated
    assert updated.count(_ABSTRACT_COLUMN) == 1
    assert updated.count(_ABSTRACT_KEYS) == 1
    assert updated.count(_SUPPRESSION_JOINS) == 1
    stripped = (
        updated.replace(_ABSTRACT_COLUMN, "", 1)
        .replace(_ABSTRACT_KEYS, "", 1)
        .replace(_SUPPRESSION_JOINS, "", 1)
    )
    assert stripped == previous
    assert "6000" not in updated
    assert "SUBSTR" not in updated.upper()
    assert "QUERY_TEXT" not in updated.upper()
    assert "ERROR_MESSAGE" not in updated.upper()
    assert "'suppressed'" in updated
    for invented in ("'present'", "'withheld'", "'empty'", "'not_provided'"):
        assert invented not in updated


def test_cdc_mmwr_activation_migration_is_append_only_pinned_and_prod_only():
    expected = PROD_CDC_MMWR_DAILY_ACTIVATION_MIGRATION
    path = ROOT / "migrations" / expected["filename"]
    digest = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
    assert digest == expected["sha256"]
    assert expected in migration_plan(PROD_DATABASE)
    assert expected not in migration_plan(DEV_DATABASE)


def test_real_dev_acceptance_uses_actual_full_query_and_inline_selects_only():
    path = ROOT / "scripts/verify_intelligence_daily_view_dev.py"
    spec = importlib.util.spec_from_file_location("view_dev_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    query, expected = module.acceptance_sql()
    assert expected["cdc-eid-ahead-of-print:active"] == (1, 1)
    assert expected["example-blocked-feed:blocked_v1"] == (1, 2)
    assert expected["example-new-feed:new_source"] == (1, 2)
    assert "example-blocked-feed" not in (ROOT / "migrations" / module.MIGRATION).read_text()
    assert "example-new-feed" not in (ROOT / "migrations" / module.MIGRATION).read_text()
    assert "GOVERNANCE." not in query and "CONFORMED." not in query
    assert "CREATE" not in query and "INSERT" not in query
    assert "blocked_source_versions" not in query and "CASE" not in query
    assert query.count("JOIN fixture_activations") == len(expected)
    assert query.count("a.state = 'ACTIVE'") == len(expected)
    blocked = module.fixture_query("cdc-eid-ahead-of-print", "blocked_v1")
    assert "'BLOCKED'" in blocked and "example-blocked-feed" in blocked
    assert "cdc-eid-ahead-of-print" not in blocked
    assert "ATLAS_DEV_READ" in path.read_text()
    assert " AS ROWS" not in query


def test_snow_cli_nested_statement_results_and_safe_error_details(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "view_cli_acceptance", ROOT / "scripts/verify_intelligence_daily_view_dev.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = {
        "U": "MATTHEWCARAWAY",
        "R": "OH_LYME_DEV_OWNER",
        "D": module.DATABASE,
        "W": "OH_LYME_DEV_INGEST_XS_WH",
    }
    nested = [[{"status": "Statement executed successfully."}], [context]]
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(nested), stderr=""),
    )
    assert module.sql("SELECT CURRENT_USER()", view_object=True) == [nested[0][0], context]
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="001003 (42000): SQL compilation error:\n"
            "syntax error line 1 at position 52 unexpected 'ROWS'.",
        ),
    )
    with pytest.raises(RuntimeError, match="001003:42000.*unexpected 'ROWS'"):
        module.sql("SELECT 1", view_object=True)
