"""Source-backed offline driver behavior; never Snowflake execution proof (#376)."""

from __future__ import annotations

import ast
import json
import socket
import subprocess
from pathlib import Path

import pytest
from snowflake.connector.connection import SnowflakeConnection
from snowflake.connector.converter import SnowflakeConverter
from snowflake.connector.cursor import SnowflakeCursor
from snowflake.connector.errorcode import ER_FAILED_TO_REWRITE_MULTI_ROW_INSERT
from snowflake.connector.errors import InterfaceError

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.failure_evidence import review_context, validate_packet

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/failure_reproductions/semantic-batch-binding-v1.json"


class OfflineConnection:
    """Only the real driver's local conversion dependencies; no transport exists."""

    log_max_query_length = 1024
    is_pyformat = True
    telemetry_enabled = False
    _reuse_results = False
    _interpolate_empty_sequences = False
    _process_params_pyformat = SnowflakeConnection._process_params_pyformat
    _process_single_param = SnowflakeConnection._process_single_param

    def __init__(self):
        self.converter = SnowflakeConverter()
        self.messages = []

    def is_closed(self):
        return False


class OfflineCursor(SnowflakeCursor):
    """Execute real rewrite/conversion, replacing server execution at its boundary."""

    def __init__(self):
        self.boundaries = []
        self.executemany_calls = 0
        super().__init__(OfflineConnection())

    def execute(self, command, params=None, **kwargs):
        # Real pyformat processing runs. The network execute method is never called.
        prepared = self._preprocess_pyformat_query(command, params)
        self.boundaries.append((command, params, prepared))
        return self

    def executemany(self, command, seqparams, **kwargs):
        self.executemany_calls += 1
        return super().executemany(command, seqparams, **kwargs)


@pytest.fixture(autouse=True)
def forbid_network_and_live_connections(monkeypatch):
    attempts = []

    def deny(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("offline reproduction attempted a live boundary")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(SnowflakeConnection, "__init__", deny)
    monkeypatch.setattr(semantic_release, "connect", deny)
    yield
    assert attempts == []


def historical_statement(source, function):
    tree = ast.parse(source)
    node = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == function
    )
    call = next(
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "executemany"
    )
    return ast.literal_eval(call.args[0])


def test_historical_templates_are_literal_source_at_the_pinned_commits():
    fixture = json.loads(FIXTURE.read_text())
    for case in fixture["cases"]:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={ROOT.as_posix()}",
                "show",
                f"{case['source_commit']}:src/lyme_gap_atlas_data/semantic_release.py",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, "pinned source unavailable; history is required"
        for name in ("_insert_counties", "_insert_observations"):
            assert historical_statement(result.stdout, name) == case["statements"][name]


@pytest.mark.parametrize("function,width", [("_insert_counties", 22), ("_insert_observations", 18)])
def test_pre_336_statement_reproduces_actual_driver_rewrite_failure(function, width, capsys):
    fixture = json.loads(FIXTURE.read_text())
    before = fixture["cases"][0]
    rows = [tuple(f"fixture-{index}" for index in range(width))]
    cursor = OfflineCursor()
    with pytest.raises(InterfaceError) as caught:
        cursor.executemany(before["statements"][function], rows)
    assert caught.value.errno == ER_FAILED_TO_REWRITE_MULTI_ROW_INSERT
    assert cursor.boundaries == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("function,width", [("_insert_counties", 22), ("_insert_observations", 18)])
def test_first_336_repair_prepares_but_does_not_prove_server_variant_behavior(function, width):
    fixture = json.loads(FIXTURE.read_text())
    first_repair = fixture["cases"][1]
    cursor = OfflineCursor()
    cursor.executemany(
        first_repair["statements"][function], [tuple("fixture" for _ in range(width))]
    )
    assert len(cursor.boundaries) == 1
    # This was the follow-on server failure documented by PR337. We stop before
    # that boundary, so a successful client rewrite cannot be called engine PASS.
    prepared = cursor.boundaries[0][2]
    assert "PARSE_JSON" in prepared.split("VALUES", 1)[1]


@pytest.mark.parametrize(
    "function,width,batch_size",
    [
        ("_insert_counties", 22, 50),
        ("_insert_observations", 18, 500),
    ],
)
def test_current_337_repair_runs_actual_local_driver_binding_in_bounded_batches(
    function, width, batch_size
):
    cursor = OfflineCursor()
    rows = [
        tuple(f"fixture-{row}-{column}" for column in range(width)) for row in range(batch_size + 1)
    ]
    if function == "_insert_counties":
        semantic_release._insert_counties(
            cursor,
            "fixture-release",
            [semantic_release.CountyRow(values=row, lineage={}) for row in rows],
        )
        expected = rows
    else:
        semantic_release._insert_observations(cursor, "fixture-release", rows)
        expected = [(row[0], "fixture-release", *row[2:]) for row in rows]
    assert cursor.executemany_calls == 0
    assert len(cursor.boundaries) == 2
    flattened = []
    for statement, parameters, prepared in cursor.boundaries:
        assert "fixture-" not in statement
        assert "%s" not in prepared
        assert "PARSE_JSON" not in statement.split("FROM VALUES", 1)[1]
        assert len(parameters) <= batch_size * width
        flattened.extend(parameters)
    assert flattened == [value for row in expected for value in row]


def test_current_batch_guard_rejects_bad_width_before_any_driver_boundary():
    cursor = OfflineCursor()
    with pytest.raises(ValueError):
        semantic_release._execute_bound_value_batches(
            cursor,
            "INSERT INTO fixture SELECT $1,$2 FROM VALUES",
            [("fixture",)],
            row_width=2,
            batch_size=50,
        )
    assert cursor.boundaries == []


def test_companion_receipt_adds_scoped_client_proof_without_rewriting_historical_identity():
    original = json.loads((ROOT / "docs/delivery/failures/pr-336.json").read_text())
    receipt = json.loads(
        (
            ROOT / ("docs/delivery/failure-reproduction-receipts/pr-336-client-binding-v1.json")
        ).read_text()
    )
    validate_packet(receipt)
    assert original["regression"]["kind"] == "STATIC"
    assert receipt["regression"]["kind"] == "BEHAVIORAL"
    assert receipt["regression"]["state"] == "PASS"
    assert receipt["identity"] == original["identity"]
    assert receipt["artifacts"] == original["artifacts"]
    assert receipt["effective_role"] == original["effective_role"]
    assert receipt["correlation_key"] == original["correlation_key"]
    assert receipt["repair"]["state"] == "UNKNOWN"
    assert receipt["repair"]["reference"]["state"] == "KNOWN"
    assert receipt["reproduction"]["state"] == "KNOWN"
    assert review_context(receipt)["independent_behavioral_evidence_required"]
