"""Nonconnecting plan and explicitly approved, synthetic DEV fixture runner.

No credential discovery, connection creation, deployment hook or live CLI entry.
The caller must supply a fresh, already authorized named-connection session.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from snowflake.connector.errors import ProgrammingError

from . import semantic_release

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
ROLE = "OH_LYME_DEV_READ"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
CONNECTION = "ATLAS_DEV_READ"
TABLES = tuple(
    f"{DATABASE}.GOVERNANCE._DATA376_20261002_A_{suffix}"
    for suffix in ("COUNTIES", "OBSERVATIONS", "CONDITIONS")
)
CONTRACT_DIGEST = "d2ce120a0a08c9ff03b77a750613162cfd964d94305ab673db52dd09848f7b3b"
MAX_SECONDS = 600
MAX_STATEMENTS = 32
MAX_INSERTED_ROWS = 553
MAX_PAYLOAD_BYTES = 1_048_576
STATEMENT_SECONDS = 30
QUEUED_SECONDS = 15
CLEANUP_RESERVE_SECONDS = 270
RELEASE = "data376-synthetic-fixture"


class ProofRejected(ValueError):
    def __init__(self) -> None:
        super().__init__("proof contract rejected")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _contract() -> dict[str, Any]:
    with Path(__file__).with_name("failure_engine_proof_contract_v1.json").open("rb") as stream:
        content = stream.read(32_769)
    if len(content) > 32_768:
        raise ProofRejected()
    value = json.loads(content.decode("utf-8-sig"))
    if not isinstance(value, dict) or _digest(value) != CONTRACT_DIGEST:
        raise ProofRejected()
    return value


def synthetic_rows() -> tuple[list[semantic_release.CountyRow], list[tuple[Any, ...]]]:
    counties = [
        semantic_release.CountyRow(
            values=(
                RELEASE,
                f"{index:05d}",
                "Synthetic",
                "ZZ",
                "Synthetic",
                100,
                True,
                "Unknown",
                None,
                None,
                0,
                "Unknown",
                "Unknown",
                "Unknown",
                "Unknown",
                None,
                None,
                None,
                None,
                0,
                '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}',
                '{"fixture":true}',
            ),
            lineage={},
        )
        for index in range(1, 52)
    ]
    observations = [
        (
            f"synthetic-observation-{index}",
            "replaced-by-helper",
            "synthetic-measure",
            f"{1 + (index - 1) % 51:05d}",
            "synthetic",
            "synthetic-version",
            "synthetic-run",
            "synthetic-artifact",
            f"synthetic-row-{index}",
            "a" * 64,
            '{"fixture":true}',
            "Unknown",
            "2026-10-02T00:00:00Z",
            "synthetic",
            "synthetic",
            "synthetic",
            "PASSED",
            "synthetic fixture",
        )
        for index in range(1, 502)
    ]
    if len(counties) + len(observations) + 1 != MAX_INSERTED_ROWS:
        raise ProofRejected()
    if (
        len(json.dumps([row.values for row in counties] + observations).encode())
        > MAX_PAYLOAD_BYTES
    ):
        raise ProofRejected()
    return counties, observations


@dataclass(frozen=True)
class Operation:
    identifier: str
    sql: str
    parameters: tuple[Any, ...] | None = None
    rows: int = 0
    expected: tuple[Any, ...] | None = None
    negative_errno: int | None = None
    original_sql: str | None = None


def _operations() -> dict[str, Operation]:
    contract = _contract()
    counties, observations = synthetic_rows()
    result: dict[str, Operation] = {}

    def add(identifier: str, sql: str, **kwargs: Any) -> None:
        result[identifier] = Operation(identifier, sql, **kwargs)

    add(
        "IDENTITY",
        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), "
        "CURRENT_WAREHOUSE(), CURRENT_TRANSACTION()",
    )
    add(
        "TIMEOUTS",
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30, "
        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=15, QUERY_TAG='DATA376_TEMP_ENGINE_V1'",
    )
    add(
        "COLLISION_CHECK",
        f"SELECT COUNT(*) FROM {DATABASE}.INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s)",
        parameters=("GOVERNANCE", *(name.rsplit(".", 1)[1] for name in TABLES)),
        expected=(0,),
    )
    for index, name in enumerate(TABLES[:2]):
        add(f"CREATE_{index}", contract["temporary_ddl"][name.rsplit(".", 1)[1]])
    add("CREATE_2", f"CREATE TEMPORARY TABLE {TABLES[2]} (conditions VARIANT)")
    add("BEGIN", "BEGIN TRANSACTION")
    add("ROLLBACK", "ROLLBACK")
    for index, name in enumerate(TABLES):
        add(f"ZERO_{index}", f"SELECT COUNT(*) FROM {name}", expected=(0,))
        add(f"DROP_{index}", f"DROP TABLE {name}")
    for function, name, width, batch, rows, label in (
        ("_insert_counties", TABLES[0], 22, 50, [row.values for row in counties], "COUNTIES"),
        (
            "_insert_observations",
            TABLES[1],
            18,
            500,
            [(row[0], RELEASE, *row[2:]) for row in observations],
            "OBSERVATIONS",
        ),
    ):
        prefix = contract["current_prefixes"][function]
        old = (
            "PRESENTATION.SEMANTIC_COUNTY_ATLAS"
            if width == 22
            else "PRESENTATION.SEMANTIC_OBSERVATIONS"
        )
        placeholder = "(" + ",".join("%s" for _ in range(width)) + ")"
        for index, offset in enumerate(range(0, len(rows), batch)):
            chunk = rows[offset : offset + batch]
            original = prefix + " " + ",".join(placeholder for _ in chunk)
            add(
                f"WRITE_{label}_{index}",
                original.replace(old, name),
                parameters=tuple(value for row in chunk for value in row),
                rows=len(chunk),
                original_sql=original,
            )
        add(
            f"NEGATIVE_VALUES_{label}",
            contract["first_repair"][function].replace(old, name),
            parameters=tuple(rows[0]),
            rows=1,
            negative_errno=2014,
        )
    scripting = (
        "EXECUTE IMMEDIATE $$ DECLARE CONDITIONS VARIANT DEFAULT PARSE_JSON('[\"synthetic\"]'); "
        f"BEGIN INSERT INTO {TABLES[2]} (conditions) SELECT {{binding}}; RETURN 'ok'; END; $$"
    )
    add("NEGATIVE_UNBOUND", scripting.format(binding="CONDITIONS"), rows=1, negative_errno=904)
    add("WRITE_CONDITIONS", scripting.format(binding=":CONDITIONS"), rows=1)
    for label, predicate, expected in (
        ("PARTIAL", "county_fips < '03144'", (3144, 3143)),
        ("EMPTY", "FALSE", (3144, 0)),
        ("FULL", "TRUE", (3144, 3144)),
    ):
        ctes = (
            "WITH proof_synthetic AS (SELECT "
            "LPAD(ROW_NUMBER() OVER (ORDER BY SEQ4())::VARCHAR,5,'0') "
            "county_fips FROM TABLE(GENERATOR(ROWCOUNT=>3144))), "
            "proof_governed_records AS (SELECT OBJECT_CONSTRUCT('record',OBJECT_CONSTRUCT('STCNTY',"
            "county_fips)) payload,'cdc_atsdr_svi_2022_county' resource_key FROM proof_synthetic "
            "UNION ALL SELECT OBJECT_CONSTRUCT('record',OBJECT_CONSTRUCT('STCNTY','00001')),"
            "'cdc_atsdr_svi_2022_county'), proof_pathogen_records AS (SELECT county_fips,"
            f"'synthetic-run' ingestion_run_id FROM proof_synthetic WHERE {predicate} UNION ALL "
            "SELECT county_fips,'synthetic-run' FROM "
            "(VALUES ('EXTRA01'),('EXTRA02')) extras(county_fips) "
            "UNION ALL SELECT county_fips,'synthetic-run' FROM proof_synthetic "
            "WHERE county_fips='00001' "
            f"AND ({predicate})) "
        )
        add(
            f"CANONICAL_{label}",
            ctes + contract["canonical_kernel"],
            parameters=("synthetic-run",),
            expected=expected,
        )
    add(
        "VERIFY_COUNTIES",
        f"SELECT COUNT(*), MIN(fips), MAX(fips), "
        "COUNT_IF(TYPEOF(geometry_json)='OBJECT'),COUNT_IF(TYPEOF(lineage)='OBJECT'),"
        f"COUNT_IF(release_id=%s) FROM {TABLES[0]}",
        parameters=(RELEASE,),
        expected=(51, "00001", "00051", 51, 51, 51),
    )
    add(
        "VERIFY_OBSERVATIONS",
        "SELECT COUNT(*),COUNT_IF(TYPEOF(value)='OBJECT'),"
        f"COUNT_IF(release_id=%s) FROM {TABLES[1]}",
        parameters=(RELEASE,),
        expected=(501, 501, 501),
    )
    add(
        "VERIFY_CONDITIONS",
        f"SELECT COUNT(*),COUNT_IF(TYPEOF(conditions)='ARRAY' "
        f"AND ARRAY_SIZE(conditions)=1) FROM {TABLES[2]}",
        expected=(1, 1),
    )
    if len(result) > MAX_STATEMENTS:
        raise ProofRejected()
    return result


def make_plan(code_commit: str) -> dict[str, Any]:
    """Pure local metadata; never opens a connection or includes SQL/parameters."""
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ProofRejected()
    operations = _operations()
    return {
        "plan_version": 1,
        "state": "NOT_EXECUTED",
        "code_commit": code_commit,
        "code_commit_basis": "REVIEW_PIN_NOT_EXECUTION_OBSERVATION",
        "harness_sha256": hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "launcher_sha256": hashlib.sha256(
            Path(__file__)
            .with_name("failure_engine_launcher.py")
            .read_bytes()
            .replace(b"\r\n", b"\n")
        ).hexdigest(),
        "connector_version_required": "4.3.0",
        "contract_sha256": CONTRACT_DIGEST,
        "helpers_sha256": _digest(
            [
                inspect.getsource(semantic_release._insert_counties).replace("\r\n", "\n"),
                inspect.getsource(semantic_release._insert_observations).replace("\r\n", "\n"),
                inspect.getsource(semantic_release._execute_bound_value_batches).replace(
                    "\r\n", "\n"
                ),
            ]
        ),
        "connection": CONNECTION,
        "database": DATABASE,
        "role": ROLE,
        "warehouse": WAREHOUSE,
        "warehouse_basis": "CONFIGURATION_OBSERVED_2026_10_02_NOT_LIVE_VERIFIED",
        "temporary_tables": list(TABLES),
        "limits": {
            "wall_seconds": MAX_SECONDS,
            "statements": MAX_STATEMENTS,
            "inserted_rows": MAX_INSERTED_ROWS,
            "payload_bytes": MAX_PAYLOAD_BYTES,
            "statement_seconds": STATEMENT_SECONDS,
            "queued_seconds": QUEUED_SECONDS,
            "cleanup_reserve_seconds": CLEANUP_RESERVE_SECONDS,
        },
        "operations": [
            {
                "id": op.identifier,
                "sql_sha256": hashlib.sha256(op.sql.encode()).hexdigest(),
                "parameter_count": len(op.parameters or ()),
                "maximum_rows": op.rows,
                "maximum_calls": 1,
                "expected_negative_errno": op.negative_errno,
            }
            for op in operations.values()
        ],
        "repair": "UNKNOWN",
        "full_v092_v098_v099_proof": "UNKNOWN",
        "cost": {
            "warehouse_size": "UNKNOWN",
            "generation": "UNKNOWN",
            "clusters": "UNKNOWN",
            "credits_per_hour": "UNKNOWN",
            "usd_per_credit": "UNKNOWN",
            "ten_minute_compute_formula": "confirmed_credits_per_hour / 6",
            "conditional_gen1_xsmall_single_cluster_credits": 1 / 6,
            "conditional_basis": "NOT_AN_OBSERVATION_OR_PRICE_ESTIMATE",
        },
    }


def plan_hash(plan: dict[str, Any]) -> str:
    return _digest(plan)


class _Runner:
    def __init__(
        self, cursor: Any, clock: Callable[[], float], cancelled: Callable[[], bool] = lambda: False
    ) -> None:
        self.cursor = cursor
        self.cancelled = cancelled
        self.clock = clock
        self.deadline = clock() + MAX_SECONDS
        self.operations = _operations()
        self.used: set[str] = set()
        self.records: list[dict[str, Any]] = []
        self.inserted_rows = 0

    def execute(self, identifier: str, *, cleanup: bool = False) -> tuple[Any, ...] | None:
        if not cleanup and self.cancelled():
            raise ProofRejected()
        operation = self.operations.get(identifier)
        if operation is None:
            raise ProofRejected()
        limit = self.deadline - (60 if cleanup else CLEANUP_RESERVE_SECONDS)
        if identifier in self.used or len(self.used) >= MAX_STATEMENTS or self.clock() + 30 > limit:
            raise ProofRejected()
        if self.inserted_rows + operation.rows > MAX_INSERTED_ROWS:
            raise ProofRejected()
        self.used.add(identifier)
        record: dict[str, Any] = {"operation": identifier, "state": "FAIL", "query_id": "UNKNOWN"}
        self.records.append(record)
        try:
            previous_query_id = self.cursor.sfqid
            previous_query_id_known = True
        except Exception:
            previous_query_id = None
            previous_query_id_known = False
        try:
            self.cursor.execute(operation.sql, operation.parameters)
            self.inserted_rows += operation.rows
            if operation.negative_errno is not None:
                record["state"] = "NOT_REPRODUCED"
                raise ProofRejected()
            row = (
                self.cursor.fetchone()
                if operation.expected is not None or identifier == "IDENTITY"
                else None
            )
            if operation.expected is not None and (row is None or tuple(row) != operation.expected):
                raise ProofRejected()
            record["state"] = "PASS"
            return tuple(row) if row is not None else None
        except ProgrammingError as error:
            if operation.negative_errno is not None and error.errno == operation.negative_errno:
                record["state"] = "EXPECTED_NEGATIVE"
                return None
            raise
        finally:
            try:
                query_id = self.cursor.sfqid
                if (
                    previous_query_id_known
                    and query_id != previous_query_id
                    and isinstance(query_id, str)
                    and re.fullmatch(
                        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", query_id
                    )
                ):
                    record["query_id"] = query_id
            except Exception:
                pass


class _HelperBoundary:
    def __init__(self, runner: _Runner) -> None:
        self.runner = runner
        self.calls = 0

    def count_calls(self) -> int:
        return self.calls

    def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        self.calls += 1
        matches = [
            op
            for op in self.runner.operations.values()
            if op.original_sql == sql and op.parameters == parameters
        ]
        if len(matches) != 1:
            raise ProofRejected()
        self.runner.execute(matches[0].identifier)


def run_proof(
    connection: Any,
    plan: dict[str, Any],
    *,
    approved_plan_sha256: str | None = None,
    expected_user: str | None = None,
    clock: Callable[[], float] = monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Future authorized invocation only; never create/discover a connection.

    The explicit approval hash is a scope pin, not a substitute for owner approval.
    Caller owns a fresh ATLAS_DEV_READ session with network/socket timeout <=30.
    No SQL or private identity/error value is returned, even on failure.
    """
    receipt: dict[str, Any] = {
        "receipt_version": 1,
        "state": "NOT_AUTHORIZED",
        "mutations_started": False,
        "context": "UNKNOWN",
        "independent_execution_verification": "UNKNOWN",
        "actual_workload_sha": "UNKNOWN",
        "repair": "UNKNOWN",
        "full_v092_v098_v099_proof": "UNKNOWN",
        "operations": [],
        "connector_version": "UNKNOWN",
        "cleanup": {
            key: "UNKNOWN"
            for key in ("rollback", "zero_rows", "drops", "cursor_close", "session_close")
        },
    }
    if approved_plan_sha256 is None or expected_user is None or not expected_user:
        return receipt
    try:
        if plan != make_plan(plan["code_commit"]) or approved_plan_sha256 != plan_hash(plan):
            raise ProofRejected()
    except Exception:
        receipt["state"] = "PLAN_REJECTED"
        return receipt
    receipt["plan_sha256"] = approved_plan_sha256
    receipt["reviewed_code_commit"] = plan["code_commit"]
    try:
        for attribute in ("network_timeout", "socket_timeout"):
            timeout = getattr(connection, attribute, None)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not 0 < timeout <= 30
            ):
                raise ProofRejected()
    except Exception:
        receipt["state"] = "CLIENT_TIMEOUTS_UNKNOWN"
        return receipt
    import snowflake.connector

    version = snowflake.connector.__version__
    receipt["connector_version"] = version if version == "4.3.0" else "UNKNOWN"
    if version != "4.3.0":
        receipt["state"] = "CONNECTOR_VERSION_REJECTED"
        return receipt
    cursor = None
    runner = None
    created: list[int] = []
    uncertain_creation = False
    transaction = False
    try:
        cursor = connection.cursor()
        runner = _Runner(cursor, clock, cancelled)
        identity = runner.execute("IDENTITY")
        if identity != (expected_user, ROLE, DATABASE, WAREHOUSE, None):
            receipt["context"] = "REJECTED"
            raise ProofRejected()
        receipt["context"] = "PASS"
        runner.execute("TIMEOUTS")
        runner.execute("COLLISION_CHECK")
        for index in range(3):
            receipt["mutations_started"] = True
            uncertain_creation = True
            runner.execute(f"CREATE_{index}")
            created.append(index)
            uncertain_creation = False
        transaction = True
        runner.execute("BEGIN")
        for identifier in (
            "NEGATIVE_VALUES_COUNTIES",
            "NEGATIVE_VALUES_OBSERVATIONS",
            "NEGATIVE_UNBOUND",
            "CANONICAL_PARTIAL",
            "CANONICAL_EMPTY",
            "CANONICAL_FULL",
        ):
            runner.execute(identifier)
        boundary = _HelperBoundary(runner)
        try:
            semantic_release._execute_bound_value_batches(
                boundary, "unapproved", [("bad-width",)], row_width=2, batch_size=50
            )
        except ValueError:
            if boundary.count_calls():
                raise ProofRejected() from None
        else:
            raise ProofRejected()
        counties, observations = synthetic_rows()
        semantic_release._insert_counties(boundary, RELEASE, counties)
        semantic_release._insert_observations(boundary, RELEASE, observations)
        if boundary.count_calls() != 4:
            raise ProofRejected()
        runner.execute("WRITE_CONDITIONS")
        for identifier in ("VERIFY_COUNTIES", "VERIFY_OBSERVATIONS", "VERIFY_CONDITIONS"):
            runner.execute(identifier)
        receipt["state"] = "PASS"
    except Exception:
        receipt["state"] = "FAIL"
    finally:
        if runner is not None:
            receipt["operations"] = runner.records
            receipt["mutations_started"] = any(
                item["operation"].startswith("CREATE_") for item in runner.records
            )
            if transaction:
                try:
                    runner.execute("ROLLBACK", cleanup=True)
                    transaction = False
                    receipt["cleanup"]["rollback"] = "PASS"
                except Exception:
                    receipt["cleanup"]["rollback"] = "FAIL"
            else:
                receipt["cleanup"]["rollback"] = "NOT_NEEDED"
            if not transaction and created:
                try:
                    for index in created:
                        runner.execute(f"ZERO_{index}", cleanup=True)
                    receipt["cleanup"]["zero_rows"] = "PASS"
                except Exception:
                    pass
                dropped = 0
                for index in created:
                    try:
                        runner.execute(f"DROP_{index}", cleanup=True)
                        dropped += 1
                    except Exception:
                        pass
                if dropped == len(created) and not uncertain_creation:
                    receipt["cleanup"]["drops"] = "PASS"
        if cursor is not None:
            with suppress(Exception):
                cursor.close()
                receipt["cleanup"]["cursor_close"] = "PASS"
        try:
            connection.close()
            receipt["cleanup"]["session_close"] = "PASS"
        except Exception:
            pass
        if receipt["state"] == "PASS" and any(
            value != "PASS" for value in receipt["cleanup"].values()
        ):
            receipt["state"] = "FAIL"
    return receipt
