import ast
import runpy
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


def test_observation_read_is_bounded_after_full_count_timed_out() -> None:
    source = SCRIPT.read_text()
    assert "VALUE, VALUE_STATE, UNIT FROM {qualified} LIMIT 4" in source
    assert "if name == NAMES[0]:" in source
    assert "CLIMATE_OBSERVATIONS_EMPTY" in source


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
        'if [ "$DIAGNOSE_CLIMATE_DEV" = "true" ]; then', 1
    )[0]
    assert "scripts/verify_climate_dev_views.py" in mode
    assert "exit 0" in mode
    assert "apply-reviewed" not in mode
