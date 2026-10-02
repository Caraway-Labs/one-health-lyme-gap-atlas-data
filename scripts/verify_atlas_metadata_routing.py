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


def summarize(data: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    actual: dict[str, str] = {}
    for item in data.get("cases", []):
        if item.get("id") in actual:
            raise ValueError("Duplicate routing case")
        if item.get("id") not in {case[0] for case in CASES} or item.get("skill") not in CHOICES:
            raise ValueError("Unsupported routing output")
        actual[item["id"]] = item["skill"]
    calls = sum(
        event.get("item", {}).get("type") not in {"agent_message", "reasoning", "plan"}
        for event in events
        if event.get("type") == "item.started"
    )
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
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except ValueError:
            pass
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
