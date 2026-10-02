"""Opt-in, bounded metadata routing probes; no workflow or deterministic-agent claim."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MODEL = "gpt-6.1-sol"
CASES = (
    (
        "db-positive",
        "Plan an Atlas DEV forward-only migration using current capability contracts "
        "and locked checksums.",
        "atlas-db-change",
    ),
    (
        "source-positive",
        "Onboard an approved public Atlas source through Tier B DEV orchestrator commands, "
        "preserving lineage and missingness.",
        "atlas-source-onboarding",
    ),
    (
        "release-positive",
        "Assess Atlas semantic release readiness with artifact identities, prerequisites "
        "and an evidence handoff.",
        "atlas-release-readiness",
    ),
    (
        "failure-positive",
        "Investigate an actual failed Atlas pipeline run using bounded evidence "
        "and a falsifiable regression.",
        "atlas-failure-investigation",
    ),
    ("db-negative", "Explain SQL joins for a beginner.", "NONE"),
    ("source-negative", "Summarize a public source website without acquiring its data.", "NONE"),
    ("release-negative", "Correct spelling in an ordinary documentation paragraph.", "NONE"),
    ("failure-negative", "Discuss general Python debugging concepts without an incident.", "NONE"),
    (
        "db-near",
        "Describe an old Atlas migration without changing it or planning database work.",
        "NONE",
    ),
    (
        "source-near",
        "Inspect a dataset description without onboarding or acquiring the source.",
        "NONE",
    ),
    (
        "release-near",
        "Explain an historical release to a nontechnical reader; "
        "no readiness assessment or promotion.",
        "NONE",
    ),
    (
        "failure-near",
        "Explain a hypothetical Snowflake error; no actual failure or investigation.",
        "NONE",
    ),
)
CHOICES = sorted({item[2] for item in CASES})
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cases"],
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "skill"],
                "properties": {
                    "id": {"type": "string", "enum": [item[0] for item in CASES]},
                    "skill": {"type": "string", "enum": CHOICES},
                },
            },
        }
    },
}


def trace_calls(data: dict[str, Any], events: list[dict[str, Any]]) -> int:
    """Require one completed turn and matching response; count unique tool item IDs."""
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError("Malformed routing trace")
    counts = {"thread.started": 0, "turn.started": 0, "turn.completed": 0}
    items: dict[str, dict[str, Any]] = {}
    substantive = False
    for event in events:
        kind = event.get("type")
        if kind in counts:
            if kind == "thread.started" and any(counts.values()):
                raise ValueError("Out-of-order routing trace")
            if kind == "turn.started" and counts != {
                "thread.started": 1,
                "turn.started": 0,
                "turn.completed": 0,
            }:
                raise ValueError("Out-of-order routing trace")
            if kind == "turn.completed" and counts != {
                "thread.started": 1,
                "turn.started": 1,
                "turn.completed": 0,
            }:
                raise ValueError("Out-of-order routing trace")
            counts[kind] += 1
            if any(event.get(key, MODEL) != MODEL for key in ("model", "model_id")):
                raise ValueError("Unexpected trace model")
            if kind == "turn.completed":
                usage = event.get("usage", {})
                if not substantive or not isinstance(usage.get("output_tokens"), int):
                    raise ValueError("Incomplete routing trace")
                if usage["output_tokens"] <= 0:
                    raise ValueError("Empty routing response")
        elif kind in {"item.started", "item.updated", "item.completed"}:
            if counts["turn.started"] != 1 or counts["turn.completed"]:
                raise ValueError("Out-of-order routing trace")
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("Malformed routing item")
            identifier, item_type = item["id"], item.get("type")
            if not identifier or not isinstance(item_type, str) or not item_type:
                raise ValueError("Malformed routing item")
            previous = items.setdefault(
                identifier, {"type": item_type, "complete": False, "started": False}
            )
            if previous["type"] != item_type or previous["complete"]:
                raise ValueError("Ambiguous routing lifecycle")
            if kind == "item.started":
                if previous["started"]:
                    raise ValueError("Ambiguous routing lifecycle")
                previous["started"] = True
            if kind == "item.completed":
                previous["complete"] = True
                if item_type == "agent_message":
                    try:
                        matched = json.loads(item["text"]) == data
                    except (KeyError, TypeError, ValueError):
                        raise ValueError("Malformed routing response") from None
                    if not matched or substantive:
                        raise ValueError("Unexpected routing response")
                    substantive = True
        else:
            raise ValueError("Unsupported routing trace")
    if any(count != 1 for count in counts.values()) or not substantive:
        raise ValueError("Incomplete routing trace")
    if not all(item["complete"] for item in items.values()):
        raise ValueError("Incomplete routing lifecycle")
    return sum(
        item["type"] not in {"agent_message", "reasoning", "plan"} for item in items.values()
    )


def summarize(data: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {"cases"} or not isinstance(data["cases"], list):
        raise ValueError("Malformed routing output")
    actual: dict[str, str] = {}
    for item in data.get("cases", []):
        if not isinstance(item, dict) or set(item) != {"id", "skill"}:
            raise ValueError("Malformed routing output")
        if item.get("id") in actual:
            raise ValueError("Duplicate routing case")
        if item.get("id") not in {case[0] for case in CASES} or item.get("skill") not in CHOICES:
            raise ValueError("Unsupported routing output")
        actual[item["id"]] = item["skill"]
    calls = trace_calls(data, events)
    cases = [
        {
            "id": identifier,
            "expected": expected,
            "selected": actual.get(identifier, "UNKNOWN"),
            "matches": actual.get(identifier) == expected,
        }
        for identifier, _task, expected in CASES
    ]
    return {
        "evidence_class": "observed_metadata_routing_probe",
        "model": MODEL,
        "reasoning": "low",
        "model_evidence": "explicit_cli_request; no independent server model attestation",
        "completed_response_verified": True,
        "launch": "disposable_isolated_repository_fixture",
        "observed_tool_calls": calls,
        "cases": cases,
        "status": "PASS" if calls == 0 and all(case["matches"] for case in cases) else "FAIL",
        "limitations": [
            "Metadata selection only; no end-to-end workflow or deterministic-agent proof."
        ],
    }


def probe(binary: Path, root: Path) -> dict[str, Any]:
    if binary.name not in {"codex", "codex.exe"} or not binary.is_file():
        raise ValueError("Expected an installed Codex executable")
    # Only public repository skills are copied; credentials/config/history/logs are not.
    fixture = Path(tempfile.mkdtemp(prefix="atlas-routing-"))
    for name in CHOICES:
        if name != "NONE":
            destination = fixture / ".agents/skills" / name
            shutil.copytree(root / ".agents/skills" / name, destination)
    subprocess.run(
        ["git", "init", "--quiet", str(fixture)], check=True, capture_output=True, timeout=10
    )
    schema = fixture / "routing.schema.json"
    result_file = fixture / "routing.result.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    prompt = (
        "Read-only metadata routing check. For each task below select one discoverable repository "
        "skill only if its metadata actually applies, otherwise NONE. Do not run commands, call "
        "tools, read files, execute SQL, deploy, or request credentials. "
        "These are selection probes, "
        "not work requests. Tasks: "
        + json.dumps([{"id": identifier, "task": task} for identifier, task, _expected in CASES])
    )
    execution = subprocess.run(
        [
            str(binary),
            "-a",
            "never",
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--disable",
            "apps",
            "--disable",
            "hooks",
            "--disable",
            "skill_mcp_dependency_install",
            "-m",
            MODEL,
            "-c",
            'model_reasoning_effort="low"',
            "-C",
            str(fixture),
            "--json",
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(result_file),
            "-",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        check=True,
        timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    events = []
    for line in execution.stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Malformed routing trace")
            events.append(value)
        except ValueError:
            raise ValueError("Malformed routing trace") from None
    # Raw stderr/startup/account metadata is never emitted or stored in repository evidence.
    return summarize(json.loads(result_file.read_text(encoding="utf-8")), events)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", type=Path, required=True)
    parser.add_argument("--run-routing", action="store_true", required=True)
    args = parser.parse_args()
    try:
        report = probe(args.codex_bin, Path(__file__).resolve().parents[1])
    except Exception:
        report = {"status": "UNKNOWN", "reason": "ROUTING_PROBE_UNAVAILABLE", "model": MODEL}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
