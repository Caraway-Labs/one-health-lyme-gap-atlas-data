"""Registry-derived expectations for Quality.

Workflow checks read parsed YAML properties. Migration membership comes from
``migrations/`` filenames and ``migrations.py``. Intelligence source identity
comes from ``config/intelligence/feed-selection-v1.json`` and the registry
JSON files. The snowflake snapshot file remains the public column-shape
contract; migration versions inside that schema are derived, not counted.

Regenerate the published snapshot schema after a public column change:

    uv run python tests/semantic_contracts.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    MIGRATIONS_DIR,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    Migration,
    load_migrations,
)

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
SELECTION_PATH = REPO / "config" / "intelligence" / "feed-selection-v1.json"
REGISTRY_DIR = REPO / "config" / "intelligence"
SOURCE_DEFINITIONS = REPO / "config" / "sources"
SNAPSHOT_SCHEMA_PATH = REPO / "docs" / "contracts" / "snowflake-snapshots" / "v1.schema.json"

# issues: write is the only write scope the checked-in workflows use.
# contents stays read so a new workflow cannot push or retag.
WRITABLE_PERMISSION_SCOPES = frozenset({"issues"})
FORBIDDEN_TRIGGER_NAMES = frozenset({"pull_request_target"})
FORBIDDEN_LOG_SNIPPETS = (
    'echo "$SNOWFLAKE_PRIVATE_KEY',
    'echo "$SNOWFLAKE_PRIVATE_KEY_B64"',
    'echo "$SPACES_SECRET',
    'echo "$SPACES_SECRET_ACCESS_KEY"',
    "printenv",
)
PATH_COMPARISON = re.compile(r"inputs\.source_definition\s*(==|!=)\s*'([^']+)'")


def migration_records_from_filenames(
    directory: Path = MIGRATIONS_DIR,
) -> list[tuple[str, str, str]]:
    """Return ``(version, filename, sha256)`` in the same order as the loader."""
    records: list[tuple[str, str, str]] = []
    for path in sorted(directory.glob("V*__*.sql")):
        source = path.read_text(encoding="utf-8")
        version = path.stem.split("__", maxsplit=1)[0]
        digest = hashlib.sha256(source.encode()).hexdigest()
        records.append((version, path.name, digest))
    if not records:
        raise ValueError(f"No migrations found in {directory}")
    return records


def assert_migrations_agree(loaded: list[Migration] | None = None) -> list[Migration]:
    """Filenames, checksums and ``load_migrations()`` describe one sequence."""
    loaded = load_migrations() if loaded is None else loaded
    from_files = migration_records_from_filenames()
    from_loader = [(item.version, item.filename, item.sha256) for item in loaded]
    if from_files != from_loader:
        raise AssertionError("migrations/ filenames and migrations.py disagree")
    versions = [version for version, _, _ in from_files]
    if len(versions) != len(set(versions)):
        raise AssertionError("migration versions are not unique")
    return loaded


def planned_versions(database: str, loaded: list[Migration] | None = None) -> list[str]:
    """Versions ``migration_plan`` keeps, taken from filenames and the scope sets."""
    if database not in {DEV_DATABASE, PROD_DATABASE}:
        raise ValueError("planned versions require the DEV or PROD database name")
    loaded = assert_migrations_agree(loaded)
    versions: list[str] = []
    for item in loaded:
        if database != DEV_DATABASE and item.version in DEV_ONLY_MIGRATION_VERSIONS:
            continue
        if database != PROD_DATABASE and item.version in PROD_ONLY_MIGRATION_VERSIONS:
            continue
        versions.append(item.version)
    return versions


def latest_daily_activation_sql() -> str:
    """SQL of the highest ``prod_*daily_activation_view`` migration file."""
    paths = list(MIGRATIONS_DIR.glob("V*__prod_*daily_activation_view.sql"))
    if not paths:
        raise AssertionError("no prod daily activation view migration is checked in")

    def version_number(path: Path) -> int:
        return int(path.name.split("__", maxsplit=1)[0][1:])

    return max(paths, key=version_number).read_text(encoding="utf-8")


def load_workflow(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AssertionError(f"{path} did not parse as a workflow mapping")
    return document


def trigger_map(document: dict[str, Any]) -> dict[str, Any]:
    """PyYAML 1.1 parses an unquoted ``on`` key as ``True``."""
    raw = document.get(True, document.get("on"))
    if isinstance(raw, str):
        return {raw: {}}
    if isinstance(raw, list):
        return {str(name): {} for name in raw}
    if isinstance(raw, dict):
        return raw
    raise AssertionError(f"workflow triggers are {type(raw).__name__}")


def workflow_runs(document: dict[str, Any]) -> list[str]:
    runs: list[str] = []
    for job in document.get("jobs", {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append(step["run"])
    return runs


def permission_blocks(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    blocks: list[tuple[str, dict[str, Any]]] = []
    workflow_permissions = document.get("permissions")
    if workflow_permissions is not None:
        blocks.append(("workflow", workflow_permissions))
    for name, job in document.get("jobs", {}).items():
        if isinstance(job, dict) and job.get("permissions") is not None:
            blocks.append((f"job {name}", job["permissions"]))
    return blocks


def assert_permissions_minimal(permissions: object, *, where: str) -> None:
    if not isinstance(permissions, dict) or not permissions:
        raise AssertionError(f"{where} permissions must be an explicit non-empty mapping")
    for scope, level in permissions.items():
        if level not in {"read", "write"}:
            raise AssertionError(f"{where} permission {scope}={level!r} is not minimal")
        if level == "write" and scope not in WRITABLE_PERMISSION_SCOPES:
            raise AssertionError(f"{where} grants write on {scope}")
        if scope == "contents" and level != "read":
            raise AssertionError(f"{where} contents permission is {level}")


def compared_definition_paths(expression: str, operator: str) -> set[str]:
    return {
        path
        for found_operator, path in PATH_COMPARISON.findall(expression)
        if found_operator == operator
    }


def _job_text(job: dict[str, Any]) -> str:
    parts = list(workflow_runs({"jobs": {"job": job}}))
    env = job.get("env")
    if isinstance(env, dict):
        parts.extend(f"{key}={value}" for key, value in env.items())
    return "\n".join(parts)


def is_fail_closed_redirect(job: dict[str, Any]) -> bool:
    if job.get("environment") is not None:
        return False
    text = _job_text(job)
    return "exit 1" in text and "secrets." not in text and "SNOWFLAKE_" not in text


def assert_workflow_security(path: Path) -> None:
    """Properties that replace an exact workflow-name allowlist."""
    document = load_workflow(path)
    triggers = trigger_map(document)
    if FORBIDDEN_TRIGGER_NAMES & set(triggers):
        raise AssertionError(f"{path.name} uses a forbidden trigger")
    if not permission_blocks(document):
        raise AssertionError(f"{path.name} does not declare permissions")
    for where, permissions in permission_blocks(document):
        assert_permissions_minimal(permissions, where=f"{path.name} {where}")
    script = "\n".join(workflow_runs(document))
    for snippet in FORBIDDEN_LOG_SNIPPETS:
        if snippet in script:
            raise AssertionError(f"{path.name} logs a secret value")
    prod_named = "prod" in path.stem.split("-")
    for name, job in document.get("jobs", {}).items():
        if not isinstance(job, dict):
            continue
        environment = job.get("environment")
        exposed_to_pull_request = "pull_request" in triggers or "pull_request_target" in triggers
        if isinstance(environment, str) and "production" in environment and exposed_to_pull_request:
            raise AssertionError(f"{path.name} job {name} exposes production to pull requests")
        if prod_named and not is_fail_closed_redirect(job) and environment != "production":
            raise AssertionError(f"{path.name} job {name} environment is {environment!r}")
    dispatch = triggers.get("workflow_dispatch")
    if isinstance(dispatch, dict):
        inputs = dispatch.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise AssertionError(f"{path.name} workflow_dispatch inputs are not a mapping")
        for input_name, spec in inputs.items():
            if isinstance(spec, dict) and spec.get("required") is True and "type" not in spec:
                raise AssertionError(f"{path.name} input {input_name} has no type")


def assert_retired_source_workflow(path: Path) -> None:
    """A retired source workflow fails closed and names the generic replacement."""
    document = load_workflow(path)
    name = str(document.get("name", "")).lower()
    if "deprecated" not in name:
        raise AssertionError(f"{path.name} is not marked deprecated")
    runs = workflow_runs(document)
    if not any("run-ingestion.yml" in run and "exit 1" in run for run in runs):
        raise AssertionError(f"{path.name} does not fail closed onto run-ingestion.yml")
    for job in document.get("jobs", {}).values():
        if isinstance(job, dict) and not is_fail_closed_redirect(job):
            raise AssertionError(f"{path.name} still has a live job")
    assert_workflow_security(path)


def selection_rows() -> list[dict[str, Any]]:
    document = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    rows = document.get("sources")
    if not isinstance(rows, list):
        raise AssertionError("feed selection has no sources")
    return rows


def selection_source_ids() -> set[str]:
    return {str(row["source_id"]) for row in selection_rows()}


def registry_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(REGISTRY_DIR.glob("*-source-v*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or "source_id" not in document:
            raise AssertionError(f"{path.name} is not a source registry")
        documents.append(document)
    return documents


def registry_source_ids() -> set[str]:
    return {str(document["source_id"]) for document in registry_documents()}


def definition_paths_by_source_id() -> dict[str, str]:
    """Map source ids that have exactly one SourceDefinition file."""
    found: dict[str, str] = {}
    duplicated: set[str] = set()
    for path in sorted(SOURCE_DEFINITIONS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or "source_id" not in document:
            continue
        source_id = str(document["source_id"])
        relative = path.relative_to(REPO).as_posix()
        if source_id in duplicated:
            continue
        if source_id in found and found[source_id] != relative:
            duplicated.add(source_id)
            del found[source_id]
            continue
        found[source_id] = relative
    return found


def migration_version_enum(schema: dict[str, Any]) -> list[str]:
    return schema["properties"]["content"]["properties"]["migrations"]["items"]["properties"][
        "version"
    ]["enum"]


def public_column_shape(schema: dict[str, Any]) -> dict[str, list[str]]:
    """Reviewed object columns. This is the snapshotted public contract shape."""
    objects = schema["properties"]["scope"]["const"]["objects"]
    return {name: list(item["columns"]) for name, item in objects.items()}


def without_migration_version_enum(schema: dict[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(schema)
    migration_version_enum(copied)[:] = ["DERIVED_FROM_MIGRATION_FILENAMES"]
    return copied


def write_snapshot_schema(path: Path = SNAPSHOT_SCHEMA_PATH) -> None:
    """Rewrite the published schema from the runtime generator."""
    from lyme_gap_atlas_data.metadata_snapshots import snapshot_schema

    rendered = json.dumps(snapshot_schema(), indent=2) + "\n"
    path.write_text(rendered, encoding="utf-8")


def main() -> None:
    write_snapshot_schema()
    print(SNAPSHOT_SCHEMA_PATH)


if __name__ == "__main__":
    main()
