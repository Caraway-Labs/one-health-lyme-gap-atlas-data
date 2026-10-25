"""Query-policy paper approval (ADR 0023): module, CLI, migration contract, preflight, status."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lyme_gap_atlas_data import cli as cli_module
from lyme_gap_atlas_data import literature_preflight as preflight_module
from lyme_gap_atlas_data import literature_status as status_module
from lyme_gap_atlas_data import paper_policy
from lyme_gap_atlas_data.settings import PipelineSettings

RUN_ID = str(uuid.uuid4())
MIGRATION = Path("migrations/V169__paper_policy_approval.sql")
POLICY_SETTINGS = PipelineSettings(
    _env_file=None,  # type: ignore[call-arg]
    paper_approval_mode="query_policy_v1",
)


class FakeCursor:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = answers
        self.statements: list[tuple[str, Any]] = []

    def execute(self, sql: str, args: Any = None) -> None:
        self.statements.append((sql, args))

    def fetchone(self) -> Any:
        return self.answers.pop(0)


def _patch_connect(monkeypatch: pytest.MonkeyPatch, cursor: FakeCursor) -> None:
    class Connection:
        @contextmanager
        def cursor(self) -> Iterator[FakeCursor]:
            yield cursor

    @contextmanager
    def fake_connect(_settings: object) -> Iterator[Connection]:
        yield Connection()

    monkeypatch.setattr(paper_policy, "connect", fake_connect)


def test_settings_default_to_human_review_and_reject_unknown_modes() -> None:
    assert PipelineSettings(_env_file=None).paper_approval_mode == "human_review"  # type: ignore[call-arg]
    assert POLICY_SETTINGS.paper_approval_mode == "query_policy_v1"
    with pytest.raises(ValidationError):
        PipelineSettings(_env_file=None, paper_approval_mode="auto")  # type: ignore[call-arg,arg-type]


def test_approve_calls_only_the_bounded_procedure_and_parses_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "batch_id": "b-1",
        "approved_count": 3,
        "skipped_no_pmcid": 1,
        "skipped_not_awaiting_review": 2,
    }
    cursor = FakeCursor([(json.dumps(payload),)])
    _patch_connect(monkeypatch, cursor)
    result = paper_policy.approve_by_policy(RUN_ID, settings=POLICY_SETTINGS, correlation_id="c-1")
    assert cursor.statements == [
        (
            "CALL GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(%s, %s, %s)",
            (RUN_ID, "pubmed-query-policy-v1", "c-1"),
        )
    ]
    assert result["approved_count"] == 3
    assert result["skipped_no_pmcid"] == 1
    assert result["skipped_not_awaiting_review"] == 2
    assert result["policy_version"] == "pubmed-query-policy-v1"
    assert result["correlation_id"] == "c-1"
    assert result["dry_run"] is False


def test_approve_accepts_dict_result_and_rejects_malformed_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = {"approved_count": 0, "skipped_no_pmcid": 0, "skipped_not_awaiting_review": 0}
    _patch_connect(monkeypatch, FakeCursor([(good,)]))
    assert paper_policy.approve_by_policy(RUN_ID, settings=POLICY_SETTINGS)["approved_count"] == 0
    for bad in (None, ({"approved_count": 1},), ("[]",)):
        _patch_connect(monkeypatch, FakeCursor([bad]))
        with pytest.raises(RuntimeError):
            paper_policy.approve_by_policy(RUN_ID, settings=POLICY_SETTINGS)


def test_policy_requires_the_mode_and_a_uuid() -> None:
    human = PipelineSettings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="PAPER_APPROVAL_MODE"):
        paper_policy.approve_by_policy(RUN_ID, settings=human)
    with pytest.raises(ValueError, match="PAPER_APPROVAL_MODE"):
        paper_policy.preview_policy_approval(RUN_ID, settings=human)
    with pytest.raises(ValueError, match="UUID"):
        paper_policy.approve_by_policy("not-a-uuid", settings=POLICY_SETTINGS)


def test_preview_is_read_only_and_reports_the_three_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor([("COMPLETED",), (4, 1, 2)])
    _patch_connect(monkeypatch, cursor)
    result = paper_policy.preview_policy_approval(RUN_ID, settings=POLICY_SETTINGS)
    assert result == {
        "discovery_run_id": RUN_ID,
        "policy_version": "pubmed-query-policy-v1",
        "dry_run": True,
        "approved_count": 4,
        "skipped_no_pmcid": 1,
        "skipped_not_awaiting_review": 2,
    }
    assert all(sql.lstrip().startswith("SELECT") for sql, _ in cursor.statements)
    assert not any("CALL" in sql for sql, _ in cursor.statements)


@pytest.mark.parametrize(
    ("answers", "message"),
    [([None], "not found"), ([("RUNNING",)], "not COMPLETED"), ([("FAILED",)], "not COMPLETED")],
)
def test_preview_rejects_unknown_or_incomplete_runs(
    monkeypatch: pytest.MonkeyPatch, answers: list[Any], message: str
) -> None:
    cursor = FakeCursor(list(answers))
    _patch_connect(monkeypatch, cursor)
    with pytest.raises(ValueError, match=message):
        paper_policy.preview_policy_approval(RUN_ID, settings=POLICY_SETTINGS)
    assert len(cursor.statements) == 1


# --- CLI ---------------------------------------------------------------------------------


def _invoke(*args: str, mode: str = "query_policy_v1") -> Any:
    env = {"PAPER_APPROVAL_MODE": mode, "TOPX_ENV": "dev"}
    return CliRunner().invoke(
        cli_module.app, ["pipeline", "pubmed-approve-by-policy", *args], env=env
    )


def test_cli_requires_exactly_one_of_dry_run_or_confirm() -> None:
    for flags in ((), ("--dry-run", "--confirm")):
        result = _invoke("--discovery-run-id", RUN_ID, *flags)
        assert result.exit_code != 0


def test_cli_dry_run_and_confirm_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        cli_module,
        "preview_policy_approval",
        lambda run_id, settings: calls.append("preview") or {"dry_run": True, "run": run_id},
    )
    monkeypatch.setattr(
        cli_module,
        "approve_by_policy",
        lambda run_id, settings: calls.append("approve") or {"dry_run": False, "run": run_id},
    )
    dry = _invoke("--discovery-run-id", RUN_ID, "--dry-run")
    assert dry.exit_code == 0 and json.loads(dry.stdout)["dry_run"] is True
    confirmed = _invoke("--discovery-run-id", RUN_ID, "--confirm")
    assert confirmed.exit_code == 0 and json.loads(confirmed.stdout)["dry_run"] is False
    assert calls == ["preview", "approve"]


def test_cli_refuses_without_policy_mode_and_redacts_the_failure() -> None:
    result = _invoke("--discovery-run-id", RUN_ID, "--confirm", mode="human_review")
    assert result.exit_code == 1
    failure = json.loads(result.stderr.strip().splitlines()[-1])
    assert failure["command"] == "pubmed_approve_by_policy"
    assert failure["failure_category"] == "policy_approval"
    assert "PAPER_APPROVAL_MODE" not in result.stderr


def test_discover_command_exits_nonzero_when_policy_approval_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "literature_preflight", lambda *_a, **_k: {"status": "READY"})
    monkeypatch.setattr(
        cli_module,
        "discover_pubmed",
        lambda *_a, **_k: {
            "status": "COMPLETED",
            "policy_approval": {"status": "FAILED", "error_type": "RuntimeError"},
        },
    )
    result = CliRunner().invoke(
        cli_module.app,
        ["pipeline", "pubmed-discover", "--family", "vector_host_pathogen"],
        env={"TOPX_ENV": "dev"},
    )
    assert result.exit_code == 1
    assert '"status": "COMPLETED"' in result.stdout


# --- migration contract (ADR 0023 / ADR 0030 boundary) ----------------------------------


def _migration() -> str:
    """Executable SQL only: comments may name the boundaries they preserve."""
    lines = MIGRATION.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("--"))


def test_migration_approves_only_the_policy_set_and_never_rejects_or_defers() -> None:
    sql = _migration()
    assert "EXECUTE AS OWNER" in sql
    assert "p.state = 'awaiting_review' AND p.pmcid IS NOT NULL" in sql
    assert "ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids)" in sql
    assert "run_status <> 'COMPLETED'" in sql
    assert "P_POLICY_VERSION <> 'pubmed-query-policy-v1'" in sql
    assert "'policy:pubmed-query-v1'" in sql
    assert "'paper_policy_approval'" in sql
    assert "'rejected'" not in sql and "'deferred'" not in sql
    decisions = re.findall(r"'approved'", sql)
    assert decisions, "the procedure must write approved decisions"


def test_migration_does_not_consult_or_touch_the_steward_boundary() -> None:
    sql = _migration()
    assert "APPROVAL_STEWARDS" not in sql
    assert "SP_RECORD_PAPER_REVIEW_BATCH" not in sql
    assert "GRANT OWNERSHIP" not in sql
    grants = re.findall(r"GRANT\s+(\w+)\s+ON\s+(\w+)\s+(\S+)", sql)
    assert grants == [("USAGE", "PROCEDURE", "GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(VARCHAR,")]
    granted_to = re.findall(r"TO ROLE ([^;]+);", sql)
    assert granted_to == ["OH_LYME_{{ ENV }}_RUNTIME"]
    assert "COPY CURRENT GRANTS" not in sql


def test_migration_renders_for_dev_and_prod_without_remaining_placeholders() -> None:
    from lyme_gap_atlas_data.migrations import load_migrations, render_migration

    migration = next(item for item in load_migrations() if item.version == "V169")
    for database, env in (
        ("ONE_HEALTH_LYME_GAP_ATLAS_DEV", "DEV"),
        ("ONE_HEALTH_LYME_GAP_ATLAS_PROD", "PROD"),
    ):
        rendered = render_migration(migration, database)
        assert "{{" not in rendered
        assert f"OH_LYME_{env}_RUNTIME" in rendered
        assert f"USE DATABASE {database};" in rendered


# --- preflight ---------------------------------------------------------------------------

_DB = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"


class _PreflightCursor:
    def __enter__(self) -> _PreflightCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, *_args: object) -> None:
        return None

    def fetchone(self) -> tuple[str, str]:
        return ("RUNTIME", _DB)

    def fetchall(self) -> list[tuple[str, ...]]:
        return [("PMID",)]


class _PreflightConnection:
    def __enter__(self) -> _PreflightConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _PreflightCursor:
        return _PreflightCursor()


def _missing(
    monkeypatch: pytest.MonkeyPatch, mode: str, grants: list[tuple[str, str, str]], operation: str
) -> list[str]:
    monkeypatch.setattr(preflight_module, "connect", lambda _s: _PreflightConnection())
    monkeypatch.setattr(preflight_module, "_effective_grants", lambda _c, _r: grants)
    settings = PipelineSettings(
        _env_file=None,  # type: ignore[call-arg]
        snowflake_role="RUNTIME",
        snowflake_database=_DB,
        paper_approval_mode=mode,  # type: ignore[arg-type]
    )
    result = preflight_module._snowflake_contract(settings, operation)["missing_capabilities"]
    assert isinstance(result, list)
    return [str(item) for item in result]


_POLICY_PROCEDURE = (
    "USAGE",
    "PROCEDURE",
    f"{_DB}.GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(VARCHAR, VARCHAR, VARCHAR):VARIANT",
)


def test_policy_mode_requires_the_policy_procedure_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = _missing(monkeypatch, "query_policy_v1", [], "discover")
    assert "GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL:USAGE" in blocked
    ready = _missing(monkeypatch, "query_policy_v1", [_POLICY_PROCEDURE], "discover")
    assert "GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL:USAGE" not in ready
    assert not any(item.startswith("FORBIDDEN:") for item in ready)


@pytest.mark.parametrize(
    ("grant", "capability"),
    [
        (
            (
                "USAGE",
                "PROCEDURE",
                f"{_DB}.GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(ARRAY, VARCHAR)",
            ),
            "FORBIDDEN:GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH",
        ),
        (
            ("INSERT", "TABLE", f"{_DB}.KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS"),
            "FORBIDDEN:KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS:WRITE",
        ),
        (
            ("UPDATE", "TABLE", f"{_DB}.KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS"),
            "FORBIDDEN:KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS:WRITE",
        ),
    ],
)
def test_policy_mode_blocks_a_runtime_that_could_approve_directly(
    monkeypatch: pytest.MonkeyPatch, grant: tuple[str, str, str], capability: str
) -> None:
    missing = _missing(monkeypatch, "query_policy_v1", [_POLICY_PROCEDURE, grant], "discover")
    assert capability in missing
    # A read-only SELECT on the decision ledger is not a write path.
    select = ("SELECT", "TABLE", f"{_DB}.KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS")
    allowed = _missing(monkeypatch, "query_policy_v1", [_POLICY_PROCEDURE, select], "discover")
    assert not any(item.startswith("FORBIDDEN:") for item in allowed)


@pytest.mark.parametrize("operation", ["discover", "extract", "build-corpus"])
def test_human_review_mode_adds_no_policy_requirements(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    missing = _missing(monkeypatch, "human_review", [], operation)
    assert not any("POLICY" in item or item.startswith("FORBIDDEN:") for item in missing)


def test_forbidden_capability_is_reported_with_a_revoke_action() -> None:
    def contract(_settings: PipelineSettings, _operation: str) -> dict[str, object]:
        return {"missing_capabilities": ["FORBIDDEN:GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH"]}

    result = preflight_module.literature_preflight(
        POLICY_SETTINGS,
        operation="discover",
        snowflake_probe=contract,
        spaces_probe=lambda _s: None,
    )
    blockers = [b for b in result["blockers"] if str(b["capability"]).startswith("FORBIDDEN:")]
    assert [b["next_action"] for b in blockers] == ["revoke_runtime_privilege"]


# --- status ------------------------------------------------------------------------------


def test_decision_sources_split_policy_and_steward_approvals() -> None:
    cursor = FakeCursor([(2, 5)])
    sources = status_module._decision_sources(cursor, [("1",), ("2",), ("1",)])
    assert sources == {"status": "CHECKED", "approved_by_policy": 2, "approved_by_steward": 5}
    assert json.loads(cursor.statements[0][1][0]) == ["1", "2"]


def test_decision_sources_degrade_without_failing_the_status_report() -> None:
    class Unreadable:
        def execute(self, *_args: object) -> None:
            raise RuntimeError("insufficient privileges on PAPER_STATE_EVENTS")

    assert status_module._decision_sources(Unreadable(), [("1",)]) == {"status": "NOT_ATTRIBUTED"}
    assert status_module._decision_sources(FakeCursor([None]), [("1",)]) == {
        "status": "NOT_ATTRIBUTED"
    }
