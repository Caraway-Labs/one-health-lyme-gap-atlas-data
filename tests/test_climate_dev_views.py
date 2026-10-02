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
        "CREATE OR REPLACE VIEW V AS select a from t"
    )
    assert body("CREATE VIEW V AS SELECT a FROM t") != body("CREATE VIEW V AS SELECT b FROM t")


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
