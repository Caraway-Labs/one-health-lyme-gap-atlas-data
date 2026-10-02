"""Routing evidence must reject ambiguous output and observed actions."""

import json
import runpy
from pathlib import Path

import pytest

HELPER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/verify_atlas_metadata_routing.py")
)


def outputs():
    return {"cases": [{"id": case[0], "skill": case[2]} for case in HELPER["CASES"]]}


def trace(data, tools=()):
    return [
        {"type": "thread.started"},
        {"type": "turn.started", "model": HELPER["MODEL"]},
        *tools,
        {
            "type": "item.completed",
            "item": {"id": "response", "type": "agent_message", "text": json.dumps(data)},
        },
        {"type": "turn.completed", "usage": {"output_tokens": 100}},
    ]


@pytest.mark.parametrize("lifecycle", ["completed_only", "started_and_completed", "updated"])
def test_tool_lifecycles_count_once_and_prevent_pass(lifecycle):
    item = {"id": "tool", "type": "command_execution"}
    tools = [{"type": "item.completed", "item": item}]
    if lifecycle == "started_and_completed":
        tools.insert(0, {"type": "item.started", "item": item})
    elif lifecycle == "updated":
        tools.insert(0, {"type": "item.updated", "item": item})
    report = HELPER["summarize"](outputs(), trace(outputs(), tools))
    assert report["status"] == "FAIL"
    assert report["observed_tool_calls"] == 1


def test_observed_command_prevents_metadata_only_pass():
    with pytest.raises(ValueError, match="Incomplete routing lifecycle"):
        HELPER["summarize"](
            outputs(),
            trace(
                outputs(),
                [{"type": "item.started", "item": {"id": "tool", "type": "command_execution"}}],
            ),
        )


def test_missing_case_remains_unknown():
    data = outputs()
    data["cases"].pop()
    report = HELPER["summarize"](data, trace(data))
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


@pytest.mark.parametrize(
    "kind", ["empty", "incomplete", "malformed", "mismatch", "wrong_model", "bad_event", "no_usage"]
)
def test_empty_incomplete_malformed_or_unexpected_response_rejected(kind):
    events = trace(outputs())
    if kind == "empty":
        events = []
    elif kind == "incomplete":
        events.pop()
    elif kind == "malformed":
        events[2]["item"]["text"] = "private diagnostic"
    elif kind == "mismatch":
        events[2]["item"]["text"] = "{}"
    elif kind == "bad_event":
        events[2] = "private diagnostic"
    elif kind == "no_usage":
        events[-1].pop("usage")
    else:
        events[1]["model"] = "unexpected"
    with pytest.raises(ValueError) as error:
        HELPER["summarize"](outputs(), events)
    assert "private diagnostic" not in str(error.value)
