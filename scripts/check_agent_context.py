"""Credential-free validation of portable agent-context references."""

from __future__ import annotations

import argparse
import re
from pathlib import Path, PurePosixPath

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
    ".agents/skills/atlas-db-change/SKILL.md",
    ".agents/skills/atlas-source-onboarding/SKILL.md",
    ".agents/skills/atlas-release-readiness/SKILL.md",
    ".agents/skills/atlas-failure-investigation/SKILL.md",
)
WORKSPACE_PATHS = ("AGENTS.md", "TECHNOLOGY_AND_GOVERNANCE.md")


def missing_context(root: Path, paths: tuple[str, ...]) -> list[str]:
    return [item for item in paths if not (root / item).is_file()]


def resolve_reference(root: Path, base: Path, reference: str) -> Path:
    """Resolve only canonical local paths; never fetch or traverse outside root."""
    parts = PurePosixPath(reference).parts
    if (
        not reference
        or re.fullmatch(r"[A-Za-z0-9_./-]+", reference) is None
        or reference.startswith("/")
        or ".." in parts
        or "." in reference.split("/")
        or "//" in reference
    ):
        raise ValueError("unsupported or malformed reference")
    try:
        target = (base / reference).resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError("unresolvable reference") from error
    if not target.is_relative_to(root.resolve()):
        raise ValueError("reference escapes repository")
    exists = target.is_dir() if reference.endswith("/") else target.is_file()
    if not exists:
        raise ValueError("missing reference")
    return target


def skill_reference_errors(root: Path) -> list[str]:
    """Read entrypoints and declared bullet-list indexes, not a hard-coded path sample.

    SKILL.md Markdown links are relative to the skill. Index bullet declarations
    use backtick-quoted paths relative to the repository. Commands outside bullets
    are prose examples and are never executed. URLs/fragments/queries are unsupported.
    """
    errors: list[str] = []
    for skill in sorted((root / ".agents/skills").glob("*/SKILL.md")):
        source = skill.relative_to(root).as_posix()
        try:
            resolve_reference(root, root, source)
        except ValueError as error:
            errors.append(f"{source}: {error}")
            continue
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", skill.read_text(encoding="utf-8-sig"))
        if "references/workflow.md" not in links:
            errors.append(f"{source}: missing declared reference index")
        for reference in links:
            try:
                resolve_reference(root, skill.parent, reference)
            except ValueError as error:
                errors.append(f"{source}: {error}: {reference}")
        index = skill.parent / "references/workflow.md"
        try:
            resolve_reference(root, skill.parent, "references/workflow.md")
        except ValueError:
            continue
        declarations = 0
        for number, line in enumerate(index.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.startswith("- "):
                continue
            references = re.findall(r"`([^`]+)`", line)
            if not references or line.count("`") != 2 * len(references):
                errors.append(f"{source} index line {number}: malformed reference declaration")
                continue
            for reference in references:
                declarations += 1
                try:
                    resolve_reference(root, root, reference)
                except ValueError as error:
                    errors.append(f"{source} index line {number}: {error}: {reference}")
        if not declarations:
            errors.append(f"{source}: empty reference index")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    missing = missing_context(root, REPOSITORY_PATHS)
    missing.extend(skill_reference_errors(root))
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
