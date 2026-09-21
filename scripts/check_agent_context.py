"""Credential-free validation of portable agent-context references."""

from __future__ import annotations

import argparse
from pathlib import Path

REPOSITORY_PATHS = (
    "AGENTS.md",
    "README.md",
    "docs/operations/agent-context.md",
    "docs/contracts/catalog-to-snowflake/operating-model.md",
    "docs/contracts/simplified-ingestion/interface-freeze.md",
    "docs/operations/connection-inventory.md",
    "docs/operations/operation-capabilities-v1.md",
    "docs/adr/0030-snowflake-role-model-simplification.md",
    "config/operation-capabilities-v1.yml",
)
WORKSPACE_PATHS = ("AGENTS.md", "TECHNOLOGY_AND_GOVERNANCE.md")


def missing_context(root: Path, paths: tuple[str, ...]) -> list[str]:
    return [item for item in paths if not (root / item).is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    missing = missing_context(root, REPOSITORY_PATHS)
    if args.workspace is not None:
        missing.extend(
            f"workspace/{item}" for item in missing_context(args.workspace, WORKSPACE_PATHS)
        )
    if missing:
        print("Missing required agent context: " + ", ".join(missing))
        return 1
    print("Agent context: PASS (repository" + (" + workspace" if args.workspace else "") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
