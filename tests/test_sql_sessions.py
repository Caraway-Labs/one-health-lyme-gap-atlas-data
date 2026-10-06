from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import sql_sessions


@pytest.mark.parametrize("value", [None, ""])
def test_existing_sessions_are_unchanged_without_opt_in(monkeypatch, value) -> None:
    if value is None:
        monkeypatch.delenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", value)
    connector = MagicMock()
    monkeypatch.setattr(sql_sessions, "shared_connect", connector)
    settings = MagicMock()
    assert sql_sessions.connect(settings, include_database=False) is connector.return_value
    connector.assert_called_once_with(settings, include_database=False)
    connector.return_value.cursor.assert_not_called()


@pytest.mark.parametrize("value", ["0", "61", "-1", "1; SELECT 1", "invalid"])
def test_invalid_limits_fail_before_authentication(monkeypatch, value) -> None:
    monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", value)
    connector = MagicMock()
    monkeypatch.setattr(sql_sessions, "shared_connect", connector)
    with pytest.raises(ValueError):
        sql_sessions.connect(MagicMock())
    connector.assert_not_called()


def test_bounds_apply_before_connection_is_returned(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", "60")
    connector = MagicMock()
    monkeypatch.setattr(sql_sessions, "shared_connect", connector)
    sql_sessions.connect(MagicMock())
    cursor = connector.return_value.cursor.return_value.__enter__.return_value
    cursor.execute.assert_called_once_with(
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60, "
        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10, ABORT_DETACHED_QUERY=TRUE, "
        "QUERY_TAG='DATA594_BOUNDED_COHORT_DELIVERY'"
    )


def test_failed_limit_configuration_closes_connection(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", "60")
    connector = MagicMock()
    monkeypatch.setattr(sql_sessions, "shared_connect", connector)
    cursor = connector.return_value.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError("permission denied")
    with pytest.raises(RuntimeError, match="permission denied"):
        sql_sessions.connect(MagicMock())
    connector.return_value.close.assert_called_once_with()
