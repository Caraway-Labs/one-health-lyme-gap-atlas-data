from pathlib import Path


def test_runtime_receipt_grant_is_bounded() -> None:
    sql = (
        Path(__file__).parents[1]
        / "migrations/V125__dev_dataset_discovery_runtime_handoff_receipts.sql"
    ).read_text()
    assert "GRANT SELECT ON VIEW DATASET_DISCOVERY.V_HANDOFF_RECEIPTS" in sql
    assert "TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME" in sql
    assert "GRANT USAGE ON PROCEDURE" not in sql
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    assert "DELETE" not in sql
