import ast
import json
import os
import runpy
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/verify_climate_dev_views.py"
MODULE = runpy.run_path(str(SCRIPT))


def test_compiled_body_comparison_preserves_projection_changes() -> None:
    body = MODULE["body"]
    assert body('CREATE VIEW "V" ("A") AS SELECT "A" FROM "T";') == body(
        'CREATE OR REPLACE VIEW V AS SELECT  "A"  FROM  "T"'
    )
    assert body("CREATE VIEW V AS SELECT a FROM t") != body("CREATE VIEW V AS SELECT b FROM t")
    assert body("CREATE VIEW V AS SELECT 'DAY' FROM t") != body(
        "CREATE VIEW V AS SELECT 'day' FROM t"
    )


def test_comparison_preserves_variant_keys_and_quoted_identifiers() -> None:
    body = MODULE["body"]
    assert body("CREATE VIEW V AS SELECT payload:record FROM t") != body(
        "CREATE VIEW V AS SELECT payload:Record FROM t"
    )
    assert body('CREATE VIEW V AS SELECT "county" FROM t') != body(
        'CREATE VIEW V AS SELECT "COUNTY" FROM t'
    )
    assert body('CREATE VIEW V AS SELECT "a b" FROM t') != body(
        'CREATE VIEW V AS SELECT "ab" FROM t'
    )
    assert body("CREATE VIEW V AS SELECT '--keep' FROM t --remove") == body(
        "CREATE VIEW V AS SELECT '--keep' FROM t"
    )


def test_comparison_preserves_token_separators_including_comments() -> None:
    body = MODULE["body"]
    assert body("CREATE VIEW V AS SELECT record:value AS value FROM t") != body(
        "CREATE VIEW V AS SELECT record:valueASvalue FROM t"
    )
    assert body("CREATE VIEW V AS SELECT a/* separator */AS value FROM t") == body(
        "CREATE VIEW V AS SELECT a AS value FROM t"
    )
    assert body("CREATE VIEW V AS SELECT a/* separator */AS value FROM t") != body(
        "CREATE VIEW V AS SELECT aASvalue FROM t"
    )


def test_reviewed_view_split_keeps_literal_and_comment_semicolons() -> None:
    sql = (ROOT / "sql/january_climate_consumer_views.sql").read_text()
    reviewed = MODULE["proposals"](sql)
    assert len(reviewed) == 2
    assert "not a midnight calendar day" in reviewed[0]
    assert "FROM records;" in reviewed[0]
    assert "CURRENT_CLIMATE_MEASURE_METADATA_V" in reviewed[1]


def test_diagnostic_execute_surface_is_read_only() -> None:
    tree = ast.parse(SCRIPT.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "execute":
            continue
        argument = node.args[0]
        prefix = argument.value if isinstance(argument, ast.Constant) else argument.values[0].value
        assert prefix.startswith(("SELECT ", "SHOW ", "DESCRIBE VIEW "))


@pytest.mark.parametrize("scalar", [False, True])
def test_observation_read_is_bounded_after_full_count_timed_out(scalar: bool) -> None:
    filename = (
        "january_climate_consumer_views_scalar_join.sql"
        if scalar
        else "january_climate_consumer_views.sql"
    )
    reviewed = (ROOT / "sql" / filename).read_text()
    definitions = MODULE["proposals"](reviewed)

    class Cursor:
        calls: list[str] = []
        description = [
            (name,)
            for name in (
                "RELEASE_ID",
                "MEASURE_ID",
                "COUNTY_FIPS",
                "PERIOD_START",
                "VALUE",
                "VALUE_STATE",
                "UNIT",
            )
        ]

        def execute(self, sql: str) -> None:
            self.calls.append(sql)
            self.current = sql

        def fetchone(self) -> tuple[object, ...]:
            if "CURRENT_USER()" in self.current:
                return (MODULE["USER"], MODULE["ROLE"], MODULE["DEV"], MODULE["WAREHOUSE"])
            if "GET_DDL" in self.current:
                return (definitions[0 if MODULE["NAMES"][0] in self.current else 1],)
            return (4,)

        def fetchall(self) -> list[tuple[object, ...]]:
            if "version='V147'" in self.current:
                return (
                    [("V147__dev_climate_scalar_membership_join.sql", MODULE["SCALAR_CHECKSUM"])]
                    if scalar
                    else []
                )
            if "SCHEMA_MIGRATIONS" in self.current:
                return [("V136__dev_january_climate_consumer_views.sql", MODULE["CHECKSUM"])]
            if "VALUE, VALUE_STATE, UNIT" in self.current:
                return [
                    (
                        "release",
                        "nclimgrid_prcp_county_day",
                        "08031",
                        "2025-01-15",
                        1.2,
                        "OBSERVED",
                        "mm",
                    )
                ]
            return []

    cursor = Cursor()
    report = MODULE["verify"](cursor, reviewed)
    observation = report["views"][0]
    assert report["v147_checksum"] == (MODULE["SCALAR_CHECKSUM"] if scalar else None)
    assert all(view["normalized_body_matches_reviewed"] for view in report["views"])
    assert observation["successful_row_count"] is None
    assert observation["bounded_sample"][0]["VALUE"] == 1.2
    assert any("COUNT(*)" in sql and MODULE["NAMES"][1] in sql for sql in cursor.calls)
    assert not any("COUNT(*)" in sql and MODULE["NAMES"][0] in sql for sql in cursor.calls)


def test_wrong_identity_stops_before_view_inspection() -> None:
    class Cursor:
        calls = []

        def execute(self, sql: str) -> None:
            self.calls.append(sql)

        def fetchone(self) -> tuple[str, ...]:
            return ("human", "owner", "PROD", "warehouse")

    cursor = Cursor()
    with pytest.raises(ValueError, match="CLIMATE_VIEW_IDENTITY"):
        MODULE["verify"](cursor, "")
    assert len(cursor.calls) == 1


def test_workflow_read_only_mode_exits_before_migration() -> None:
    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    mode = workflow.split('if [ "$DIAGNOSE_CLIMATE_VIEWS" = "true" ]; then', 1)[1].split(
        "          # Bound only the exact January view migration", 1
    )[0]
    assert "scripts/verify_climate_dev_views.py" in mode
    assert "timeout --signal=INT --kill-after=15s 300s" in mode
    assert "exit 0" in mode
    assert "apply-reviewed" not in mode
    assert workflow.index(mode) < workflow.index(
        '-q "SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE()'
    )


@pytest.mark.parametrize("kind", ["readback", "apply"])
@pytest.mark.parametrize(
    "override",
    [
        {},
        {"DIAGNOSE_JANUARY_PAIR": "true"},
        {"DIAGNOSE_INTELLIGENCE_DEV": "true"},
        {"REGISTER_EID_EXPEDITED_DEV": "true"},
        {"DIAGNOSE_QUERY_ID": "unapproved-query"},
        {"EXPECTED_PENDING_JSON": '[{"version":"V147"}]'},
        {"GITHUB_REF": "refs/heads/feature"},
        {"REVIEWED_COMMIT": "b" * 40},
    ],
)
def test_actual_workflow_climate_dispatch_never_calls_cli_sql(
    tmp_path: Path, override: dict[str, str], kind: str
) -> None:
    # Execute the actual dispatch shell with command fakes. Invalid combinations
    # must stop before any Snowflake path; the valid mode calls the verifier once.
    import yaml

    bash = shutil.which("bash") if os.name != "nt" else None
    if not bash:
        pytest.skip("Linux workflow shell is validated by exact-head Linux Quality")
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-dev.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    calls = tmp_path / "calls"
    environment = {
        **os.environ,
        **{key: "false" for key in step["env"]},
        "RUNNER_TEMP": str(tmp_path),
        "SNOWFLAKE_PRIVATE_KEY_B64": "",
        "EXPECTED_PENDING_JSON": "[]"
        if kind == "readback"
        else json.dumps(
            [
                {
                    "version": "V147",
                    "filename": "V147__dev_climate_scalar_membership_join.sql",
                    "sha256": MODULE["SCALAR_CHECKSUM"],
                }
            ]
        ),
        "DIAGNOSE_CLIMATE_VIEWS": "true" if kind == "readback" else "false",
        "DIAGNOSE_QUERY_ID": "",
        "JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE": "",
        "REVIEWED_COMMIT": "a" * 40,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_REF": "refs/heads/main",
        "CALLS": str(calls),
        "PYTHON_EXECUTABLE": sys.executable,
        **override,
    }
    fakes = """
    uv() {
      if [[ "$*" == *scripts/verify_climate_dev_views.py* ]]; then
        printf '%s\\n' "verifier:$MAX_CON_RETRY_ATTEMPTS" >> "$CALLS"
      else
        source="$(cat)"
        if [[ "$source" == *apply_reviewed_dev_migrations_command* ]]; then
          message="apply:$MAX_CON_RETRY_ATTEMPTS:$ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"
          printf '%s\\n' "$message" >> "$CALLS"
        else
          "$PYTHON_EXECUTABLE" -c "$source"
        fi
      fi
    }
    gh() { echo 1; }
    git() { echo "$GITHUB_SHA"; }
    snow() { echo unexpected-sql >> "$CALLS"; return 99; }
    timeout() { shift 3; "$@"; }
    """
    result = subprocess.run(
        [bash, "-c", fakes + step["run"]],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if override:
        assert result.returncode != 0
        assert not calls.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert calls.read_text().splitlines() == (
            ["verifier:0"] if kind == "readback" else ["apply:0:60"]
        )


@pytest.mark.parametrize("identity_matches", [True, False])
def test_actual_v147_inline_identity_gate_precedes_existing_cli(
    monkeypatch: pytest.MonkeyPatch, identity_matches: bool
) -> None:
    import lyme_gap_atlas_data.cli as cli

    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    mode = workflow.split('if [ "$climate_v147_batch" = "true" ]; then', 1)[1]
    inline = textwrap.dedent(mode.split("<<'PY'\n", 1)[1].split("\n          PY", 1)[0])
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return self

        def execute(self, sql):
            calls.append(sql)

        def fetchone(self):
            return (
                tuple(MODULE[key] for key in ("USER", "ROLE", "DEV", "WAREHOUSE"))
                if identity_matches
                else ("wrong",) * 4
            )

    monkeypatch.setattr(runpy, "run_path", lambda path: {"bounded_connection": Connection})
    monkeypatch.setattr(
        cli, "apply_reviewed_dev_migrations_command", lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setenv("EXPECTED_PENDING_JSON", "exact-scope")
    monkeypatch.setenv("GITHUB_SHA", "reviewed-sha")
    if identity_matches:
        exec(compile(inline, "workflow-v147", "exec"), {})
        assert calls[-1] == {
            "database": MODULE["DEV"],
            "expected_pending_json": "exact-scope",
            "commit": "reviewed-sha",
            "confirm": True,
            "feed_preflight_accounting_confirmed": False,
        }
    else:
        with pytest.raises(SystemExit, match="CLIMATE_MIGRATION_IDENTITY"):
            exec(compile(inline, "workflow-v147", "exec"), {})
        assert len(calls) == 1


def test_server_timeouts_are_present_before_any_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    bounded_connection = MODULE["bounded_connection"]
    parameters = {"session_parameters": {"QUERY_TAG": "old"}, "role": "existing-role"}
    captured = {}
    sentinel = object()
    monkeypatch.setitem(bounded_connection.__globals__, "SnowflakeSettings", lambda: object())
    monkeypatch.setitem(
        bounded_connection.__globals__, "connection_parameters", lambda settings: parameters
    )

    def connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setitem(bounded_connection.__globals__, "connect", connect)
    assert bounded_connection() is sentinel
    assert captured["role"] == "existing-role"
    assert captured["network_timeout"] == captured["socket_timeout"] == 65
    assert captured["session_parameters"] == {
        "QUERY_TAG": "atlas-climate-dev-view-readback",
        "STATEMENT_TIMEOUT_IN_SECONDS": 60,
        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 10,
        "ABORT_DETACHED_QUERY": True,
    }
