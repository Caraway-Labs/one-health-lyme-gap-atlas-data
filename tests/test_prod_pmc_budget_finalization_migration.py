"""PROD finalization must match the worker without changing reservation logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)


def test_prod_budget_finalization_contract() -> None:
    migrations = {migration.version: migration for migration in load_migrations()}
    prod_plan = {item["version"] for item in migration_plan(PROD_DATABASE)}
    dev_plan = {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert {"V130", "V131"} <= prod_plan
    assert {"V130", "V131"}.isdisjoint(dev_plan)
    for version in ("V130", "V131"):
        with pytest.raises(ValueError, match="PROD-only"):
            render_migration(migrations[version], DEV_DATABASE)

    ledger = render_migration(migrations["V130"], PROD_DATABASE).upper()
    procedure = render_migration(migrations["V131"], PROD_DATABASE).upper()
    assert "CREATE TABLE IF NOT EXISTS GOVERNANCE.LLM_BUDGET_FINALIZATIONS" in ledger
    assert "UNIQUE (WORKLOAD, REQUEST_ID)" in ledger
    assert "CHECK (STATUS IN ('USED', 'FAILED'))" in ledger
    assert (
        "GRANT SELECT, INSERT ON TABLE GOVERNANCE.LLM_BUDGET_FINALIZATIONS\n"
        "  TO ROLE OH_LYME_PROD_KG_LLM_BUDGET_OWNER"
    ) in ledger
    assert "OH_LYME_PROD_RUNTIME" not in ledger
    assert (
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(\n"
        "  WORKLOAD VARCHAR, REQUEST_ID VARCHAR, STATUS VARCHAR, ACTUAL_COST_USD NUMBER"
    ) in procedure
    assert "EXECUTE AS OWNER" in procedure
    assert "SP_RESERVE_KG_LLM_BUDGET(" not in procedure
    assert (
        "GRANT USAGE ON PROCEDURE "
        "GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(VARCHAR, VARCHAR, VARCHAR, NUMBER)\n"
        "  TO ROLE OH_LYME_PROD_RUNTIME"
    ) in procedure
    assert migration_execution_role(migrations["V131"], PROD_DATABASE) == (
        "OH_LYME_PROD_KG_LLM_BUDGET_OWNER"
    )
    worker = (
        Path(__file__).parents[1] / "src/lyme_gap_atlas_data/pmc_extraction_worker.py"
    ).read_text()
    assert "CALL GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(%s,%s,%s,%s)" in worker

