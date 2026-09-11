from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import cdc
from lyme_gap_atlas_data import cdc_historical_ingestion as historical
from lyme_gap_atlas_data.cdc_policy import metadata_fingerprint, snapshot_checksum
from lyme_gap_atlas_data.cdc_quality import CdcQualityError
from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration


def connection_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = 1
    monkeypatch.setattr(historical, "connect", lambda _: connection)
    return connection, cursor


@pytest.mark.parametrize("action", ["refresh", "recover", "publish", "rollback", "quality"])
def test_unisolated_environment_rejected_before_io(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    monkeypatch.setattr(historical, "PipelineSettings", lambda: SimpleNamespace(topx_env="alpha"))
    connect = MagicMock()
    fetch = MagicMock()
    monkeypatch.setattr(historical, "connect", connect)
    monkeypatch.setattr(historical, "_fetch_json", fetch)
    with pytest.raises(ValueError, match="isolated DEV or PROD"):
        if action == "refresh":
            historical.refresh_historical("source")
        elif action == "recover":
            historical.recover_historical("source", "run")
        elif action == "publish":
            historical.publish("source", "run", "validation", "lease", 0)
        elif action == "quality":
            historical.record_quality("source", "run", 5)
        else:
            historical.rollback_historical("source", "run", 1)
    connect.assert_not_called()
    fetch.assert_not_called()


def test_direct_loader_cannot_bypass_environment_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cdc, "PipelineSettings", lambda: SimpleNamespace(topx_env="alpha"))
    with pytest.raises(ValueError, match="isolated DEV or PROD"):
        cdc.ingest_approved_cdc(dataset_id="qtbi-xd4i")


def test_prod_historical_operation_requires_exact_prod_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(historical, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    connection, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.return_value = (
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "OH_LYME_PROD_PIPELINE_RUNTIME",
    )
    with historical.historical_operation():
        pass
    assert any("CURRENT_DATABASE" in call.args[0] for call in cursor.execute.call_args_list)


def test_prod_historical_operation_rejects_dev_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(historical, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    _, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.return_value = (
        "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "OH_LYME_DEV_PIPELINE_RUNTIME",
    )
    with (
        pytest.raises(ValueError, match="isolated environment runtime"),
        historical.historical_operation(),
    ):
        pass


@pytest.mark.parametrize("page", [[{"year": "2022"}], [{"year": None}], [1], [], [{}]])
def test_reject_invalid_pages(page: list) -> None:
    with pytest.raises(ValueError):
        historical.validate_page(page, 5)


def test_source_values_preserved_without_invented_key() -> None:
    page = [
        {"year": "2008", "frequency": 0, "fips": "00123"},
        {"year": "2021", "frequency": None, "sex": "Unknown"},
        {"year": "2010", "frequency": "Suppressed"},
    ]
    original = deepcopy(page)
    historical.validate_page(page, 5)
    assert page == original
    with pytest.raises(ValueError, match="bound"):
        historical.validate_page(page, 2)


def test_historical_checks_are_run_scoped_and_never_read_current_era() -> None:
    sql = historical.quality_sql(historical.CANDIDATE)
    assert "X5J9" not in sql
    assert sql.count("WHERE data_source_version_id = %s AND ingestion_run_id = %s") == 2
    assert "NOT BETWEEN 2008 AND 2021" in sql
    assert "source_value_status:frequency" in sql
    assert "IS_NULL_VALUE(payload:frequency)" in sql
    assert "duplicate_source_hash" in sql
    with pytest.raises(ValueError):
        historical.quality_sql("RAW.ARBITRARY")


def test_failed_quality_is_persisted_before_rejecting(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.side_effect = [(1,), (4,)]
    cursor.fetchall.return_value = [("run", str(i), 0, 0) for i in range(10)]
    with pytest.raises(CdcQualityError, match="persisted"):
        historical.record_quality("source", "run", 5)
    connection.commit.assert_called_once()
    inserts = [c for c in cursor.execute.call_args_list if "INSERT INTO" in c.args[0]]
    assert len(inserts) == 11
    assert inserts[-1].args[1][3] == "FAILED"


@pytest.mark.parametrize("failure", ["approval", "quality", "revision", "copy", "retained"])
def test_publication_failure_preserves_pointer(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    connection, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.side_effect = [
        (0,) if failure == "approval" else (1,),
        (10, 0) if failure == "quality" else (11, 0),
        (2 if failure == "revision" else 1, "old", "old-run"),
        (0,),
    ]
    cursor.fetchall.side_effect = [
        [("a" * 64,)],
        [("run", str(i), 0, 1 if failure == "retained" else 0) for i in range(10)],
    ]
    if failure == "copy":

        def execute(sql: str, *_: object) -> None:
            if "INSERT INTO CONFORMED" in sql:
                cursor.rowcount = 0

        cursor.execute.side_effect = execute
    with pytest.raises((ValueError, CdcQualityError)):
        historical.publish("source", "run", "validation", "lease", 1)
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()
    assert not any(
        "UPDATE GOVERNANCE.CDC_PUBLICATIONS" in c.args[0] for c in cursor.execute.call_args_list
    )


def test_unchanged_data_does_not_advance_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    connection, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.side_effect = [(1,), (11, 0), (1, snapshot_checksum(["a" * 64]), "old-run")]
    cursor.fetchall.return_value = [("a" * 64,)]
    result = historical.publish("source", "run", "validation", "lease", 1)
    assert result == {"status": "UNCHANGED", "ingestion_run_id": "old-run"}
    assert not any("INSERT" in c.args[0] for c in cursor.execute.call_args_list)
    connection.commit.assert_called_once()


def test_approval_missing_prevents_publisher_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.return_value = (0,)
    monkeypatch.setattr(historical, "historical_operation", lambda: nullcontext("lease"))
    fetch = MagicMock()
    monkeypatch.setattr(historical, "_fetch_json", fetch)
    with pytest.raises(ValueError, match="approved"):
        historical.refresh_historical("bae8827a-d5cd-4451-acd0-e5ae2f8c7bb3")
    fetch.assert_not_called()


def test_historical_recovery_uses_exact_retained_run_without_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "5f8d78de-90f0-477e-aea4-a438e9a4ab66"
    run = "349c1710-e48b-4733-87ad-bbd9a7401bb7"
    _, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.side_effect = [(1,), ("COMPLETED",), (40_468, 9), (40_468,), None]
    monkeypatch.setattr(historical, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    monkeypatch.setattr(historical, "historical_operation", lambda: nullcontext("lease"))
    fetch = MagicMock()
    acquire = MagicMock()
    dbt = MagicMock()
    quality = MagicMock(return_value="validation")
    publish = MagicMock(return_value={"status": "PUBLISHED", "ingestion_run_id": run})
    monkeypatch.setattr(historical, "_fetch_json", fetch)
    monkeypatch.setattr(historical, "ingest_approved_cdc", acquire)
    monkeypatch.setattr(historical, "run_cdc_dbt", dbt)
    monkeypatch.setattr(historical, "record_quality", quality)
    monkeypatch.setattr(historical, "publish", publish)

    result = historical.recover_historical(source, run)

    assert result == {
        "source_version_id": source,
        "ingestion_run_id": run,
        "raw_rows": 40_468,
        "request_pages": 9,
        "quality_checks": 11,
        "publication": {"status": "PUBLISHED", "ingestion_run_id": run},
        "status": "COMPLETED",
    }
    dbt.assert_called_once_with("stg_cdc_lyme_qtbi_xd4i+")
    quality.assert_called_once_with(source, run, 40_468)
    publish.assert_called_once_with(source, run, "validation", "lease", 0)
    fetch.assert_not_called()
    acquire.assert_not_called()
    assert any(
        "resource_key=%s" in call.args[0] and call.args[1] == (run, historical.RESOURCE_KEY)
        for call in cursor.execute.call_args_list
    )


def test_historical_recovery_rejects_unreconciled_raw_before_dbt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.side_effect = [(1,), ("COMPLETED",), (40_468, 9), (40_467,)]
    monkeypatch.setattr(historical, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    monkeypatch.setattr(historical, "historical_operation", lambda: nullcontext("lease"))
    dbt = MagicMock()
    monkeypatch.setattr(historical, "run_cdc_dbt", dbt)

    with pytest.raises(ValueError, match="reconciled retained RAW"):
        historical.recover_historical(
            "5f8d78de-90f0-477e-aea4-a438e9a4ab66",
            "349c1710-e48b-4733-87ad-bbd9a7401bb7",
        )
    dbt.assert_not_called()


def test_metadata_fingerprint_requires_exact_publisher_identity() -> None:
    data = {"id": "qtbi-xd4i", "rowsUpdatedAt": 1, "columns": [{"fieldName": "year"}]}
    assert len(metadata_fingerprint(data, dataset_id="qtbi-xd4i")) == 64
    with pytest.raises(ValueError, match="identity"):
        metadata_fingerprint(data)


@pytest.mark.parametrize("frequency", ["0.5", "-1", "NaN", "Infinity", "unexpected"])
def test_frequency_cannot_be_silently_rounded(frequency: str) -> None:
    with pytest.raises(ValueError):
        historical.validate_page([{"year": "2008", "frequency": frequency}], 1)


@pytest.mark.parametrize("rollback", [False, True])
def test_publication_and_rollback_validate_before_updating_pointer(
    monkeypatch: pytest.MonkeyPatch,
    rollback: bool,
) -> None:
    connection, cursor = connection_fixture(monkeypatch)
    cursor.fetchone.side_effect = [(1,), (11, 0), (2, "old", "old-run"), (1,) if rollback else (0,)]
    cursor.fetchall.side_effect = [[("a" * 64,)], [("run", str(i), 0, 0) for i in range(10)]]
    result = historical.publish("source", "run", "validation", "lease", 2, rollback=rollback)
    assert result["status"] == "PUBLISHED"
    calls = cursor.execute.call_args_list
    validate = next(i for i, c in enumerate(calls) if "WITH raw AS" in c.args[0])
    update = next(
        i for i, c in enumerate(calls) if "UPDATE GOVERNANCE.CDC_PUBLICATIONS" in c.args[0]
    )
    assert validate < update
    assert not any("DELETE" in c.args[0] for c in calls)
    if rollback:
        assert not any("INSERT INTO CONFORMED" in c.args[0] for c in calls)
        assert calls[-1].args[1][-1] == "OPERATOR_ROLLBACK"
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()


def test_storage_and_explorer_are_dev_only() -> None:
    for migration in load_migrations():
        if migration.version not in {"V046", "V047"}:
            continue
        with pytest.raises(ValueError, match="DEV-only"):
            render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
        assert "MANUAL_REVIEW_DECISIONS" not in migration.source
        assert "ACCOUNTADMIN" not in migration.source
    assert not {"V046", "V047"} & {
        row["version"] for row in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }


def test_prod_storage_and_explorer_are_prod_only_and_least_privilege() -> None:
    storage = next(item for item in load_migrations() if item.version == "V051")
    explorer = next(item for item in load_migrations() if item.version == "V052")
    for migration in (storage, explorer):
        with pytest.raises(ValueError, match="PROD-only"):
            render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_DEV")
    sql = storage.source + explorer.source
    assert "OH_LYME_PROD_PIPELINE_RUNTIME" in sql
    assert "OH_LYME_PROD_GOVERNED_VIEW_OWNER" in sql
    assert "OH_LYME_PROD_STREAMLIT_OWNER" in sql
    assert "ACCOUNTADMIN" not in sql
    assert "MANUAL_REVIEW_DECISIONS" not in sql
    assert "DELETE" not in sql
    assert "RAW.CDC_LYME_QTBI_XD4I" in sql
    assert "CONFORMED.CDC_HISTORICAL_VALIDATED_SNAPSHOTS" in sql
    assert "SELECT, INSERT ON TABLE GOVERNANCE.SCHEMA_MIGRATIONS" in storage.source
    assert {"V051", "V052"} <= {
        row["version"] for row in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    assert not {"V051", "V052"} & {
        row["version"] for row in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")
    }


def test_historical_view_ownership_cleanup_is_exact_and_dev_only() -> None:
    migration = next(item for item in load_migrations() if item.version == "V048")
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "GRANT OWNERSHIP ON VIEW CONFORMED.CONFORMED_CDC_LYME_QTBI_XD4I" in migration.source
    assert "TO ROLE OH_LYME_DEV_GOVERNED_VIEW_OWNER COPY CURRENT GRANTS" in migration.source
    assert "GRANT SELECT ON TABLE GOVERNANCE.CDC_PUBLICATIONS" in migration.source
    assert "GRANT SELECT ON TABLE CONFORMED.CDC_HISTORICAL_VALIDATED_SNAPSHOTS" in migration.source
    assert (
        "REVOKE SELECT ON TABLE GOVERNANCE.DATA_SOURCE_VERSIONS FROM ROLE ACCOUNTADMIN"
        in migration.source
    )
    assert "RAW.CDC_LYME_QTBI_XD4I" not in migration.source
    assert "OH_LYME_DEV_PIPELINE_RUNTIME" not in migration.source
    assert "PROD" not in migration.source
    assert "V048" not in {
        row["version"] for row in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
