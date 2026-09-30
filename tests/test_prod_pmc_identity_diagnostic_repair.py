"""The incident repair must match the already reviewed DEV diagnostic contract."""

import re
from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "scripts" / "repair_prod_pmc_identity_diagnostic.sql"
RECOVERY = ROOT / "scripts" / "recover_prod_pmc_identity_attempt.sql"
TYPES = {
    "dropped_illegal_edge",
    "contribution_validation_failure",
    "partial_accept_summary",
    "identity_mismatch",
}


def test_prod_constraint_repair_matches_dev_and_adds_no_privileges() -> None:
    dev = next(m.source for m in load_migrations() if m.version == "V064")
    repair = REPAIR.read_text(encoding="utf-8")
    assert all(f"'{name}'" in dev and f"'{name}'" in repair for name in TYPES)
    assert repair.count("ADD CONSTRAINT ck_extraction_attempt_diagnostic_type") == 2
    assert repair.count("DROP CONSTRAINT ck_extraction_attempt_diagnostic_type;") == 1
    assert "CURRENT_ROLE() <> 'ACCOUNTADMIN'" in repair
    assert "INFORMATION_SCHEMA.CHECK_CONSTRAINTS" in repair
    assert "INFORMATION_SCHEMA.COLUMNS" in repair
    assert "IS_NULLABLE" in repair.upper()
    assert "GET_DDL('TABLE'" not in repair
    add_temp = repair.index("ADD CONSTRAINT ck_extraction_attempt_diagnostic_type_data495")
    drop_old = repair.index("DROP CONSTRAINT ck_extraction_attempt_diagnostic_type;")
    add_final = repair.index("ADD CONSTRAINT ck_extraction_attempt_diagnostic_type CHECK")
    assert add_temp < drop_old < add_final
    assert "new_count = 1 AND temp_count = 1" in repair
    assert "old_count <> 1 AND temp_count <> 1" in repair
    assert not re.search(r"(?im)^\s*(GRANT|REVOKE)\s+", repair)


def test_stranded_attempt_cleanup_is_exact_and_counts_failure() -> None:
    sql = RECOVERY.read_text(encoding="utf-8")
    assert "917b97aa-cb5c-43dc-9ff1-5d17e461b843" in sql
    assert "a.pmid = '39307534' AND a.attempt_number = 1" in sql
    assert sql.count("a.lease_expires_at < CURRENT_TIMESTAMP()") >= 2
    assert "p.state = 'extracting'" in sql
    assert sql.count("GRAPH_PUBLICATION_RECEIPTS") >= 3
    assert sql.count("newer.attempt_number >") >= 3
    update_attempt = sql.split("UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS", 1)[1].split(
        "rows_changed := SQLROWCOUNT", 1
    )[0]
    assert "lease_expires_at < CURRENT_TIMESTAMP()" in update_attempt
    assert "p.state = 'extracting'" in update_attempt
    assert "GRAPH_PUBLICATION_RECEIPTS" in update_attempt
    assert "newer.attempt_number > 1" in update_attempt
    assert "status = 'failed'" in sql
    assert "error_class = 'ContributionIdentityError'" in sql
    assert "state = 'retry_pending'" in sql
    assert "PAPER_STATE_EVENTS" in sql
    assert "rows_changed <> 1" in sql
    assert "ROLLBACK;" in sql
    assert "LLM_BUDGET_USAGE" not in sql
    assert "EXTRACTION_ATTEMPT_CLASSIFICATIONS" not in sql
