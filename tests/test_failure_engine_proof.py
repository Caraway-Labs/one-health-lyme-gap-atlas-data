"""Offline harness safety/control tests; these never claim Snowflake engine proof."""

import ast
import json
import re
import runpy
import socket
import sys
from pathlib import Path

import pytest
from snowflake.connector import SnowflakeConnection
from snowflake.connector.errors import ProgrammingError

from lyme_gap_atlas_data import failure_engine_proof as proof

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
PRIVATE = "private-user-do-not-publish"


@pytest.fixture(autouse=True)
def no_live_connection(monkeypatch):
    attempted = []

    def denied(*args, **kwargs):
        attempted.append(True)
        raise RuntimeError("network prohibited")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(SnowflakeConnection, "__init__", denied)
    yield
    assert attempted == []


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError("exception rendering forbidden")


class Clock:
    value = 0

    def __call__(self):
        return self.value


class FixtureSession:
    network_timeout = 30
    socket_timeout = 30

    def __init__(
        self,
        *,
        fail=None,
        negative_success=None,
        clock=None,
        jump_after=None,
        identity=None,
        private_query_id=False,
        effect_then_fail=None,
    ):
        self.ops = proof._operations()
        self.fail = fail
        self.negative_success = negative_success
        self.clock = clock
        self.jump_after = jump_after
        self.identity = identity or (PRIVATE, proof.ROLE, proof.DATABASE, proof.WAREHOUSE, None)
        self.private_query_id = private_query_id
        self.effect_then_fail = effect_then_fail
        self.calls = []
        self.rows = {}
        self.transaction = False
        self.close_count = 0
        self.cursor_close_count = 0
        self.current = None
        self.sfqid = "00000000-0000-0000-0000-000000000001"

    def cursor(self):
        return Cursor(self)

    def close(self):
        self.close_count += 1
        self.rows.clear()

    def commit(self):
        pytest.fail("harness must never commit")


class Cursor:
    def __init__(self, session):
        self.session = session

    @property
    def sfqid(self):
        return PRIVATE if self.session.private_query_id else self.session.sfqid

    def execute(self, sql, params=None):
        session = self.session
        matches = [op for op in session.ops.values() if op.sql == sql and op.parameters == params]
        assert len(matches) == 1
        op = matches[0]
        session.calls.append(op.identifier)
        session.current = op
        if session.fail == op.identifier:
            raise PrivateFailure()
        if op.identifier.startswith("CREATE_"):
            assert not session.transaction
            session.rows[int(op.identifier[-1])] = 0
        elif op.identifier == "BEGIN":
            assert not session.transaction
            session.transaction = True
        elif op.identifier == "ROLLBACK":
            session.transaction = False
            session.rows = dict.fromkeys(session.rows, 0)
        elif op.identifier.startswith("DROP_"):
            assert not session.transaction
            del session.rows[int(op.identifier[-1])]
        elif op.identifier.startswith("WRITE_"):
            assert session.transaction
            index = (
                0 if "COUNTIES" in op.identifier else 1 if "OBSERVATIONS" in op.identifier else 2
            )
            session.rows[index] += op.rows
        if session.effect_then_fail == op.identifier:
            raise PrivateFailure()
        if session.clock and session.jump_after and op.identifier == session.jump_after[0]:
            session.clock.value = session.jump_after[1]
        if op.negative_errno and op.identifier != session.negative_success:
            raise ProgrammingError(msg=PRIVATE, errno=op.negative_errno)

    def fetchone(self):
        session = self.session
        if session.current.identifier == "IDENTITY":
            return session.identity
        if session.current.identifier.startswith("ZERO_"):
            return (session.rows[int(session.current.identifier[-1])],)
        return session.current.expected

    def close(self):
        self.session.cursor_close_count += 1


def approved(session, **kwargs):
    plan = proof.make_plan(COMMIT)
    return proof.run_proof(
        session, plan, approved_plan_sha256=proof.plan_hash(plan), expected_user=PRIVATE, **kwargs
    )


def test_default_plan_and_cli_are_nonexecuting_metadata_only(monkeypatch, capsys):
    namespace = runpy.run_path(str(ROOT / "scripts/plan_failure_engine_dev.py"), run_name="planner")
    monkeypatch.setattr(sys, "argv", ["planner", "--code-commit", COMMIT])
    assert namespace["main"]() == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["plan"]["state"] == "NOT_EXECUTED"
    assert payload["plan_sha256"] == proof.plan_hash(payload["plan"])
    assert "INSERT INTO" not in output and "synthetic-observation" not in output
    assert PRIVATE not in output and "replaced-by-helper" not in output
    assert len(payload["plan"]["operations"]) == 28
    assert payload["plan"]["cost"]["credits_per_hour"] == "UNKNOWN"
    assert payload["plan"]["cost"]["usd_per_credit"] == "UNKNOWN"


def test_cli_has_no_live_execution_or_arbitrary_input_echo(monkeypatch, capsys):
    namespace = runpy.run_path(str(ROOT / "scripts/plan_failure_engine_dev.py"), run_name="planner")
    monkeypatch.setattr(sys, "argv", ["planner", "--execute", PRIVATE])
    assert namespace["main"]() == 1
    assert capsys.readouterr().out == '{"state":"PLAN_UNAVAILABLE"}\n'


def test_absent_or_bad_approval_never_touches_session():
    class Untouched:
        def __getattr__(self, name):
            pytest.fail("unapproved session touched")

    plan = proof.make_plan(COMMIT)
    assert proof.run_proof(Untouched(), plan)["state"] == "NOT_AUTHORIZED"
    assert (
        proof.run_proof(Untouched(), plan, approved_plan_sha256="bad", expected_user=PRIVATE)[
            "state"
        ]
        == "PLAN_REJECTED"
    )
    changed = dict(plan, warehouse=PRIVATE)
    assert (
        proof.run_proof(
            Untouched(),
            changed,
            approved_plan_sha256=proof.plan_hash(changed),
            expected_user=PRIVATE,
        )["state"]
        == "PLAN_REJECTED"
    )


@pytest.mark.parametrize("bad", [None, False, 0, 31, float("nan")])
def test_unbounded_client_is_rejected_without_queries_or_cleanup(bad):
    session = FixtureSession()
    session.socket_timeout = bad
    receipt = approved(session)
    assert receipt["state"] == "CLIENT_TIMEOUTS_UNKNOWN"
    assert session.calls == [] and session.close_count == 0


def test_success_exercises_actual_helpers_and_rolls_back_before_cleanup(capsys):
    session = FixtureSession()
    receipt = approved(session)
    assert receipt["state"] == "PASS" and receipt["context"] == "PASS"
    assert receipt["repair"] == "UNKNOWN" and receipt["full_v092_v098_v099_proof"] == "UNKNOWN"
    assert all(value == "PASS" for value in receipt["cleanup"].values())
    assert len(session.calls) == len(set(session.calls)) == 28
    assert session.calls.index("CREATE_2") < session.calls.index("BEGIN")
    assert session.calls.index("ROLLBACK") < session.calls.index("DROP_0")
    assert session.close_count == session.cursor_close_count == 1
    assert session.rows == {}
    serialized = json.dumps(receipt)
    assert PRIVATE not in serialized and "INSERT INTO" not in serialized
    assert "synthetic-observation" not in serialized
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "field,value",
    [
        (1, "OH_LYME_PROD_READ"),
        (2, "ONE_HEALTH_LYME_GAP_ATLAS"),
        (3, "OTHER_WAREHOUSE"),
        (4, "existing-transaction"),
    ],
)
def test_context_mismatch_fails_before_ddl(field, value):
    identity = [PRIVATE, proof.ROLE, proof.DATABASE, proof.WAREHOUSE, None]
    identity[field] = value
    session = FixtureSession(identity=tuple(identity))
    receipt = approved(session)
    assert receipt["state"] == "FAIL" and receipt["context"] == "REJECTED"
    assert session.calls == ["IDENTITY"]
    assert not receipt["mutations_started"]


@pytest.mark.parametrize(
    "negative", ["NEGATIVE_VALUES_COUNTIES", "NEGATIVE_VALUES_OBSERVATIONS", "NEGATIVE_UNBOUND"]
)
def test_unexpected_negative_success_stops_before_positive_writes(negative):
    session = FixtureSession(negative_success=negative)
    receipt = approved(session)
    assert receipt["state"] == "FAIL"
    assert (
        next(item for item in receipt["operations"] if item["operation"] == negative)["state"]
        == "NOT_REPRODUCED"
    )
    assert not any(identifier.startswith("WRITE_") for identifier in session.calls)
    assert receipt["cleanup"]["rollback"] == "PASS"


@pytest.mark.parametrize(
    "identifier",
    [
        "TIMEOUTS",
        "COLLISION_CHECK",
        "CREATE_0",
        "CREATE_1",
        "BEGIN",
        "CANONICAL_PARTIAL",
        "WRITE_COUNTIES_0",
        "WRITE_OBSERVATIONS_1",
        "VERIFY_COUNTIES",
    ],
)
def test_failures_preserve_cleanup_and_never_render_private_exception(identifier, capsys):
    session = FixtureSession(fail=identifier, private_query_id=True)
    receipt = approved(session)
    assert receipt["state"] == "FAIL"
    assert PRIVATE not in json.dumps(receipt)
    assert all(op["query_id"] == "UNKNOWN" for op in receipt["operations"])
    assert session.close_count == 1
    assert capsys.readouterr() == ("", "")


def test_rollback_failure_skips_all_ddl_cleanup():
    session = FixtureSession(fail="ROLLBACK")
    receipt = approved(session)
    assert receipt["state"] == "FAIL"
    assert receipt["cleanup"]["rollback"] == "FAIL"
    assert not any(identifier.startswith("DROP_") for identifier in session.calls)
    assert receipt["cleanup"]["drops"] == "UNKNOWN"
    assert session.close_count == 1


def test_ambiguous_create_does_not_drop_unconfirmed_object():
    session = FixtureSession(effect_then_fail="CREATE_1")
    receipt = approved(session)
    assert receipt["state"] == "FAIL"
    assert "DROP_0" in session.calls and "DROP_1" not in session.calls
    assert receipt["cleanup"]["drops"] == "UNKNOWN"


def test_normal_budget_exhaustion_uses_reserved_cleanup_time():
    clock = Clock()
    session = FixtureSession(clock=clock, jump_after=("WRITE_CONDITIONS", 340))
    receipt = approved(session, clock=clock)
    assert receipt["state"] == "FAIL"
    assert "VERIFY_COUNTIES" not in session.calls
    assert receipt["cleanup"]["rollback"] == receipt["cleanup"]["drops"] == "PASS"


def test_exhausted_cleanup_budget_closes_without_ddl_or_retry():
    clock = Clock()
    session = FixtureSession(clock=clock, jump_after=("VERIFY_CONDITIONS", 580))
    receipt = approved(session, clock=clock)
    assert receipt["state"] == "FAIL"
    assert "ROLLBACK" not in session.calls
    assert not any(identifier.startswith("DROP_") for identifier in session.calls)
    assert session.close_count == 1


def test_gate_rejects_unknown_repeated_sql_parameters_and_row_overflow():
    session = FixtureSession()
    runner = proof._Runner(session.cursor(), Clock())
    boundary = proof._HelperBoundary(runner)
    with pytest.raises(proof.ProofRejected, match="proof contract rejected"):
        runner.execute(PRIVATE)
    with pytest.raises(proof.ProofRejected):
        boundary.execute("DELETE FROM real_table", (PRIVATE,))
    op = runner.operations["WRITE_COUNTIES_0"]
    with pytest.raises(proof.ProofRejected):
        boundary.execute(op.original_sql, (PRIVATE,))
    assert session.calls == []
    runner.inserted_rows = proof.MAX_INSERTED_ROWS
    with pytest.raises(proof.ProofRejected):
        runner.execute("WRITE_COUNTIES_1")
    runner.execute("IDENTITY")
    with pytest.raises(proof.ProofRejected):
        runner.execute("IDENTITY")
    assert session.calls == ["IDENTITY"]


def test_frozen_templates_are_source_backed_and_canonical_kernel_is_unaltered():
    contract = proof._contract()
    tree = ast.parse((ROOT / "src/lyme_gap_atlas_data/semantic_release.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in contract["current_prefixes"]:
            assert node.body[0].value.args[1].value == contract["current_prefixes"][node.name]
    v071 = (ROOT / "migrations/V071__governed_semantic_release_storage.sql").read_text()
    for old, index in (("SEMANTIC_COUNTY_ATLAS", 0), ("SEMANTIC_OBSERVATIONS", 1)):
        match = re.search(
            r"CREATE TABLE IF NOT EXISTS PRESENTATION\." + old + r"\s*\([\s\S]*?\n\);", v071
        )
        assert match
        expected = match.group().replace(
            "CREATE TABLE IF NOT EXISTS PRESENTATION." + old,
            "CREATE TEMPORARY TABLE " + proof.TABLES[index],
        )
        assert contract["temporary_ddl"][proof.TABLES[index].rsplit(".", 1)[1]] == expected
    source = (ROOT / "migrations/V098__fix_prod_pathogen_canonical_parity.sql").read_text()
    start = source.index("  SELECT COUNT(*), COUNT(p.county_fips)")
    kernel = source[start : source.index(";", start)].strip()
    kernel = re.sub(r"\s+INTO :canonical_count, :reported_count", "", kernel)
    kernel = (
        kernel.replace("CONFORMED.GOVERNED_SOURCE_RECORDS", "proof_governed_records")
        .replace("CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS", "proof_pathogen_records")
        .replace(":INGESTION_RUN_ID", "%s")
    )
    assert contract["canonical_kernel"] == kernel


def test_changed_contract_is_rejected_without_echo(tmp_path, monkeypatch, capsys):
    content = proof._contract()
    content["private"] = PRIVATE
    module = tmp_path / "module.py"
    module.write_text("fixture")
    module.with_name("failure_engine_proof_contract_v1.json").write_text(json.dumps(content))
    monkeypatch.setattr(proof, "__file__", str(module))
    with pytest.raises(proof.ProofRejected):
        proof.make_plan(COMMIT)
    assert capsys.readouterr() == ("", "")


def test_prior_query_id_is_not_correlated_to_failed_submission():
    class StaleCursor:
        sfqid = None

        def execute(self, sql, parameters):
            if self.sfqid is not None:
                raise PrivateFailure()
            self.sfqid = "00000000-0000-0000-0000-000000000001"

        def fetchone(self):
            return (PRIVATE, proof.ROLE, proof.DATABASE, proof.WAREHOUSE, None)

    runner = proof._Runner(StaleCursor(), Clock())
    runner.execute("IDENTITY")
    with pytest.raises(PrivateFailure):
        runner.execute("TIMEOUTS")
    assert runner.records[0]["query_id"] != "UNKNOWN"
    assert runner.records[1]["query_id"] == "UNKNOWN"


def test_cooperative_cancel_blocks_normal_work_but_allows_cleanup():
    session = FixtureSession()
    runner = proof._Runner(session.cursor(), Clock(), lambda: True)
    with pytest.raises(proof.ProofRejected):
        runner.execute("IDENTITY")
    runner.execute("ROLLBACK", cleanup=True)
    assert session.calls == ["ROLLBACK"]


def test_actual_connector_mismatch_rejects_without_queries(monkeypatch):
    import snowflake.connector

    monkeypatch.setattr(snowflake.connector, "__version__", PRIVATE)
    session = FixtureSession()
    plan = proof.make_plan(COMMIT)
    result = proof.run_proof(
        session, plan, approved_plan_sha256=proof.plan_hash(plan), expected_user=PRIVATE
    )
    assert result["state"] == "CONNECTOR_VERSION_REJECTED"
    assert result["connector_version"] == "UNKNOWN"
    assert session.calls == []


def test_cancelled_run_rolls_back_and_drops_only_owned_objects():
    session = FixtureSession()
    plan = proof.make_plan(COMMIT)
    result = proof.run_proof(
        session,
        plan,
        approved_plan_sha256=proof.plan_hash(plan),
        expected_user=PRIVATE,
        cancelled=lambda: "BEGIN" in session.calls,
    )
    assert result["state"] == "FAIL"
    assert result["connector_version"] == "4.3.0"
    assert not any(op.startswith("NEGATIVE_") for op in session.calls)
    assert result["cleanup"]["rollback"] == "PASS"
    assert result["cleanup"]["drops"] == "PASS"
    assert result["cleanup"]["session_close"] == "PASS"
