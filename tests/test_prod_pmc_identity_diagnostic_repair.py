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
    assert repair.count("ADD CONSTRAINT ck_extraction_attempt_diagnostic_type") == 1
    assert repair.count("DROP CONSTRAINT ck_extraction_attempt_diagnostic_type") == 1
    assert "CURRENT_ROLE() <> 'ACCOUNTADMIN'" in repair
    assert "GET_DDL('TABLE'" in repair
    assert not re.search(r"(?im)^\s*(GRANT|REVOKE)\s+", repair)


def test_stranded_attempt_cleanup_is_exact_and_counts_failure() -> None:
    sql = RECOVERY.read_text(encoding="utf-8")
    assert "917b97aa-cb5c-43dc-9ff1-5d17e461b843" in sql
    assert "a.pmid = '39307534' AND a.attempt_number = 1" in sql
    assert "a.lease_expires_at < CURRENT_TIMESTAMP()" in sql
    assert "p.state = 'extracting'" in sql
    assert "GRAPH_PUBLICATION_RECEIPTS" in sql
    assert "status = 'failed'" in sql
    assert "error_class = 'ContributionIdentityError'" in sql
    assert "state = 'retry_pending'" in sql
    assert "PAPER_STATE_EVENTS" in sql
    assert "rows_changed <> 1" in sql
    assert "ROLLBACK;" in sql
    assert "LLM_BUDGET_USAGE" not in sql
    assert "EXTRACTION_ATTEMPT_CLASSIFICATIONS" not in sql
