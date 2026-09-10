from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from lyme_gap_atlas_data import tick_surveillance as tick
from lyme_gap_atlas_data.artifacts import create_artifact
from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)


def workbook_bytes(
    *,
    headers: tuple[str, ...] = tick.EXPECTED_HEADERS,
    rows: list[tuple[object, ...]] | None = None,
) -> bytes:
    workbook = Workbook()
    agreement = workbook.active
    agreement.title = "Data Use Agreement"
    agreement.append(["Tick surveillance data release guidelines"])
    terms = workbook.create_sheet("Classification Terms")
    terms.append(["County Classification", "Definition"])
    terms.append(["No records", "No reported surveillance evidence"])
    data = workbook.create_sheet("Ixodes records 2025")
    data.append(["Ixodes status through Dec. 31, 2025"])
    data.append(list(headers))
    source_rows = rows or [
        (
            f"{1000 + index:05d}",
            "Fixture State",
            f"Fixture County {index}",
            "Established" if index % 2 else "No records",
            "Fixture citation",
            "Reported",
            "Fixture citation",
        )
        for index in range(1, 31)
    ]
    for row in source_rows:
        data.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def profile() -> dict[str, object]:
    return tick.load_tick_profile()


def test_canonical_tick_contract_has_required_semantics_and_examples() -> None:
    schema = json.loads(
        Path(
            "docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["properties"]["county_fips"]["pattern"] == "^[0-9]{5}$"
    assert set(schema["properties"]["observation_type"]["enum"]) == {
        "VECTOR_PRESENCE_STATUS",
        "COLLECTION_ABUNDANCE",
        "PATHOGEN_TESTING",
    }
    missingness = set(schema["properties"]["missingness"]["additionalProperties"]["enum"])
    assert {"NULL", "UNKNOWN", "SUPPRESSED", "NOT_REPORTED", "NOT_APPLICABLE"} <= missingness
    contract = Path("docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md").read_text(
        encoding="utf-8"
    )
    assert contract.count('"canonical_observation_id"') == 2
    assert "NO_RECORDS" in contract
    assert "not evidence that ticks are absent" in contract


def test_tick_profile_is_dev_only_and_pins_first_party_workbook() -> None:
    source = profile()
    assert source["resource_key"] == tick.RESOURCE_KEY
    assert source["connector_name"] == "HTTP_XLSX_V1"
    assert source["onboarding_environments"] == ["dev"]
    assert str(source["endpoint_template"]).startswith("https://www.cdc.gov/")
    assert source["deterministic_order_clause"] == "FIPSCode ASC"


def test_workbook_parser_preserves_status_and_bounded_fips_order() -> None:
    evidence = tick._parse_workbook(workbook_bytes(), profile(), 25)
    assert evidence.row_count == 30
    assert len(evidence.sample) == 25
    assert evidence.sample[0]["FIPSCode"] == "01001"
    assert evidence.sample[1]["Ixodes_scapularis_County_Status"] == "No records"
    assert evidence.schema["full_dataset_quality_validated"] is False
    assert evidence.schema["headers"] == list(tick.EXPECTED_HEADERS)


@pytest.mark.parametrize(
    ("headers", "rows", "message"),
    [
        (("Changed", *tick.EXPECTED_HEADERS[1:]), None, "schema changed"),
        (
            tick.EXPECTED_HEADERS,
            [
                ("01002", "State", "County 2", "Reported", "Citation", "Reported", "Citation"),
                ("01001", "State", "County 1", "Reported", "Citation", "Reported", "Citation"),
            ],
            "not deterministically ordered",
        ),
        (
            tick.EXPECTED_HEADERS,
            [("1001", "State", "County", "Reported", "Citation", "Reported", "Citation")],
            "five-character county FIPS",
        ),
        (
            tick.EXPECTED_HEADERS,
            [("01001", "State", "County", "Absent", "Citation", "Reported", "Citation")],
            "unreviewed county-status",
        ),
    ],
)
def test_workbook_parser_fails_closed_on_unreviewed_structure(
    headers: tuple[str, ...], rows: list[tuple[object, ...]] | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        tick._parse_workbook(
            workbook_bytes(headers=headers, rows=rows), profile(), min(2, len(rows or [1, 2]))
        )


def test_tick_evidence_rejects_non_dev_before_network_or_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tick, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    fetch = MagicMock()
    monkeypatch.setattr(tick, "_fetch_bytes", fetch)
    with pytest.raises(ValueError, match="only for isolated DEV"):
        tick.collect_tick_surveillance_evidence()
    fetch.assert_not_called()


def test_cdc_fetch_uses_browser_compatible_first_party_request_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.url = "https://www.cdc.gov/ticks/example.html"
    response.headers = {"content-type": "text/html", "content-length": "2"}
    response.iter_bytes.return_value = iter([b"ok"])
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.return_value = response
    monkeypatch.setattr(tick.httpx, "Client", lambda **_kwargs: client)

    result = tick._fetch_bytes(
        "https://www.cdc.gov/ticks/example.html",
        accept="text/html",
        maximum_bytes=100,
    )

    assert result.payload == b"ok"
    headers = client.stream.call_args.kwargs["headers"]
    assert headers["User-Agent"] == tick.BROWSER_USER_AGENT
    assert headers["Accept-Language"] == "en-US,en;q=0.9"
    assert headers["Cache-Control"] == "no-cache"


def test_tick_evidence_retains_non_retryable_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(topx_env="dev")
    monkeypatch.setattr(tick, "PipelineSettings", lambda: settings)
    request = tick.httpx.Request("GET", str(profile()["landing_page_url"]))
    response = tick.httpx.Response(403, request=request)
    monkeypatch.setattr(
        tick,
        "_fetch_bytes",
        MagicMock(
            side_effect=tick.httpx.HTTPStatusError("forbidden", request=request, response=response)
        ),
    )
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(tick, "connect", lambda _: connection)

    with pytest.raises(tick.httpx.HTTPStatusError):
        tick.collect_tick_surveillance_evidence()

    cursor = connection.cursor.return_value.__enter__.return_value
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "'RUNNING'" in statements[0]
    assert "status='FAILED'" in statements[-1]
    assert cursor.execute.call_args_list[-1].args[1][1] == "HTTP_403"
    assert "forbidden" not in statements[-1]
    connection.rollback.assert_called_once()
    assert connection.commit.call_count == 2


def test_tick_evidence_creates_only_pending_review_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        topx_env="dev",
        spaces_bucket="fixture-dev",
        spaces_prefix="dev",
    )
    monkeypatch.setattr(tick, "PipelineSettings", lambda: settings)
    landing_payload = (
        b"Tick Surveillance Data Sets No records Established "
        b"Public_Use_Ixodes_County_Table_2026_03252026.xlsx"
    )
    source_workbook = workbook_bytes()
    monkeypatch.setattr(
        tick,
        "_fetch_bytes",
        MagicMock(
            side_effect=[
                tick.FetchResult(landing_payload, "text/html", None, None),
                tick.FetchResult(
                    source_workbook,
                    tick.XLSX_MEDIA_TYPE,
                    '"fixture-etag"',
                    "Fri, 15 May 2026 13:38:49 GMT",
                ),
            ]
        ),
    )
    monkeypatch.setattr(tick, "_spaces_client", lambda _: object())

    def save_artifact(
        _s3: object,
        local_settings: object,
        run_id: str,
        payload: bytes,
        _media_type: str,
    ) -> object:
        return create_artifact(
            payload=payload,
            environment=str(local_settings.topx_env),
            resource_key=tick.RESOURCE_KEY,
            run_id=run_id,
        )

    monkeypatch.setattr(tick, "_save_artifact", save_artifact)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(tick, "connect", lambda _: connection)

    result = tick.collect_tick_surveillance_evidence(25)

    assert result["status"] == "PENDING_STEWARD_REVIEW"
    assert result["sample_rows"] == 25
    assert result["workbook_rows"] == 30
    assert result["full_dataset_quality_validated"] is False
    statements = [
        call.args[0]
        for call in connection.cursor.return_value.__enter__.return_value.execute.call_args_list
    ]
    rendered = "\n".join(statements)
    for required in (
        "GOVERNANCE.INGESTION_RUNS",
        "GOVERNANCE.CATALOG_DATASETS",
        "GOVERNANCE.CATALOG_RESOURCES",
        "GOVERNANCE.SOURCE_ACCESS_PROFILES",
        "GOVERNANCE.INGESTION_REQUESTS",
        "GOVERNANCE.RAW_ARTIFACTS",
        "GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS",
        "GOVERNANCE.SCHEMA_SNAPSHOTS",
        "GOVERNANCE.DATASET_QUALITY_ASSESSMENTS",
    ):
        assert required in rendered
    for forbidden in (
        "DATA_SOURCE_VERSIONS",
        "MANUAL_REVIEW_DECISIONS",
        "RAW.CDC_TICK",
        "STAGING.",
        "CONFORMED.",
        "ANALYTICS.",
        "FEATURE_STORE.",
        "COPY INTO",
    ):
        assert forbidden not in rendered
    assert connection.commit.call_count == 2
    connection.rollback.assert_not_called()


def test_dev_tick_review_migrations_and_workflow_preserve_scope() -> None:
    migrations = {migration.version: migration for migration in load_migrations()}
    assert migration_execution_role(migrations["V053"], DEV_DATABASE) == (
        "OH_LYME_DEV_STREAMLIT_OWNER"
    )
    assert "cdc_tick_ixodes_county_status" in migrations["V053"].source
    assert "No records is not evidence of absence" in migrations["V053"].source
    assert "HTTP_XLSX_V1" in migrations["V054"].source
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migrations["V053"], "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V053" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    workflow = Path(".github/workflows/capture-dev-cdc-tick-surveillance.yml").read_text(
        encoding="utf-8"
    )
    assert "cdc-tick-surveillance-sample --sample-limit 25" in workflow
    assert "cdc-tick-evidence-once" in workflow
    assert "PRE_DEPLOY" in workflow
    assert "restore" in workflow
    for forbidden in ("ingest-approved", "dbt", "PROD_APP_ID", "production"):
        assert forbidden not in workflow


def test_approval_console_exposes_tick_candidate_only_in_dev() -> None:
    source = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    assert 'if current_database.endswith("_DEV")' in source
    assert 'source_labels["cdc_tick_ixodes_county_status"]' in source
    assert "No records means no reported surveillance evidence" in source
    assert "implemented and authorized acquisition path" in source
    assert "INSERT INTO GOVERNANCE" not in source
    assert "UPDATE GOVERNANCE" not in source
