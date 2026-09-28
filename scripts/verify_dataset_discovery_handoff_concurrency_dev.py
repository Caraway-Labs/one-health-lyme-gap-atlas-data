"""Exercise one handoff from two independent, authenticated DEV reviewer sessions."""

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import snowflake.connector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--review-event-id", required=True)
    args = parser.parse_args()
    if len(args.version_id) != 64 or len(args.review_event_id) != 64:
        raise ValueError("Expected canonical SHA-256 identifiers")

    token = (
        Path(os.environ["DATASET_DISCOVERY_REVIEWER_PAT_FILE"]).read_text(encoding="utf-8").strip()
    )
    barrier = threading.Barrier(2)

    def invoke(index: int) -> dict[str, object]:
        with (
            snowflake.connector.connect(
                account="TXB06009",
                user="MATTHEWCARAWAY",
                authenticator="PROGRAMMATIC_ACCESS_TOKEN",
                token=token,
                role="OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER",
                database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                warehouse="OH_LYME_DEV_INGEST_XS_WH",
                session_parameters={"QUERY_TAG": "data450-concurrent-handoff-dev"},
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT CURRENT_SESSION(), CURRENT_USER(), CURRENT_ROLE(), "
                "CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
            )
            session, user, role, database, warehouse = cursor.fetchone()
            if (
                user != "MATTHEWCARAWAY"
                or role != "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"
                or database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
                or warehouse != "OH_LYME_DEV_INGEST_XS_WH"
            ):
                raise RuntimeError("Unexpected authenticated reviewer context")
            barrier.wait(timeout=30)
            cursor.execute(
                "CALL GOVERNANCE.SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION(%s, %s)",
                (args.version_id, args.review_event_id),
            )
            result = cursor.fetchone()[0]
            if isinstance(result, str):
                result = json.loads(result)
            return {
                "index": index,
                "session": session,
                "query_id": cursor.sfqid,
                "result": result,
            }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, index) for index in (1, 2)]
        results = [future.result() for future in futures]
    if results[0]["session"] == results[1]["session"]:
        raise RuntimeError("Concurrent calls shared one Snowflake session")
    if results[0]["result"] != results[1]["result"]:
        raise RuntimeError("Concurrent calls returned different logical receipts")

    with (
        snowflake.connector.connect(
            account="TXB06009",
            user="MATTHEWCARAWAY",
            authenticator="PROGRAMMATIC_ACCESS_TOKEN",
            token=token,
            role="OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER",
            database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            warehouse="OH_LYME_DEV_INGEST_XS_WH",
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT handoff_id) "
            "FROM DATASET_DISCOVERY.V_HANDOFF_RECEIPTS "
            "WHERE recommendation_version_id = %s",
            (args.version_id,),
        )
        count, distinct_count = cursor.fetchone()
    if count != 1 or distinct_count != 1:
        raise RuntimeError("Concurrent delivery produced duplicate or missing receipts")
    print(json.dumps({"calls": results, "receipt_count": count}))


if __name__ == "__main__":
    main()
