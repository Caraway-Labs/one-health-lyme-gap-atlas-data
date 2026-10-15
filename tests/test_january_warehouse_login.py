"""Offline login parameter/metadata proof; not evidence of PROD warehouse access."""

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data import sql_sessions

WAREHOUSE = "OH_LYME_PROD_APPROVAL_XS_WH"


def settings():
    return SnowflakeSettings(
        _env_file=None,
        snowflake_account="fixture-account",
        snowflake_user="OH_LYME_PROD_PIPELINE_SVC",
        snowflake_role="OH_LYME_PROD_RUNTIME",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        snowflake_warehouse=WAREHOUSE,
        snowflake_auth_method="pat",
        snowflake_pat="offline-fixture",
    )


@pytest.mark.parametrize("path", ["canonical", "identity"])
@pytest.mark.parametrize("returned", [WAREHOUSE, None, "WRONG_WAREHOUSE"])
def test_both_paths_request_and_validate_same_warehouse_without_sql(monkeypatch, path, returned):
    monkeypatch.setenv("ATLAS_JANUARY_PROD_SESSION", "true")
    connection = Mock(warehouse=returned)
    connect = Mock(return_value=connection)
    if path == "canonical":
        monkeypatch.setattr(sql_sessions, "connector_connect", connect)

        def call():
            return sql_sessions.connect(settings())
    else:
        function = runpy.run_path(str(Path("scripts/verify_climate_dev_views.py")))[
            "bounded_connection"
        ]
        monkeypatch.setitem(function.__globals__, "connect", connect)
        monkeypatch.setitem(function.__globals__, "SnowflakeSettings", settings)
        call = function
    if returned == WAREHOUSE:
        assert call() is connection
        connection.close.assert_not_called()
    else:
        with pytest.raises(ValueError, match="JANUARY_WAREHOUSE_NOT_SELECTED"):
            call()
        connection.close.assert_called_once_with(retry=False)
    parameters = connect.call_args.kwargs
    assert parameters["warehouse"] == WAREHOUSE
    assert parameters["validate_default_parameters"] is True
    assert parameters["network_timeout"] == parameters["socket_timeout"] == 65
    assert parameters["session_parameters"]["STATEMENT_TIMEOUT_IN_SECONDS"] == 60
    assert parameters["session_parameters"]["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"] == 10
    assert parameters["session_parameters"]["ABORT_DETACHED_QUERY"] is True
    connection.cursor.assert_not_called()


@pytest.mark.parametrize("warehouse", [None, "", "WRONG_WAREHOUSE"])
def test_invalid_requested_warehouse_rejected_before_connect(monkeypatch, warehouse):
    monkeypatch.setenv("ATLAS_JANUARY_PROD_SESSION", "true")
    connect = Mock()
    monkeypatch.setattr(sql_sessions, "connector_connect", connect)
    value = SimpleNamespace(
        snowflake_warehouse=warehouse, snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    )
    with pytest.raises(ValueError, match="JANUARY_WAREHOUSE_CONFIGURATION"):
        sql_sessions.connect(value)
    connect.assert_not_called()


def test_non_january_connections_keep_existing_behavior(monkeypatch):
    monkeypatch.delenv("ATLAS_JANUARY_PROD_SESSION", raising=False)
    monkeypatch.delenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", raising=False)
    connect = Mock()
    monkeypatch.setattr(sql_sessions, "shared_connect", connect)
    sql_sessions.connect(settings())
    connect.assert_called_once()


def test_january_workflows_enable_common_login_initialization():
    for name in (
        "capture-prod-routine-public-evidence",
        "run-prod-ingestion",
        "publish-semantic-release",
    ):
        source = Path(f".github/workflows/{name}.yml").read_text()
        assert "echo 'ATLAS_JANUARY_PROD_SESSION=true'" in source
    assert (
        'ATLAS_JANUARY_PROD_SESSION: "true"'
        in Path(".github/workflows/promote-prod.yml").read_text()
    )
