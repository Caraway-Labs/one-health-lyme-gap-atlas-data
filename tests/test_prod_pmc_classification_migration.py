"""The PROD classification ledger must satisfy the deployed PMC worker."""

from __future__ import annotations

import inspect
import re

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
    render_migration,
)
from lyme_gap_atlas_data.pmc_extraction_worker import SnowflakePMCExtractionLedger


def _migration_sql() -> str:
    migration = next(item for item in load_migrations() if item.version == "V129")
    return render_migration(migration, PROD_DATABASE)


def test_prod_classification_shape_and_append_only_runtime_grant() -> None:
    sql = _migration_sql().upper()
    assert "CREATE TABLE IF NOT EXISTS KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS" in sql
    for column in (
        "CLASSIFICATION_ID VARCHAR PRIMARY KEY",
        "EXTRACTION_ATTEMPT_ID VARCHAR NOT NULL",
        "PMID VARCHAR NOT NULL",
        "CLASSIFICATION VARCHAR NOT NULL",
        "RATIONALE VARCHAR NOT NULL",
        "CORRELATION_ID VARCHAR NOT NULL",
        "RECORDED_AT TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()",
    ):
        assert column in sql
    assert "UNIQUE (EXTRACTION_ATTEMPT_ID, CLASSIFICATION)" in sql
    assert re.search(
        r"CHECK\s*\(\s*CLASSIFICATION IN\s*\(\s*"
        r"'PROVIDER_REJECTED_PRE_INFERENCE'\s*,\s*"
        r"'CONTRACT_REMEDIATION_REOPEN'\s*\)\s*\)",
        sql,
    )
    grants = re.findall(r"(?im)^GRANT\s+.+?;", sql, flags=re.DOTALL)
    assert len(grants) == 1
    assert re.sub(r"\s+", " ", grants[0]).strip() == (
        "GRANT SELECT, INSERT ON TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS "
        "TO ROLE OH_LYME_PROD_RUNTIME;"
    )
    assert not re.search(r"\b(UPDATE|DELETE|TRUNCATE|MERGE INTO|GRANT OWNERSHIP)\b", sql)


def test_prod_migration_is_scoped_repeatable_and_matches_worker_queries() -> None:
    migration = next(item for item in load_migrations() if item.version == "V129")
    assert "V129" in {item["version"] for item in migration_plan(PROD_DATABASE)}
    assert "V129" not in {item["version"] for item in migration_plan(DEV_DATABASE)}
    with pytest.raises(ValueError, match="PROD-only"):
        render_migration(migration, DEV_DATABASE)
    sql = _migration_sql().upper()
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 1
    assert "CREATE OR REPLACE" not in sql
    source = inspect.getsource(SnowflakePMCExtractionLedger)
    assert source.count("KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS") >= 3
    assert "provider_rejected_pre_inference" in source
    assert "contract_remediation_reopen" in source
    assert "INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS" in source
    claim_sql = inspect.getsource(SnowflakePMCExtractionLedger.claim_one)
    claim_columns = set(re.findall(r"\bc\.([a-z_]+)", claim_sql))
    assert claim_columns == {"extraction_attempt_id", "classification"}
    for column in claim_columns:
        assert re.search(rf"\b{column.upper()} VARCHAR NOT NULL\b", sql)
    insert_columns_match = re.search(
        r"INSERT INTO KNOWLEDGE_GRAPH\.EXTRACTION_ATTEMPT_CLASSIFICATIONS\s*\(([^)]+)\)",
        source,
    )
    assert insert_columns_match is not None
    insert_columns = {item.strip() for item in insert_columns_match.group(1).split(",")}
    assert insert_columns == {
        "classification_id",
        "extraction_attempt_id",
        "pmid",
        "classification",
        "rationale",
        "correlation_id",
    }
    for column in insert_columns:
        assert re.search(rf"\b{column.upper()} VARCHAR\b", sql)
