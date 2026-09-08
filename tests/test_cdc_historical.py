from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import cdc
from lyme_gap_atlas_data.cdc_historical import REQUIRED_COLUMNS, validate_historical_evidence
from lyme_gap_atlas_data.migrations import (
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)


def metadata() -> dict[str, object]:
    return {"id": "qtbi-xd4i", "columns": [{"fieldName": key} for key in REQUIRED_COLUMNS]}


def test_historical_review_migration_is_dev_only_and_preserves_steward_boundary() -> None:
    migration = next(item for item in load_migrations() if item.version == "V044")
    assert (
        migration_execution_role(migration, "ONE_HEALTH_LYME_GAP_ATLAS_DEV")
        == "OH_LYME_DEV_STREAMLIT_OWNER"
    )
    assert "V044" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    decision = next(item for item in load_migrations() if item.version == "V045")
    assert migration_execution_role(decision, "ONE_HEALTH_LYME_GAP_ATLAS_DEV") is None
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(decision, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    sql = migration.source + decision.source
    assert "s.username = :REVIEWER_USERNAME AND s.is_active = TRUE" in sql
    assert "r.resource_key = 'cdc_lyme_qtbi_xd4i' AND r.api_dataset_id = 'qtbi-xd4i'" in sql
    assert "r.resource_key = 'cdc_lyme_x5j9_wybp' AND r.api_dataset_id = 'x5j9-wybp'" in sql
    assert "BEGIN TRANSACTION" in sql and "EXCEPTION WHEN OTHER THEN ROLLBACK; RAISE;" in sql
    assert "LEFT JOIN latest_run r ON r.resource_key = seed.resource_key" in sql
    assert "COPY INTO" not in sql
    assert "GRANT USAGE ON PROCEDURE" in sql
    assert "TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME" not in sql


def test_historical_collector_rejects_prod_before_any_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cdc, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    fetch = MagicMock()
    storage = MagicMock()
    connection = MagicMock()
    monkeypatch.setattr(cdc, "_fetch_json", fetch)
    monkeypatch.setattr(cdc, "_spaces_client", storage)
    monkeypatch.setattr(cdc, "connect", connection)
    with pytest.raises(ValueError, match="DEV-only"):
        cdc.collect_cdc_evidence(dataset_id="qtbi-xd4i")
    fetch.assert_not_called()
    storage.assert_not_called()
    connection.assert_not_called()


def test_historical_collector_keeps_evidence_and_current_source_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        topx_env="dev", socrata_app_token=None, spaces_bucket="fixture-dev", spaces_prefix="dev"
    )
    monkeypatch.setattr(cdc, "PipelineSettings", lambda: settings)
    fetch = MagicMock(side_effect=[metadata(), [{"year": "2008", "frequency": 0}]])
    monkeypatch.setattr(cdc, "_fetch_json", fetch)
    monkeypatch.setattr(cdc, "_spaces_client", lambda _: object())
    artifact = SimpleNamespace(sha256="a" * 64, object_key="fixture", byte_count=10)
    save = MagicMock(return_value=artifact)
    monkeypatch.setattr(cdc, "_save_artifact", save)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(cdc, "connect", lambda _: connection)
    result = cdc.collect_cdc_evidence(dataset_id="qtbi-xd4i")
    assert result["resource_key"] == "cdc_lyme_qtbi_xd4i"
    assert result["status"] == "PENDING_STEWARD_REVIEW"
    assert fetch.call_count == 2
    assert "%24limit=25" in fetch.call_args_list[1].args[0]
    assert "%3Aid+ASC" in fetch.call_args_list[1].args[0]
    assert all(call.args[2] == "cdc_lyme_qtbi_xd4i" for call in save.call_args_list)
    calls = connection.cursor.return_value.__enter__.return_value.execute.call_args_list
    for call in calls:
        assert "x5j9" not in str(call)
        assert "DATA_SOURCE_VERSIONS" not in call.args[0]
        assert "MANUAL_REVIEW_DECISIONS" not in call.args[0]
        assert "COPY INTO" not in call.args[0]
        assert call.args[0].count("%s") == len(call.args[1])
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()


def test_historical_sample_preserves_unknowns_and_does_not_claim_complete_quality() -> None:
    sample = [{"year": "2008", "frequency": 0}, {"year": "2021", "fips": "Unknown"}]
    original = deepcopy(sample)
    result = validate_historical_evidence(metadata(), sample, environment="dev", sample_limit=25)
    assert sample == original
    assert result["full_dataset_validated"] is False
    assert result["publisher_record_identity_verified"] is False


@pytest.mark.parametrize("year", ["2007", "2022", None, "Unknown", "2010.0"])
def test_historical_sample_rejects_wrong_era(year: object) -> None:
    with pytest.raises(ValueError, match="era"):
        validate_historical_evidence(
            metadata(), [{"year": year}], environment="dev", sample_limit=25
        )


def test_historical_candidate_cannot_enter_prod_or_exceed_sample_bound() -> None:
    with pytest.raises(ValueError, match="DEV-only"):
        validate_historical_evidence(
            metadata(), [{"year": "2008"}], environment="prod", sample_limit=25
        )
    with pytest.raises(ValueError, match="bound"):
        validate_historical_evidence(
            metadata(), [{"year": "2008"}] * 2, environment="dev", sample_limit=1
        )


def test_historical_candidate_rejects_wrong_dataset_and_missing_schema() -> None:
    wrong = metadata()
    wrong["id"] = "x5j9-wybp"
    with pytest.raises(ValueError, match="identity"):
        validate_historical_evidence(wrong, [{"year": "2008"}], environment="dev", sample_limit=25)
    with pytest.raises(ValueError, match="columns"):
        validate_historical_evidence(
            {"id": "qtbi-xd4i", "columns": []},
            [{"year": "2008"}],
            environment="dev",
            sample_limit=25,
        )
