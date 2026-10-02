"""Read-only local Codex skills/list probe; never starts an agent turn or logs."""

from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

SKILLS = {
    "atlas-db-change",
    "atlas-source-onboarding",
    "atlas-release-readiness",
    "atlas-failure-investigation",
}


def verify_entry(entry: dict[str, Any], root: Path) -> dict[str, Any]:
    selected = [skill for skill in entry.get("skills", []) if skill.get("name") in SKILLS]
    valid = len(selected) == len(SKILLS) and {skill["name"] for skill in selected} == SKILLS
    for skill in selected:
        expected = root / ".agents/skills" / skill["name"] / "SKILL.md"
        path = skill.get("path")
        try:
            valid = valid and skill.get("enabled") is True and isinstance(path, str)
            valid = (
                valid
                and Path(path).is_absolute()
                and (Path(path).resolve(strict=True) == expected.resolve(strict=True))
            )
            valid = valid and expected.resolve(strict=True).is_relative_to(
                root.resolve(strict=True)
            )
        except (OSError, TypeError, ValueError):
            valid = False
    return {
        "skills": sorted(skill["name"] for skill in selected),
        "repository_paths_verified": valid,
        "error_count": len(entry.get("errors", [])),
        "status": "PASS" if valid and not entry.get("errors") else "UNKNOWN",
    }


def discover(binary: Path, root: Path) -> dict[str, Any]:
    if binary.name not in {"codex", "codex.exe"} or not binary.is_file():
        raise ValueError("Expected an installed Codex executable")
    version = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    # Only a version-shaped value may enter public evidence.
    if re.fullmatch(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("Unexpected Codex version output")
    process = subprocess.Popen(
        [str(binary), "app-server", "--stdio"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    responses: queue.Queue[dict[str, Any]] = queue.Queue()

    def read_responses() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    responses.put(value)
            except ValueError:
                pass

    threading.Thread(target=read_responses, daemon=True).start()

    def request(identifier: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert process.stdin is not None
        process.stdin.write(
            json.dumps({"id": identifier, "method": method, "params": params}) + "\n"
        )
        process.stdin.flush()
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Discovery request timed out")
            response = responses.get(timeout=remaining)
            if response.get("id") == identifier:
                return response

    try:
        initialized = request(
            1,
            "initialize",
            {
                "clientInfo": {"name": "atlas_skill_discovery", "version": "1"},
                "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True},
            },
        )
        if "result" not in initialized:
            raise ValueError("Initialization unavailable")
        assert process.stdin is not None
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        result = request(
            2,
            "skills/list",
            {"cwds": [str(root), str(root / "tests")], "forceReload": True},
        )
        entries = result.get("result", {}).get("data", [])
        launches = []
        for label, cwd in (("repo_root", root), ("nested_tests", root / "tests")):
            matches = [item for item in entries if Path(item["cwd"]) == cwd]
            entry = matches[0] if len(matches) == 1 else {}
            launches.append(
                {
                    "launch": label,
                    **verify_entry(entry, root),
                }
            )
        return {
            "evidence_class": "observed_local_skill_discovery",
            "codex_version": version,
            "launches": launches,
            "agent_turn_started": False,
            "status": "PASS" if all(item["status"] == "PASS" for item in launches) else "UNKNOWN",
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = discover(args.codex_bin, Path(__file__).resolve().parents[1])
    except Exception:
        report = {
            "status": "UNKNOWN",
            "reason": "DISCOVERY_UNAVAILABLE",
            "agent_turn_started": False,
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
