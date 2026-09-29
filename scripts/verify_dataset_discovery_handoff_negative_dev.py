"""Non-destructive DEV denial probes for the Dataset Discovery handoff boundary."""

import json
import os
from pathlib import Path

import snowflake.connector


def connect(*, reviewer: bool):
    prefix = "DATASET_DISCOVERY_REVIEWER" if reviewer else "DATASET_DISCOVERY_RUNTIME"
    token = Path(os.environ[f"{prefix}_PAT_FILE"]).read_text(encoding="utf-8").strip()
    return snowflake.connector.connect(
        account="TXB06009",
        user="MATTHEWCARAWAY" if reviewer else "OH_LYME_DEV_DATASET_DISCOVERY_SVC",
        authenticator="PROGRAMMATIC_ACCESS_TOKEN",
        token=token,
        role=(
            "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"
            if reviewer
            else "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME"
        ),
        database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        warehouse="OH_LYME_DEV_INGEST_XS_WH",
        session_parameters={"QUERY_TAG": "data450-negative-handoff-dev"},
    )


def denied(connection, label: str, sql: str, expected: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        try:
            cursor.execute(sql)
        except snowflake.connector.Error as error:
            message = str(error)
            if expected not in message:
                raise AssertionError(f"{label}: unexpected denial: {message}") from error
            return {"case": label, "query_id": cursor.sfqid, "denial": expected}
    raise AssertionError(f"{label}: unexpectedly succeeded")


def main() -> None:
    pending = "a89ecf1201b98819f16ce45bf6083ccdd9f2c628b8857500e6e15ca3e9e73a11"
    rejected = "8d9e1d588ee07a75805a0ccfcf514ea4d56505df1d592d574593b7d05338e09d"
    accepted = "1f04868f1a06df60b99179faced37aed16ccc66d71eda035c70c9d2c52da2c45"
    rejected_event = "6c9affe8b37ca6e5917562ea0df50db4c6a0a843ce292ce63581864b6bf59c36"
    missing = "0" * 64
    results = []

    with connect(reviewer=True) as reviewer:
        with reviewer.cursor() as cursor:
            cursor.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
            )
            if cursor.fetchone() != (
                "MATTHEWCARAWAY",
                "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "OH_LYME_DEV_INGEST_XS_WH",
            ):
                raise AssertionError("Unexpected reviewer identity")
        for label, version, event, expected in (
            ("never accepted", pending, missing, "REJECTED_OR_STALE_HANDOFF"),
            ("rejected", rejected, rejected_event, "REJECTED_OR_STALE_HANDOFF"),
            ("stale event", accepted, missing, "CONFLICTING_HANDOFF_REPLAY"),
            ("missing event", accepted, "", "INVALID_REVIEW_EVENT_ID"),
            ("unknown version", missing, missing, "REJECTED_OR_STALE_HANDOFF"),
        ):
            results.append(
                denied(
                    reviewer,
                    label,
                    "CALL GOVERNANCE.SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION("
                    f"'{version}', '{event}')",
                    expected,
                )
            )
        results.append(
            denied(
                reviewer,
                "direct review-table read",
                "SELECT COUNT(*) FROM DATASET_DISCOVERY.REVIEW_EVENTS",
                "does not exist or not authorized",
            )
        )
        results.append(
            denied(
                reviewer,
                "source approval",
                "CALL GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION("
                "'data450-negative','APPROVED','negative probe',PARSE_JSON('[]'),"
                "'MATTHEWCARAWAY','data450','data450-negative')",
                "Unknown user-defined function",
            )
        )
        results.append(
            denied(
                reviewer,
                "ingestion-run DML",
                "DELETE FROM GOVERNANCE.INGESTION_RUNS WHERE 1=0",
                "does not exist or not authorized",
            )
        )
        results.append(
            denied(
                reviewer,
                "publication DML",
                "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status = status WHERE 1=0",
                "does not exist or not authorized",
            )
        )

    with connect(reviewer=False) as runtime:
        with runtime.cursor() as cursor:
            cursor.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
            )
            if cursor.fetchone() != (
                "OH_LYME_DEV_DATASET_DISCOVERY_SVC",
                "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "OH_LYME_DEV_INGEST_XS_WH",
            ):
                raise AssertionError("Unexpected runtime identity")
        results.append(
            denied(
                runtime,
                "governance base-table read",
                "SELECT COUNT(*) FROM GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS",
                "does not exist or not authorized",
            )
        )
        results.append(
            denied(
                runtime,
                "governance handoff DML",
                "UPDATE GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS "
                "SET investigation_status = investigation_status WHERE 1=0",
                "does not exist or not authorized",
            )
        )
        results.append(
            denied(
                runtime,
                "source-version DML",
                "UPDATE GOVERNANCE.DATA_SOURCE_VERSIONS SET resource_key = resource_key WHERE 1=0",
                "does not exist or not authorized",
            )
        )
        results.append(
            denied(
                runtime,
                "ingestion-run DML",
                "DELETE FROM GOVERNANCE.INGESTION_RUNS WHERE 1=0",
                "does not exist or not authorized",
            )
        )
        results.append(
            denied(
                runtime,
                "publication DML",
                "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status = status WHERE 1=0",
                "does not exist or not authorized",
            )
        )
    print(json.dumps(results))


if __name__ == "__main__":
    main()
