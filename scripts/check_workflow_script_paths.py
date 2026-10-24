"""Fail when a workflow references a scripts/ path missing from this commit."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Boundary before "scripts/" so "notscripts/foo" is not a hit. Paths under
# another checkout (for example ri706-handoff/scripts/...) are not this repo.
# /app/scripts/ and ./scripts/ are this repo's image and relative paths.
_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])scripts/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
)


def referenced_script_paths(workflow_text: str) -> list[str]:
    """Return repo-relative scripts/ paths referenced by one workflow file."""
    paths: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(workflow_text):
        prefix = workflow_text[: match.start()]
        if prefix.endswith("/") and not (prefix.endswith("/app/") or prefix.endswith("./")):
            continue
        path = match.group(0)
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def missing_script_references(root: Path) -> list[tuple[str, str]]:
    """Return (workflow filename, missing scripts/ path) pairs."""
    missing: list[tuple[str, str]] = []
    workflow_dir = root / ".github" / "workflows"
    workflows = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for path in referenced_script_paths(text):
            if not (root / path).is_file():
                missing.append((workflow.name, path))
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root. Defaults to the parent of this script.",
    )
    args = parser.parse_args(argv)
    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    missing = missing_script_references(root)
    if missing:
        for workflow, path in missing:
            print(f"{workflow}: {path}")
        return 1
    print("workflow script paths: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
