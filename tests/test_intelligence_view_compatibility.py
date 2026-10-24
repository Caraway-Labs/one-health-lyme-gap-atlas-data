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


def test_nih_activation_extends_v165_predicate_without_projection_drift():
    prior = (ROOT / "migrations" / PROD_INTELLIGENCE_VIEW_COMPATIBILITY_MIGRATION["filename"]).read_text()
    updated = (ROOT / "migrations" / PROD_NIH_NEWS_DAILY_ACTIVATION_MIGRATION["filename"]).read_text()
    prior_predicate = prior.split("    WHERE NOT COALESCE((", 1)[1].split("        ),FALSE)", 1)[0]
    updated_predicate = updated.split("    WHERE NOT COALESCE((", 1)[1].split("        ),FALSE)", 1)[0]

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


def test_real_dev_acceptance_uses_actual_full_query_and_inline_selects_only():
    path = ROOT / "scripts/verify_intelligence_daily_view_dev.py"
    spec = importlib.util.spec_from_file_location("view_dev_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    query, expected = module.acceptance_sql()
    assert len(expected) == 24
    assert "GOVERNANCE." not in query and "CONFORMED." not in query
    assert "CREATE" not in query and "INSERT" not in query
    assert query.count("LEFT JOIN blocked_source_versions blocked") == 24
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
