import json
import runpy
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "docs" / "delivery" / "examples"
validate_handoff = runpy.run_path(str(REPO / "scripts" / "validate_handoff.py"))["validate_handoff"]


def test_handoff_examples_validate() -> None:
    for path in EXAMPLES.glob("*.json"):
        assert validate_handoff(json.loads(path.read_text(encoding="utf-8"))) == []


def test_handoff_rejects_missing_workload_identity() -> None:
    assert "missing workload field: deployed_artifact" in validate_handoff(
        {
            "outcome": "x",
            "starting_commit": "1234567",
            "date": "2026-09-21",
            "scope": "x",
            "non_goals": "x",
            "workload": {},
            "verification": {},
        }
    )
