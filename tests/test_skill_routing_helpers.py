"""Routing evidence must reject ambiguous output and observed actions."""

import runpy
from pathlib import Path

import pytest

HELPER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/verify_atlas_metadata_routing.py")
)


def outputs():
    return {"cases": [{"id": case[0], "skill": case[2]} for case in HELPER["CASES"]]}


def test_observed_command_prevents_metadata_only_pass():
    report = HELPER["summarize"](
        outputs(), [{"type": "item.started", "item": {"type": "command_execution"}}]
    )
    assert report["status"] == "FAIL"
    assert report["observed_tool_calls"] == 1


def test_missing_case_remains_unknown():
    data = outputs()
    data["cases"].pop()
    report = HELPER["summarize"](data, [])
    assert report["status"] == "FAIL"
    assert report["cases"][-1]["selected"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["duplicate", "unsupported"])
def test_ambiguous_or_private_output_rejected_without_echo(kind):
    data = outputs()
    data["cases"].append(
        data["cases"][0] if kind == "duplicate" else {"id": "private-value", "skill": "NONE"}
    )
    with pytest.raises(ValueError) as error:
        HELPER["summarize"](data, [])
    assert "private-value" not in str(error.value)
