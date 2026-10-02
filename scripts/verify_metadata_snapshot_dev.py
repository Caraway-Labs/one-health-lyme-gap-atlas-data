"""Authorized bounded DEV evidence comparison; raw responses remain in memory."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from lyme_gap_atlas_data.metadata_snapshots import (
    collect_dev,
    load_scope,
    report,
    snapshot,
    snow_rows,
    validate_snapshot,
)
from lyme_gap_atlas_data.operation_capabilities import load_contract

root = Path(__file__).resolve().parents[1]
git = ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root)]
head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
if subprocess.check_output([*git, "status", "--porcelain"], text=True).strip():
    raise SystemExit("Commit reviewed implementation before live evidence capture")
responses = []


def query(sql):
    rows = snow_rows(sql)
    responses.append((sql, rows))
    return rows


scope = load_scope()
facts = collect_dev(scope, query=query)
captured = datetime.now(UTC)
observed = snapshot(facts, environment="dev", code_commit=head, generated_at=captured, scope=scope)
validate_snapshot(observed)
content = observed["content"]


def upper(row):
    return {str(k).upper(): v for k, v in row.items()}


source_objects = {
    (f"{r.get('TABLE_SCHEMA')}.{r.get('TABLE_NAME')}", r.get("TABLE_TYPE"))
    for row in facts["objects"]
    for r in [upper(row)]
    if f"{r.get('TABLE_SCHEMA')}.{r.get('TABLE_NAME')}" in scope["objects"]
    and r.get("TABLE_TYPE") in {"BASE TABLE", "VIEW"}
}
assert {(r["name"], r["kind"]) for r in content["objects"]} == source_objects
for column in content["columns"]:
    matching = [
        r
        for row in facts["columns"]
        for r in [upper(row)]
        if f"{r.get('TABLE_SCHEMA')}.{r.get('TABLE_NAME')}" == column["object"]
        and r.get("COLUMN_NAME") == column["name"]
    ]
    assert matching and any(
        r["DATA_TYPE"] == column["type"] and (r["IS_NULLABLE"] == "YES") == column["nullable"]
        for r in matching
    )
roles = {
    value.replace("{ENV}", "DEV"): alias for alias, value in load_contract()["role_aliases"].items()
}
database = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
for category in ("grants", "future_grants"):
    for grant in content[category]:
        matching = [
            r
            for row in facts[category]
            for r in [upper(row)]
            if roles.get(r.get("GRANTEE_NAME")) == grant["role"]
            and r.get("PRIVILEGE") == grant["privilege"]
            and r.get("GRANTED_ON", r.get("GRANT_ON")) == grant["kind"]
            and r.get("NAME")
            in {database if grant["object"] == "database" else f"{database}.{grant['object']}"}
        ]
        assert matching and any(
            (
                True
                if r.get("GRANT_OPTION") in (True, "true", "TRUE")
                else False
                if r.get("GRANT_OPTION") in (False, "false", "FALSE")
                else "unknown"
            )
            == grant["grant_option"]
            for r in matching
        )
for edge in content["role_edges"]:
    assert any(
        roles.get(r.get("GRANTEE_NAME")) == edge["parent"]
        and roles.get(r.get("NAME")) == edge["child"]
        and r.get("GRANTED_ON") == "ROLE"
        for row in facts["grants"]
        for r in [upper(row)]
    )
assert {r["version"] for r in content["migrations"]}.issubset(
    {upper(r).get("VERSION") for r in facts["migrations"]}
)
assert observed["visibility"] == "partial"
assert observed["environment"] == "dev"
assert observed["inspected_role"] == "read"
result = report(observed, now=captured)
safe = {
    "verification_version": 1,
    "code_commit": head,
    "generated_at": captured.isoformat(),
    "environment": "dev",
    "role": "OH_LYME_DEV_READ",
    "visibility": "partial",
    "semantic_hash": observed["semantic_hash"],
    "contract_hash": observed["contract_hash"],
    "scope_hash": observed["scope_hash"],
    "source_query_count": len(responses),
    "source_comparison": (
        "objects, emitted columns, grants, future grants, role edges and ledger versions matched"
    ),
    "normalized_counts": {k: len(v) for k, v in content.items() if isinstance(v, list)},
    "unavailable": observed["unavailable"],
    "prod_verification": "unverified",
}
out = root / ".atlas-metadata-private"
out.mkdir(exist_ok=True)
(out / "dev.snapshot.json").write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n")
(out / "dev.report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
(out / "dev.verification.json").write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n")
print(json.dumps(safe, sort_keys=True))
