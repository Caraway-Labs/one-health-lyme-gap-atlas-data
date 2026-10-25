"""Compile and execute the actual forward view query with inline DEV-only fixtures.

Uses the named least-privilege Snowflake CLI connection. No DDL, persistent
fixtures, provider requests, credentials, grants or production access.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from lyme_gap_atlas_data.intelligence_items import identity_hash

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = "V169__intelligence_source_activations.sql"
DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def fixture_query(source_id: str, change: str) -> str:
    template = "cdc-eid-ahead-of-print" if change == "new_source" else source_id
    if change == "new_source":
        source_id = "example-new-feed"
    old = json.loads((ROOT / f"config/intelligence/{template}-source-v1.json").read_text())
    new = json.loads((ROOT / f"config/intelligence/{template}-source-v2.json").read_text())
    old, new = copy.deepcopy(old), copy.deepcopy(new)
    old["source_id"] = source_id
    new["source_id"] = source_id
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
    docs = [(1, old_hash, old), (version, new_hash, new)]
    registry = " UNION ALL ".join(
        f"SELECT {literal(source_id)} source_id,{v} registry_version,"
        f"{literal(sha)} registry_sha256,PARSE_JSON({literal(json.dumps(doc))}) registry_document"
        for v, sha, doc in docs
    )
    activation_sha = "0" * 64 if change == "wrong_hash" else new_hash
    activation_state = "BLOCKED" if change == "future" else "ACTIVE"
    activations = (
        f"SELECT {literal(source_id)} source_id,1 registry_version,"
        f"{literal(old_hash)} registry_sha256,'BLOCKED' state,'reviewed' decision_id,"
        "'2026-10-21T00:00:00Z'::TIMESTAMP_LTZ activated_at"
        " UNION ALL "
        f"SELECT {literal(source_id)},{version},{literal(activation_sha)},"
        f"{literal(activation_state)},'reviewed','2026-10-21T00:00:00Z'::TIMESTAMP_LTZ"
    )
    item = {
        "contract_version": "2.0.0",
        "title": "DEV inline fixture",
        "provenance": {"run_id": "dev-fixture-run", "artifact_sha256": "a" * 64},
    }
    capture_version = 1 if change == "blocked_v1" else version
    captures = (
        "SELECT 'item' item_id,'revision' revision_id,"
        f"{literal(source_id)} source_id,{capture_version} registry_version,'rss' transport,"
        f"PARSE_JSON({literal(json.dumps(item))}) item_document,"
        "'2026-10-21T00:00:00Z'::TIMESTAMP_NTZ retrieved_at,'old' capture_id"
    )
    if change == "dedup":
        captures += (
            " UNION ALL SELECT 'item','revision',"
            f"{literal(source_id)},1,'rss',PARSE_JSON({literal(json.dumps(item))}),"
            "'2026-10-21T01:00:00Z'::TIMESTAMP_NTZ,'blocked-v1'"
        )
    if change == "blocked_v1":
        captures = (
            "SELECT 'item' item_id,'revision' revision_id,"
            f"{literal(source_id)} source_id,1 registry_version,'rss' transport,"
            f"PARSE_JSON({literal(json.dumps(item))}) item_document,"
            "'2026-10-21T00:00:00Z'::TIMESTAMP_NTZ retrieved_at,'old' capture_id"
        )
    query = (ROOT / "migrations" / MIGRATION).read_text().split("COPY GRANTS AS", 1)[1]
    query = query.strip().removesuffix(";")
    query = query.replace("GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS", "fixture_sources")
    query = query.replace("GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES", "fixture_captures")
    query = query.replace("CONFORMED.INTELLIGENCE_ITEM_REVISIONS", "fixture_revisions")
    query = query.replace("GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS", "fixture_activations")
    return (
        f"WITH fixture_sources AS ({registry}),fixture_captures AS ({captures}),"
        "fixture_revisions AS (SELECT 'item' item_id,'revision' revision_id),"
        f"fixture_activations AS ({activations}) {query}"
    )


def acceptance_sql() -> tuple[str, dict[str, tuple[int, int | None]]]:
    expected = {}
    selects = []
    for source in ("cdc-eid-expedited", "cdc-eid-ahead-of-print", "cdc-outbreaks"):
        for change in (
            "active",
            "dedup",
            "blocked_v1",
            "paused",
            "revoked",
            "untrusted",
            "null_state",
            "future",
            "wrong_hash",
        ):
            name = source + ":" + change
            expected[name] = (1, 2) if change in {"active", "dedup"} else (0, None)
            selects.append(
                f"SELECT {literal(name)} AS SCENARIO,COUNT(*) AS ENTRY_COUNT,"
                f"MAX(REGISTRY_VERSION) AS VERSION FROM ({fixture_query(source, change)})"
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
