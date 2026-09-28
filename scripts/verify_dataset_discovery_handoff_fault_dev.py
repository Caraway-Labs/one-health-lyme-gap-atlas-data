"""One-shot protected DEV post-intake rollback probe for Data #450.

This reproduces V113's serialization and investigation-row insert shape for
one fixed, human-accepted DEV fixture. It raises after the row and receipt view
are visible inside the transaction, rolls back, and checks for zero residue.
The real reviewer procedure must be called separately for the retry.
"""

import hashlib
import json

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"
VERSION = "b0d664168a3ec74d143958e9456f15d58c3947b48d1cfc9931ee494e12133d57"
EVENT = "5ca401592d3b6566d38e0427d9c3331fc735109c337050cf4242039c79954095"
RUN_PREFIX = "data449-rollback-"
OPERATION = f"handoff-v1:{VERSION}"
HANDOFF = hashlib.sha256(OPERATION.encode()).hexdigest()


class ControlledFault(Exception):
    """Raised after the uncommitted downstream insert is visible."""


def one(connection, sql, binds=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, binds)
        return cursor.fetchone()


def command(connection, sql, binds=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, binds)
        return cursor.rowcount


def counts(connection):
    return {
        "investigation": one(
            connection,
            "SELECT COUNT(*) FROM GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS "
            "WHERE operation_key = %s OR handoff_id = %s",
            (OPERATION, HANDOFF),
        )[0],
        "receipt": one(
            connection,
            "SELECT COUNT(*) FROM DATASET_DISCOVERY.V_HANDOFF_RECEIPTS "
            "WHERE operation_key = %s OR handoff_id = %s",
            (OPERATION, HANDOFF),
        )[0],
        "queue": one(
            connection,
            "SELECT COUNT(*) FROM GOVERNANCE.V_DATASET_DISCOVERY_INVESTIGATION_QUEUE "
            "WHERE handoff_id = %s",
            (HANDOFF,),
        )[0],
    }


def main():
    settings = SnowflakeSettings()
    if settings.snowflake_database != DATABASE or settings.snowflake_role != ROLE:
        raise ValueError("Requires protected DEV migration connection")
    with connect(settings) as connection:
        identity = one(
            connection,
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()",
        )
        if identity[1] != ROLE or identity[2] != DATABASE or not identity[3]:
            raise ValueError("Unexpected protected DEV migration identity")
        rec = one(
            connection,
            "SELECT rec.recommendation_id, rec.run_id, rec.resource_key, "
            "rec.catalog_dataset_id, rec.catalog_resource_id, "
            "rec.evidence_snapshot_id, rec.relationship_type, rec.rights_state, "
            "rev.reviewer_user FROM DATASET_DISCOVERY.RECOMMENDATIONS rec "
            "JOIN DATASET_DISCOVERY.V_CURRENT_REVIEW_STATE state "
            "ON state.recommendation_version_id = rec.recommendation_version_id "
            "JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev "
            "ON rev.review_event_id = state.latest_review_event_id "
            "WHERE rec.recommendation_version_id = %s AND rec.commit_complete = TRUE "
            "AND state.review_state = 'ACCEPTED_FOR_INVESTIGATION' "
            "AND rev.review_event_id = %s AND rev.reviewer_user = 'MATTHEWCARAWAY'",
            (VERSION, EVENT),
        )
        if rec is None or not rec[1].startswith(RUN_PREFIX):
            raise ValueError("Fixed accepted DEV fixture is missing")
        rec_id, run_id, resource, dataset, catalog_resource, snapshot, relation, rights, user = rec
        evidence = one(
            connection,
            "SELECT ARRAY_AGG(DISTINCT e.observation_id), "
            "COUNT(DISTINCT e.observation_id) "
            "FROM DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE e "
            "JOIN GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o "
            "ON o.observation_id = e.observation_id "
            "WHERE e.recommendation_version_id = %s "
            "AND e.catalog_dataset_id = %s AND e.catalog_resource_id = %s "
            "AND o.catalog_dataset_id = %s AND o.catalog_resource_id = %s "
            "AND o.canonical_resource_key = %s AND o.ingestion_run_id = %s",
            (VERSION, dataset, catalog_resource, dataset, catalog_resource, resource, snapshot),
        )
        if evidence is None or not 1 <= evidence[1] <= 100:
            raise ValueError("Fixed fixture lacks matching retained evidence")
        observation_ids = evidence[0]
        if isinstance(observation_ids, str):
            observation_ids = json.loads(observation_ids)
        if any(counts(connection).values()):
            raise ValueError("Fixed fixture already has handoff state")

        try:
            command(connection, "BEGIN TRANSACTION")
            changed = command(
                connection,
                "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION "
                "SET revision = revision + 1, touched_at = CURRENT_TIMESTAMP() "
                "WHERE lock_name = 'V1_WRITES'",
            )
            if changed != 1:
                raise AssertionError("Serialization row missing")
            inserted = command(
                connection,
                "INSERT INTO GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS ("
                "handoff_id, operation_key, recommendation_id, recommendation_version_id, "
                "run_id, review_event_id, reviewer_user, resource_key, catalog_dataset_id, "
                "catalog_resource_id, evidence_snapshot_id, evidence_observation_ids, "
                "relationship_type, rights_assertion, reviewed_rights_state, "
                "acquisition_boundary, disposition, investigation_status) "
                "SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "PARSE_JSON(%s), %s, %s, NULL, "
                "'INVESTIGATE_BEFORE_ACQUISITION', 'HANDED_OFF', 'PENDING'",
                (
                    HANDOFF,
                    OPERATION,
                    rec_id,
                    VERSION,
                    run_id,
                    EVENT,
                    user,
                    resource,
                    dataset,
                    catalog_resource,
                    snapshot,
                    json.dumps(observation_ids),
                    relation,
                    rights,
                ),
            )
            if inserted != 1:
                raise AssertionError("Intake insert did not reach one row")
            inside = counts(connection)
            if inside != {"investigation": 1, "receipt": 1, "queue": 1}:
                raise AssertionError(f"Unexpected uncommitted intake shape: {inside}")
            raise ControlledFault("DATA450_AFTER_INTAKE_INSERT_BEFORE_COMMIT")
        except ControlledFault:
            command(connection, "ROLLBACK")
        except BaseException:
            command(connection, "ROLLBACK")
            raise
        after = counts(connection)
        if any(after.values()):
            raise AssertionError(f"Partial handoff state survived rollback: {after}")
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "event": EVENT,
                    "handoff": HANDOFF,
                    "fault": "DATA450_AFTER_INTAKE_INSERT_BEFORE_COMMIT",
                    "inside": inside,
                    "after": after,
                }
            )
        )


if __name__ == "__main__":
    main()
