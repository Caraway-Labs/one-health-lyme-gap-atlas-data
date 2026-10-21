"""Compile and execute the actual forward view query with inline DEV-only fixtures.

Uses the named least-privilege Snowflake CLI connection. No DDL, persistent
fixtures, provider requests, credentials, grants or production access.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = "V165__prod_intelligence_daily_view_join_compatibility.sql"
DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def fixture_query(source_id: str, change: str) -> str:
    old = json.loads((ROOT / f"config/intelligence/{source_id}-source-v1.json").read_text())
    new = json.loads((ROOT / f"config/intelligence/{source_id}-source-v2.json").read_text())
    from lyme_gap_atlas_data.intelligence_items import identity_hash

    old_hash, new_hash = identity_hash(old), identity_hash(new)
    if change in {"paused", "revoked", "untrusted", "null_state"}:
        new = copy.deepcopy(new)
        if change == "paused":
            new["state"] = "paused"
        elif change == "revoked":
            new["approval"]["status"] = "revoked"
        elif change == "untrusted":
            new["trust_review"]["status"] = "revoked"
        else:
            new["state"] = None
    version = 3 if change == "future" else 2
    if change == "wrong_hash":
        new_hash = "0" * 64
    docs = [(1, old_hash, old), (version, new_hash, new)]
    registry = " UNION ALL ".join(
        f"SELECT {literal(source_id)} source_id,{v} registry_version,"
        f"{literal(sha)} registry_sha256,PARSE_JSON({literal(json.dumps(doc))}) registry_document"
        for v, sha, doc in docs
    )
    item = {"contract_version": "2.0.0", "title": "DEV inline fixture", "provenance": {}}
    captures = (
        "SELECT 'item' item_id,'revision' revision_id,"
        f"{literal(source_id)} source_id,1 registry_version,'rss' transport,"
        f"PARSE_JSON({literal(json.dumps(item))}) item_document,"
        "'2026-10-21T00:00:00Z'::TIMESTAMP_NTZ retrieved_at,'old' capture_id"
    )
    if change == "dedup":
        captures += (
            " UNION ALL SELECT 'item','revision',"
            f"{literal(source_id)},2,'rss',PARSE_JSON({literal(json.dumps(item))}),"
            "'2026-10-21T01:00:00Z'::TIMESTAMP_NTZ,'new'"
        )
    query = (ROOT / "migrations" / MIGRATION).read_text().split("COPY GRANTS AS", 1)[1]
    query = query.strip().removesuffix(";")
    query = query.replace("GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS", "fixture_sources")
    query = query.replace("GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES", "fixture_captures")
    query = query.replace("CONFORMED.INTELLIGENCE_ITEM_REVISIONS", "fixture_revisions")
    return query.replace(
        "WITH blocked_source_versions AS (",
        f"WITH fixture_sources AS ({registry}),fixture_captures AS ({captures}),"
        "fixture_revisions AS (SELECT 'item' item_id,'revision' revision_id),"
        "blocked_source_versions AS (",
        1,
    )


def acceptance_sql() -> tuple[str, dict[str, tuple[int, int | None]]]:
    expected = {}
    selects = []
    for source in ("cdc-eid-expedited", "cdc-eid-ahead-of-print", "cdc-outbreaks"):
        for change in (
            "active",
            "dedup",
            "paused",
            "revoked",
            "untrusted",
            "null_state",
            "future",
            "wrong_hash",
        ):
            name = source + ":" + change
            expected[name] = (
                (1, 2 if change == "dedup" else 1) if change in {"active", "dedup"} else (0, None)
            )
            selects.append(
                f"SELECT {literal(name)} AS SCENARIO,COUNT(*) AS ROWS,"
                f"MAX(REGISTRY_VERSION) AS VERSION FROM ({fixture_query(source, change)})"
            )
    return " UNION ALL ".join(selects), expected


def sql(query: str) -> list[dict]:
    result = subprocess.run(
        [
            "snow",
            "sql",
            "-c",
            "ATLAS_DEV_READ",
            "--database",
            DATABASE,
            "--warehouse",
            "COMPUTE_WH",
            "--format",
            "JSON",
            "--stdin",
        ],
        input=query,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError("DEV_INLINE_VIEW_QUERY_FAILED")
    return json.loads(result.stdout)


def main() -> None:
    identity = sql(
        "SELECT CURRENT_USER() U,CURRENT_ROLE() R,CURRENT_DATABASE() D,CURRENT_WAREHOUSE() W"
    )
    assert identity == [
        {"U": "MATTHEWCARAWAY", "R": "OH_LYME_DEV_READ", "D": DATABASE, "W": "COMPUTE_WH"}
    ]
    query, expected = acceptance_sql()
    rows = sql(query)
    actual = {r["SCENARIO"]: (r["ROWS"], r["VERSION"]) for r in rows}
    assert actual == expected, "DEV_INLINE_VIEW_ACCEPTANCE_MISMATCH"
    print(
        json.dumps(
            {
                "identity": identity,
                "scenarios_passed": len(rows),
                "rows": rows,
                "persistent_writes": False,
                "provider_requests": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
