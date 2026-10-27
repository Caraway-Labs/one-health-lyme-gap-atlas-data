"""PubMed failures keep a redacted code, and a second attempt can name one search."""

from __future__ import annotations

import json
import os
import socket
import ssl
from typing import Any

import httpx
import pytest

from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion import intelligence_entrez as entrez
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError
from lyme_gap_atlas_data.ingestion.intelligence_entrez import SOURCE_ORDER
from lyme_gap_atlas_data.settings import PipelineSettings

POISON = (
    "user@example.test https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    "?email=user@example.test <html>blocked Secret-Header: no"
)
TICK = "pubmed-tick-borne"
LYME = "pubmed-lyme-borrelia"


def _settings() -> PipelineSettings:
    return PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        intelligence_daily_enabled=True,
        ncbi_email="fixture@example.test",
    )


class _Ledger:
    def __init__(self) -> None:
        self.saved: list[Any] = []
        self.claims: list[str] = []

    def claim_daily_run(self, _run_id: str, source_id: str, _sha: str, **_kwargs: Any) -> bool:
        self.claims.append(source_id)
        return True

    def save(self, state: Any) -> None:
        self.saved.append(state)


def _succeeded(source_id: str, _path: str, **_kwargs: Any) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "outcome": "SUCCEEDED",
        "status": "COMPLETED",
        "failed_stage": None,
        "stage_timings_ms": {},
    }


def _patch_walk(monkeypatch: pytest.MonkeyPatch, ledger: _Ledger, error: BaseException) -> None:
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _settings)
    monkeypatch.setattr(polling, "execute_daily_source", _succeeded)

    def _registered(*_args: Any, **kwargs: Any) -> list[dict[str, str]]:
        only = kwargs.get("only_source_id")
        chosen = SOURCE_ORDER if only is None else (only,)
        return [{"source_id": source_id} for source_id in chosen if source_id in SOURCE_ORDER]

    monkeypatch.setattr(polling, "registered_entrez_sources", _registered)
    monkeypatch.setattr(polling, "open_entrez_daily_io", lambda _settings: ("store", ledger, None))

    def boom(**_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(polling, "execute_registered_entrez_daily", boom)


def _assert_redacted(text: str) -> None:
    for marker in ("user@example.test", "esearch.fcgi", "<html>", "Secret-Header", POISON):
        assert marker not in text


@pytest.mark.parametrize(
    ("error", "code", "status"),
    [
        (AcquisitionError(POISON, code="FEED_HTTP_403", http_status=403), "FEED_HTTP_403", 403),
        (
            AcquisitionError(POISON, code="FEED_RATE_LIMITED", http_status=429),
            "FEED_RATE_LIMITED",
            429,
        ),
        (
            AcquisitionError(POISON, code="FEED_HTTP_FAILED", http_status=500),
            "FEED_HTTP_FAILED",
            500,
        ),
        (AcquisitionError(POISON, code="FEED_TIMEOUT"), "FEED_TIMEOUT", None),
        (AcquisitionError(POISON, code="FEED_DNS_FAILED"), "FEED_DNS_FAILED", None),
        (AcquisitionError(POISON, code="FEED_TLS_FAILED"), "FEED_TLS_FAILED", None),
        (
            AcquisitionError(POISON, code="FEED_TLS_VERIFICATION_FAILED"),
            "FEED_TLS_VERIFICATION_FAILED",
            None,
        ),
        (TimeoutError(POISON), "FEED_TIMEOUT", None),
        (PermissionError(POISON), "PUBMED_DAILY_FAILED", None),
    ],
)
def test_pubmed_failure_records_code_and_status_without_message_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    code: str,
    status: int | None,
) -> None:
    entrez._PUBMED_STEP.set(None)
    ledger = _Ledger()
    _patch_walk(monkeypatch, ledger, error)
    payload = polling.run_production_daily()
    logged = capsys.readouterr().out
    rendered = json.dumps(payload)
    _assert_redacted(logged)
    _assert_redacted(rendered)
    assert payload["status"] == "SUCCEEDED"
    assert [row["outcome"] for row in payload["sources"]] == ["SUCCEEDED"] * len(
        runtime.PROD_SOURCE_DEFINITIONS
    )
    assert [row["error_code"] for row in payload["pubmed"]] == [code, code]
    if status is None:
        assert all("http_status" not in row for row in payload["pubmed"])
    else:
        assert [row["http_status"] for row in payload["pubmed"]] == [status, status]
    assert len(ledger.saved) == 2
    for state in ledger.saved:
        checkpoint = state.stages[0]
        assert checkpoint.redacted_diagnostic_code == code
        if code == "PUBMED_DAILY_FAILED":
            assert checkpoint.detail == {"exception_class": type(error).__name__}
        else:
            assert checkpoint.detail == ({} if status is None else {"http_status": status})
        _assert_redacted(json.dumps(state.to_dict()))
    for line in logged.splitlines():
        if not line.startswith(polling.DAILY_OUTCOME_LOG_PREFIX):
            continue
        body = json.loads(line.removeprefix(polling.DAILY_OUTCOME_LOG_PREFIX))
        if body.get("source_id") not in SOURCE_ORDER:
            continue
        assert body["error_code"] == code
        assert body["status"] == "FAILED"
        if status is None:
            assert "http_status" not in body
        else:
            assert body["http_status"] == status


class ProgrammingError(Exception):
    """Stand-in for the Snowflake DB-API error. The message must never be stored."""

    def __init__(self, message: str, *, errno: object, sqlstate: object) -> None:
        super().__init__(message)
        self.errno = errno
        self.sqlstate = sqlstate


def test_unclassified_programming_error_records_step_errno_and_sqlstate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    message = (
        "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD SET write_sequence=write_sequence+1 "
        "WHERE note='user@example.test' AND sql='SELECT secret FROM RAW_ARTIFACTS'"
    )
    error = ProgrammingError(message, errno=625, sqlstate="57014")
    ledger = _Ledger()
    _patch_walk(monkeypatch, ledger, error)

    def boom(**_kwargs: Any) -> None:
        entrez.note_pubmed_step("CAPTURE")
        raise error

    monkeypatch.setattr(polling, "execute_registered_entrez_daily", boom)
    payload = polling.run_production_daily()
    logged = capsys.readouterr().out
    rendered = json.dumps(payload)
    _assert_redacted(logged)
    _assert_redacted(rendered)
    assert "INTELLIGENCE_WRITE_GUARD" not in logged
    assert "RAW_ARTIFACTS" not in logged
    assert "SELECT" not in logged
    expected = {
        "errno": 625,
        "exception_class": "ProgrammingError",
        "sqlstate": "57014",
        "step": "CAPTURE",
    }
    assert [row["error_code"] for row in payload["pubmed"]] == ["PUBMED_DAILY_FAILED"] * 2
    for row in payload["pubmed"]:
        assert {key: row[key] for key in expected} == expected
        assert "http_status" not in row
    for state in ledger.saved:
        assert state.stages[0].detail == expected
        _assert_redacted(json.dumps(state.to_dict()))
    for line in logged.splitlines():
        if not line.startswith(polling.DAILY_OUTCOME_LOG_PREFIX):
            continue
        body = json.loads(line.removeprefix(polling.DAILY_OUTCOME_LOG_PREFIX))
        if body.get("source_id") not in SOURCE_ORDER:
            continue
        assert {key: body[key] for key in expected} == expected
        assert body["error_class"] == "ProgrammingError"
        assert body["error_code"] == "PUBMED_DAILY_FAILED"
        assert set(body) <= {
            "errno",
            "error_class",
            "error_code",
            "exception_class",
            "source_id",
            "sqlstate",
            "status",
            "step",
        }
    entrez._PUBMED_STEP.set(None)


def test_unclassified_failure_drops_partial_or_free_text_dbapi_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entrez._PUBMED_STEP.set(None)
    error = ProgrammingError(POISON, errno=True, sqlstate="not a state")
    ledger = _Ledger()
    _patch_walk(monkeypatch, ledger, error)
    payload = polling.run_production_daily()
    capsys.readouterr()
    assert ledger.saved[0].stages[0].detail == {"exception_class": "ProgrammingError"}
    assert "errno" not in payload["pubmed"][0]
    assert "sqlstate" not in payload["pubmed"][0]
    assert "step" not in payload["pubmed"][0]


def test_connector_exceptions_become_redacted_codes() -> None:
    dns = httpx.ConnectError(POISON)
    dns.__cause__ = socket.gaierror(8, POISON)
    tls = httpx.ConnectError(POISON)
    tls.__cause__ = ssl.SSLError(POISON)
    verify = httpx.ConnectError(POISON)
    verify.__cause__ = ssl.SSLCertVerificationError(POISON)
    refused = httpx.ConnectError(POISON)
    refused.__cause__ = ConnectionRefusedError(111, POISON)
    cases = (
        (httpx.ConnectTimeout(POISON), "FEED_TIMEOUT"),
        (httpx.ReadTimeout(POISON), "FEED_TIMEOUT"),
        (dns, "FEED_DNS_FAILED"),
        (tls, "FEED_TLS_FAILED"),
        (verify, "FEED_TLS_VERIFICATION_FAILED"),
        (refused, "FEED_CONNECTION_REFUSED"),
        (httpx.RemoteProtocolError(POISON), "FEED_HTTP_PROTOCOL_FAILED"),
        (httpx.ConnectError(POISON), "FEED_NETWORK_FAILED"),
        (RuntimeError(POISON), "FEED_HTTP_FAILED"),
    )
    for error, code in cases:
        wrapped = entrez._transport_acquisition_error(error)
        assert wrapped.code == code
        assert wrapped.http_status is None
        assert str(wrapped) == code
        _assert_redacted(str(wrapped))


def test_pubmed_failure_log_keeps_detail_and_uses_daily_attempt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    polling._log_pubmed_failure(
        TICK,
        "ProgrammingError",
        error_code="PUBMED_DAILY_FAILED",
        daily_attempt=2,
        detail={
            "errno": 625,
            "exception_class": "ProgrammingError",
            "sqlstate": "57014",
            "step": "CAPTURE",
        },
    )
    polling._log_pubmed_retry_success(TICK, {"FETCH": 12})
    polling._log_pubmed_retry_success(LYME, {})
    lines = [
        json.loads(line.removeprefix(polling.DAILY_OUTCOME_LOG_PREFIX))
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(polling.DAILY_OUTCOME_LOG_PREFIX)
    ]
    failure, measured, unknown = lines
    assert failure["daily_attempt"] == 2
    assert "attempt" not in failure
    assert failure["errno"] == 625
    assert failure["step"] == "CAPTURE"
    assert set(failure) <= {
        "daily_attempt",
        "errno",
        "error_class",
        "error_code",
        "exception_class",
        "source_id",
        "sqlstate",
        "status",
        "step",
    }
    assert measured["stage_timings_ms"] == {"FETCH": 12}
    assert measured["daily_attempt"] == 2
    assert "attempt" not in measured
    assert "stage_timings_ms" not in unknown
    assert unknown["daily_attempt"] == 2


def test_pubmed_reopen_accepts_one_search_only_from_attempt_two() -> None:
    assert polling.daily_source_selection((TICK,), reopen_attempt=2) == frozenset({TICK})
    assert polling.daily_source_selection((LYME,), reopen_attempt=3) == frozenset({LYME})
    with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
        polling.daily_source_selection((TICK,), reopen_attempt=1)
    with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
        polling.daily_source_selection((TICK, "cdc-mmwr"), reopen_attempt=2)
    with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
        polling.daily_source_selection((TICK, LYME), reopen_attempt=2)
    assert polling.daily_source_selection(("cdc-mmwr",), reopen_attempt=2) == frozenset(
        {"cdc-mmwr"}
    )
    assert polling.daily_source_selection(
        ("cdc-mmwr", "cdc-outbreaks"), reopen_attempt=2
    ) == frozenset({"cdc-mmwr", "cdc-outbreaks"})


def test_pubmed_reopen_runs_only_that_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _settings)
    rss: list[str] = []
    monkeypatch.setattr(
        polling,
        "execute_daily_source",
        lambda source_id, *_args, **_kwargs: rss.append(source_id),
    )
    seen: dict[str, Any] = {}

    def walk(*_args: Any, **kwargs: Any) -> list[dict[str, str]]:
        seen.update(kwargs)
        return [{"source_id": kwargs["only_source_id"], "status": "FAILED", "error_class": "x"}]

    monkeypatch.setattr(polling, "_walk_registered_entrez_daily", walk)
    payload = polling.run_production_daily(reopen_attempt=2, source_ids=(TICK,))
    assert rss == []
    assert seen["only_source_id"] == TICK
    assert seen["reopen_attempt"] == 2
    assert payload["status"] == "FAILED"
    assert {row["outcome"] for row in payload["sources"]} == {"SKIPPED_NOT_SELECTED"}
    assert [row["source_id"] for row in payload["pubmed"]] == [TICK]
    assert LYME not in json.dumps(payload["pubmed"])


def test_pubmed_reopen_rejects_a_prior_attempt_that_is_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _settings)
    monkeypatch.setattr(
        polling,
        "execute_daily_source",
        lambda *_args, **_kwargs: pytest.fail("rss source ran"),
    )
    monkeypatch.setattr(
        polling,
        "registered_entrez_sources",
        lambda *_args, **_kwargs: [{"source_id": TICK}],
    )
    monkeypatch.setattr(
        polling,
        "execute_registered_entrez_daily",
        lambda **_kwargs: pytest.fail("pubmed fetch ran"),
    )

    class _Reject:
        def claim_daily_run(self, *_args: Any, **_kwargs: Any) -> bool:
            raise PermissionError("INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED")

        def save(self, _state: Any) -> None:
            raise AssertionError("checkpoint written")

    monkeypatch.setattr(
        polling, "open_entrez_daily_io", lambda _settings: ("store", _Reject(), None)
    )
    with pytest.raises(PermissionError, match="REOPEN_PRIOR_TERMINAL_FAILED"):
        polling.run_production_daily(reopen_attempt=2, source_ids=(TICK,))


def test_scheduled_run_retries_one_failed_pubmed_source_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTELLIGENCE_DAILY_REOPEN", raising=False)
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _settings)
    monkeypatch.setattr(polling, "execute_daily_source", _succeeded)
    calls: list[dict[str, Any]] = []

    def walk(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        if kwargs["reopen_attempt"] == 1:
            return [
                {
                    "source_id": TICK,
                    "status": "FAILED",
                    "error_class": "TimeoutError",
                    "error_code": "FEED_TIMEOUT",
                }
            ]
        assert kwargs["scheduled_retry"] is True
        assert kwargs["only_source_id"] == TICK
        assert os.environ.get("INTELLIGENCE_DAILY_REOPEN") != "true"
        return [
            {
                "source_id": TICK,
                "status": "FAILED",
                "error_class": "TimeoutError",
                "error_code": "FEED_TIMEOUT",
            }
        ]

    monkeypatch.setattr(polling, "_walk_registered_entrez_daily", walk)
    payload = polling.run_production_daily(scheduled_retry=True)
    assert [call["reopen_attempt"] for call in calls] == [1, 2]
    assert calls[0]["only_source_id"] is None
    assert payload["status"] == "SUCCEEDED"
    assert payload["pubmed"] == [
        {
            "source_id": TICK,
            "status": "FAILED",
            "error_class": "TimeoutError",
            "error_code": "FEED_TIMEOUT",
            "daily_attempt": 2,
        }
    ]
    assert LYME not in json.dumps(payload["pubmed"])
    assert os.environ.get("INTELLIGENCE_DAILY_REOPEN") != "true"


def test_scheduled_pubmed_retry_success_clears_the_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _settings)
    monkeypatch.setattr(polling, "execute_daily_source", _succeeded)
    calls: list[int] = []

    def walk(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs["reopen_attempt"])
        if kwargs["reopen_attempt"] == 1:
            return [{"source_id": LYME, "status": "FAILED", "error_class": "TimeoutError"}]
        assert kwargs["only_source_id"] == LYME
        return []

    monkeypatch.setattr(polling, "_walk_registered_entrez_daily", walk)
    payload = polling.run_production_daily(scheduled_retry=True)
    assert calls == [1, 2]
    assert "pubmed" not in payload
    assert payload["status"] == "SUCCEEDED"


def test_rss_reopen_still_skips_pubmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    monkeypatch.setattr(polling, "PUBMED_WALK_ISOLATE", False)
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", _settings)
    monkeypatch.setattr(polling, "execute_daily_source", _succeeded)
    monkeypatch.setattr(
        polling,
        "_walk_registered_entrez_daily",
        lambda *_args, **_kwargs: pytest.fail("pubmed walk"),
    )
    payload = polling.run_production_daily(reopen_attempt=2, source_ids=("cdc-mmwr",))
    assert "pubmed" not in payload
    by_id = {row["source_id"]: row["outcome"] for row in payload["sources"]}
    assert by_id["cdc-mmwr"] == "SUCCEEDED"
    assert all(
        outcome == "SKIPPED_NOT_SELECTED"
        for source_id, outcome in by_id.items()
        if source_id != "cdc-mmwr"
    )
