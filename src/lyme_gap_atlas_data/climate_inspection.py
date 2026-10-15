"""Two fixed, checksum-pinned read-only query bundles, never deployment."""

import hashlib
import time
from pathlib import Path
from typing import Any

import sqlglot

from .climate_membership_diagnostic import DiagnosticStop, validate_warehouse_cost

ROOT = Path(__file__).resolve().parents[2]
BUNDLES = {
    "dev": (
        "january_climate_dev_scientific_inspection.sql",
        "672873435c728b1b524c4792fedd42eeb2a4593858a1546c7104560508d118df",
        5,
    ),
    "production": (
        "january_climate_prod_readiness_inspection.sql",
        "7fc5085d376414f93378297cccc41146902d90ebcdc2d96ee2a3f765a7727c21",
        10,
    ),
}


class Stop(Exception):
    pass


def require(condition: bool, category: str) -> None:
    if not condition:
        raise Stop(category)


def statements(environment: str) -> list[str]:
    require(environment in BUNDLES, "ENVIRONMENT")
    name, digest, count = BUNDLES[environment]
    source = (ROOT / "sql" / name).read_text()
    require(hashlib.sha256(source.encode()).hexdigest() == digest, "SQL_SCOPE_CHANGED")
    trees = sqlglot.parse(source, read="snowflake")
    require(len(trees) == count, "STATEMENT_COUNT")
    result = []
    for tree in trees:
        require(tree is not None, "EMPTY_STATEMENT")
        assert tree is not None
        sql = tree.sql(dialect="snowflake")
        require(
            tree.key in {"select", "show"}
            or (tree.key == "command" and sql.upper().startswith("SHOW GRANTS ")),
            "READ_ONLY_SCOPE",
        )
        result.append(sql)
    return result


def inspect(
    cursor: Any, environment: str, expected: tuple[str, ...], report: dict[str, Any], started: float
) -> dict[str, Any]:
    report["checks"] = []
    report["forecast_usd"] = 20.0625 if environment == "production" else 2.90625
    report["combined_maximum_usd"] = 25
    report["actual_billed_cost_usd"] = None
    report["pricing_basis"] = "OWNER_APPROVED_PLANNING_ONLY_NOT_CONTRACTUAL_RATE"
    identity: tuple[Any, ...] = ()
    for index, sql in enumerate(statements(environment)):
        check: dict[str, Any] = {"ordinal": index + 1, "status": "BLOCKED"}
        report["checks"].append(check)
        try:
            require(time.monotonic() - started < 180, "PROCESS_DEADLINE")
            report["statements_executed"] += 1
            cursor.execute(sql)
            check["query_id"] = getattr(cursor, "sfqid", None)
            columns = [str(column[0]).lower() for column in cursor.description]
            require(len(columns) == len(set(columns)), "DUPLICATE_COLUMNS")
            values = cursor.fetchall()
            require(len(values) <= 200, "RESULT_LIMIT")
            rows = [dict(zip(columns, row, strict=True)) for row in values]
            check["row_count"] = len(rows)
            if index == 0:
                require(len(values) == 1 and len(values[0]) == 6, "IDENTITY_SHAPE")
                identity = tuple(values[0])
                require(identity[:4] == expected, "IDENTITY_MISMATCH")
                report["account_locator_sha256"] = hashlib.sha256(
                    str(identity[5]).upper().encode()
                ).hexdigest()
                report["region"] = identity[4]
            elif index == 1:
                require(len(rows) == 1, "WAREHOUSE_VISIBILITY")
                require(rows[0].get("name") == expected[3], "WAREHOUSE_NAME")
                evidence: dict[str, Any] = {}
                if (
                    report["account_locator_sha256"]
                    == "9d740b2d2d7445285e80aea51237b1159401d6f6e29e49b996932c74f55df328"
                    and identity[4] == "AWS_US_WEST_2"
                ):
                    evidence["standard_capability_evidence"] = {
                        "edition": "STANDARD",
                        "cloud": "AWS",
                    }
                validate_warehouse_cost(rows[0], evidence, str(identity[4]), report)
                if not evidence:
                    require(
                        type(rows[0].get("min_cluster_count")) is int
                        and rows[0]["min_cluster_count"] == 1,
                        "MIN_CLUSTER_UNVERIFIED",
                    )
                check["observations"] = report["warehouse_cost_observation"]
            else:
                check["rows"] = rows
            check["status"] = "PASS"
        except (Exception, KeyboardInterrupt) as error:
            check["category"] = (
                str(error)
                if isinstance(error, (Stop, DiagnosticStop))
                else "READ_OR_ACCESS_UNAVAILABLE"
            )
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            return report
    report.update(status="PASS", writes=False, elapsed_seconds=round(time.monotonic() - started, 3))
    return report
