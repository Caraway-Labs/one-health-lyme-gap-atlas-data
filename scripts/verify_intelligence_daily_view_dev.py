"""Compile and execute the actual forward view query with inline DEV-only fixtures.

Uses the named least-privilege Snowflake CLI connection. No DDL, persistent
fixtures, provider requests, credentials, grants or production access.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from lyme_gap_atlas_data.intelligence_items import identity_hash

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = "V170__intelligence_source_activations.sql"
DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
LIVE_SOURCES = (
    "cdc-eid-expedited",
    "cdc-eid-ahead-of-print",
    "cdc-outbreaks",
    "nih-news-releases",
    "cdc-mmwr",
)


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def fixture_query(source_id: str, change: str) -> str:
    template = source_id if source_id in LIVE_SOURCES else "cdc-eid-ahead-of-print"
    if change == "new_source":
        source_id = "example-new-feed"
    elif change == "blocked_v1":
        source_id = "example-blocked-feed"
    old = json.loads((ROOT / f"config/intelligence/{template}-source-v1.json").read_text())
    new = json.loads((ROOT / f"config/intelligence/{template}-source-v2.json").read_text())

    def retarget(document: dict) -> dict:
        return json.loads(json.dumps(document).replace(template, source_id))

    old, new = retarget(old), retarget(new)
    if change in {"paused", "revoked", "untrusted", "null_state"}:
        if change == "paused":
            new["state"] = "paused"
        elif change == "revoked":
            new["approval"]["status"] = "revoked"
        elif change == "untrusted":
            new["trust_review"]["status"] = "revoked"
        else:
            new["state"] = None
    version = 3 if change == "future" else 2
    new["registry_version"] = version
    old_hash, new_hash = identity_hash(old), identity_hash(new)
    if change == "wrong_hash":
        new_hash = "0" * 64
    docs = [(1, old_hash, old), (version, new_hash, new)]
    registry = " UNION ALL ".join(
        f"SELECT {literal(source_id)} source_id,{v} registry_version,"
        f"{literal(sha)} registry_sha256,PARSE_JSON({literal(json.dumps(doc))}) registry_document"
        for v, sha, doc in docs
    )

    def activation_select(registry_version: int, sha: str, state: str) -> str:
        return (
            f"SELECT {literal(source_id)} source_id,{registry_version} registry_version,"
            f"{literal(sha)} registry_sha256,{literal(state)} state,'reviewed' decision_id,"
            "'2026-10-21T00:00:00Z'::TIMESTAMP_LTZ activated_at"
        )

    activation_parts = [activation_select(version, new_hash, "ACTIVE")]
    if change in {"active", "dedup"}:
        activation_parts.append(activation_select(1, old_hash, "ACTIVE"))
    elif change == "blocked_v1":
        activation_parts.append(activation_select(1, old_hash, "BLOCKED"))
    activations = " UNION ALL ".join(activation_parts)
    item = {
        "contract_version": "2.0.0",
        "title": "DEV inline fixture",
        "provenance": {"run_id": "dev-fixture-run", "artifact_sha256": "a" * 64},
    }
    later = dict(item)
    later["title"] = "DEV inline fixture v2"
    capture_version = version if change in {"new_source"} else 1
    captures = (
        "SELECT 'item' item_id,'revision' revision_id,"
        f"{literal(source_id)} source_id,{capture_version} registry_version,'rss' transport,"
        f"PARSE_JSON({literal(json.dumps(item))}) item_document,"
        "'2026-10-21T00:00:00Z'::TIMESTAMP_NTZ retrieved_at,'old' capture_id"
    )
    if change == "dedup":
        captures += (
            " UNION ALL SELECT 'item','revision',"
            f"{literal(source_id)},2,'rss',PARSE_JSON({literal(json.dumps(item))}),"
            "'2026-10-21T01:00:00Z'::TIMESTAMP_NTZ,'new'"
        )
    if change == "blocked_v1":
        captures += (
            " UNION ALL SELECT 'v2-item','revision',"
            f"{literal(source_id)},2,'rss',PARSE_JSON({literal(json.dumps(later))}),"
            "'2026-10-21T01:00:00Z'::TIMESTAMP_NTZ,'v2'"
        )
    query = (ROOT / "migrations" / MIGRATION).read_text().split("COPY GRANTS AS", 1)[1]
    query = query.strip().removesuffix(";")
    query = query.replace("GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS", "fixture_sources")
    query = query.replace("GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES", "fixture_captures")
    query = query.replace("CONFORMED.INTELLIGENCE_ITEM_REVISIONS", "fixture_revisions")
    query = query.replace("GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS", "fixture_activations")
    return (
        f"WITH fixture_sources AS ({registry}),fixture_captures AS ({captures}),"
        "fixture_revisions AS (SELECT 'item' item_id,'revision' revision_id "
        "UNION ALL SELECT 'v2-item','revision'),"
        f"fixture_activations AS ({activations}) {query}"
    )


def acceptance_sql() -> tuple[str, dict[str, tuple[int, int | None]]]:
    expected = {}
    selects = []
    for source in LIVE_SOURCES:
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
                f"SELECT {literal(name)} AS SCENARIO,COUNT(*) AS ENTRY_COUNT,"
                f"MAX(REGISTRY_VERSION) AS VERSION FROM ({fixture_query(source, change)})"
            )
    expected["example-blocked-feed:blocked_v1"] = (1, 2)
    selects.append(
        "SELECT 'example-blocked-feed:blocked_v1' AS SCENARIO,COUNT(*) AS ENTRY_COUNT,"
        "MAX(REGISTRY_VERSION) AS VERSION FROM ("
        + fixture_query("cdc-eid-ahead-of-print", "blocked_v1")
        + ")"
    )
    expected["example-new-feed:new_source"] = (1, 2)
    selects.append(
        "SELECT 'example-new-feed:new_source' AS SCENARIO,COUNT(*) AS ENTRY_COUNT,"
        "MAX(REGISTRY_VERSION) AS VERSION FROM ("
        + fixture_query("cdc-eid-ahead-of-print", "new_source")
        + ")"
    )
    return " UNION ALL ".join(selects), expected


def sql(query: str, *, view_object: bool = False) -> list[dict]:
    result = subprocess.run(
        [
            "snow",
            "sql",
            "-c",
            "ATLAS_DEV_OWNER" if view_object else "ATLAS_DEV_READ",
            "--database",
            DATABASE,
            "--warehouse",
            "OH_LYME_DEV_INGEST_XS_WH",
            "--format",
            "JSON",
            "--stdin",
        ],
        input="USE WAREHOUSE OH_LYME_DEV_INGEST_XS_WH;\n" + query,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
        detail = re.findall(
            r"(?:SQL compilation error|syntax error|No active warehouse|"
            r"Unsupported subquery|unexpected|Insufficient privileges)[^\r\n]*",
            cleaned,
            re.IGNORECASE,
        )
        code = re.search(r"\b(\d{6})\s*\(([A-Z0-9]+)\)", cleaned)
        raise RuntimeError(
            "DEV_VIEW_QUERY_FAILED"
            + (":" + ":".join(code.groups()) if code else "")
            + ":"
            + " | ".join(detail)
        )
    decoder = json.JSONDecoder()
    remaining = result.stdout.strip()
    outputs = []
    while remaining:
        value, end = decoder.raw_decode(remaining)
        outputs.append(value)
        remaining = remaining[end:].lstrip()

    def rows(value):
        if isinstance(value, list):
            return [row for child in value for row in rows(child)]
        if not isinstance(value, dict):
            raise ValueError("UNEXPECTED_SNOW_CLI_JSON_SHAPE")
        return [value]

    return rows(outputs[-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--view-object", action="store_true")
    args = parser.parse_args()
    identity = sql(
        "SELECT CURRENT_USER() U,CURRENT_ROLE() R,CURRENT_DATABASE() D,CURRENT_WAREHOUSE() W",
        view_object=args.view_object,
    )
    print(json.dumps({"dev_context_results": identity}), file=sys.stderr, flush=True)
    identity = [row for row in identity if {"U", "R", "D", "W"} <= row.keys()]
    assert identity == [
        {
            "U": "MATTHEWCARAWAY",
            "R": "OH_LYME_DEV_OWNER" if args.view_object else "OH_LYME_DEV_READ",
            "D": DATABASE,
            "W": "OH_LYME_DEV_INGEST_XS_WH",
        }
    ]
    query, expected = acceptance_sql()
    if args.view_object:
        prefix = "V165_ACCEPT_" + uuid4().hex.upper()
        statements = []
        checks = []
        for index, name in enumerate(expected):
            source, change = name.split(":")
            view = DATABASE + ".GOVERNANCE." + prefix + "_" + str(index)
            statements.append(
                "CREATE TEMPORARY VIEW " + view + " AS " + fixture_query(source, change)
            )
            checks.append(
                f"SELECT {literal(name)} SCENARIO,COUNT(*) ENTRY_COUNT,"
                "MAX(REGISTRY_VERSION) VERSION,"
                "COUNT_IF(PROVENANCE:run_id::VARCHAR='dev-fixture-run') PROVENANCE_COUNT FROM "
                + view
            )
        query = ";\n".join(statements + [" UNION ALL ".join(checks)])
    rows = [row for row in sql(query, view_object=args.view_object) if "SCENARIO" in row]
    actual = {r["SCENARIO"]: (r["ENTRY_COUNT"], r["VERSION"]) for r in rows}
    assert actual == expected, "DEV_VIEW_ACCEPTANCE_MISMATCH"
    if args.view_object:
        assert all(r["ENTRY_COUNT"] == 0 or r["PROVENANCE_COUNT"] == r["ENTRY_COUNT"] for r in rows)
    print(
        json.dumps(
            {
                "identity": identity,
                "scenarios_passed": len(rows),
                "rows": rows,
                "persistent_writes": False,
                "provider_requests": 0,
                "real_temporary_view_objects": len(rows) if args.view_object else 0,
                "temporary_objects_expire_with_session": args.view_object,
            }
        )
    )


if __name__ == "__main__":
    main()
