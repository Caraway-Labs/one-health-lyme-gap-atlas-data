"""One-shot protected DEV transaction fault for Data #449.

The protected migration identity already owns the Dataset Discovery tables.
This helper has no DDL, grant, role, or PROD path. It inserts a labeled bundle
inside the V108 serialization transaction shape, raises before commit, rolls
back, then checks base tables and the bounded receipt view for residue.
"""

import argparse
import hashlib
import json
import re

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

RUN_PATTERN = re.compile(r"data449-rollback-[0-9a-f]{32}\Z")
RESOURCE_PATTERN = re.compile(r"candidate:[0-9a-f]{32}\Z")
DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"


class ControlledFault(Exception):
    """Raised only after all three bundle tables contain uncommitted test rows."""


def one(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def command(connection, sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)


def counts(connection, operation_key, run_id, resource_key, version_id):
    recommendation_rows, version_rows = one(
        connection,
        "SELECT COUNT(*), COUNT_IF(recommendation_version_id = %s) "
        "FROM DATASET_DISCOVERY.RECOMMENDATIONS "
        "WHERE operation_key = %s OR recommendation_version_id = %s "
        "OR (run_id = %s AND resource_key = %s)",
        (version_id, operation_key, version_id, run_id, resource_key),
    )
    evidence_rows = one(
        connection,
        "SELECT COUNT(*) FROM DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE "
        "WHERE recommendation_version_id = %s",
        (version_id,),
    )[0]
    proposal_rows = one(
        connection,
        "SELECT COUNT(*) FROM DATASET_DISCOVERY.SEARCH_EXPANSION_PROPOSALS "
        "WHERE recommendation_version_id = %s",
        (version_id,),
    )[0]
    receipt_rows = one(
        connection,
        "SELECT COUNT(*) FROM DATASET_DISCOVERY.V_RECOMMENDATION_RECEIPTS "
        "WHERE operation_key = %s OR recommendation_version_id = %s",
        (operation_key, version_id),
    )[0]
    return {
        "recommendation_rows": recommendation_rows,
        "version_rows": version_rows or 0,
        "evidence_rows": evidence_rows,
        "proposal_rows": proposal_rows,
        "receipt_rows": receipt_rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resource-key", required=True)
    args = parser.parse_args()
    if not RUN_PATTERN.fullmatch(args.run_id) or not RESOURCE_PATTERN.fullmatch(args.resource_key):
        raise ValueError("fault requires a unique labeled DEV run and candidate key")
    settings = SnowflakeSettings()
    if settings.snowflake_database != DATABASE or settings.snowflake_role != ROLE:
        raise ValueError("fault requires the protected DEV migration identity")
    version_id = hashlib.sha256(
        ("recommendation-version-v1\x1f" + args.run_id + "\x1f" + args.resource_key).encode()
    ).hexdigest()
    recommendation_id = hashlib.sha256(
        ("recommendation-v1\x1f" + args.resource_key).encode()
    ).hexdigest()
    operation_key = f"recommendation:{args.run_id}:{args.resource_key}"
    with connect(settings) as connection:
        identity = one(
            connection,
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()",
        )
        if identity[1] != ROLE or identity[2] != DATABASE or not identity[3]:
            raise ValueError("effective Snowflake identity is not protected DEV migrator")
        run = one(
            connection,
            "SELECT status, evidence_snapshot_id FROM DATASET_DISCOVERY.RUNS WHERE run_id = %s",
            (args.run_id,),
        )
        if run is None or run[0] != "RUNNING":
            raise ValueError("prepared test run is missing or terminal")
        snapshot = run[1]
        candidate = one(
            connection,
            "SELECT catalog_dataset_id, catalog_resource_id FROM "
            "DATASET_DISCOVERY.V_CANDIDATE_SUMMARY "
            "WHERE discovery_run_id = %s AND resource_key = %s",
            (snapshot, args.resource_key),
        )
        if candidate is None:
            raise ValueError("prepared candidate is not in the run snapshot")
        observation = one(
            connection,
            "SELECT observation_id FROM DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS "
            "WHERE discovery_run_id = %s AND resource_key = %s "
            "AND catalog_dataset_id = %s AND catalog_resource_id = %s "
            "AND field_values:title::VARCHAR IS NOT NULL ORDER BY observation_id LIMIT 1",
            (snapshot, args.resource_key, candidate[0], candidate[1]),
        )
        if observation is None:
            raise ValueError("prepared candidate has no retained title observation")
        initial = counts(connection, operation_key, args.run_id, args.resource_key, version_id)
        if any(initial.values()):
            raise ValueError("test operation already has recommendation state")
        try:
            command(connection, "BEGIN TRANSACTION")
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION "
                    "SET revision = revision + 1, touched_at = CURRENT_TIMESTAMP() "
                    "WHERE lock_name = 'V1_WRITES'"
                )
                if cursor.rowcount != 1:
                    raise AssertionError("serialization row missing")
                cursor.execute(
                    "INSERT INTO DATASET_DISCOVERY.RECOMMENDATIONS ("
                    "recommendation_version_id, recommendation_id, run_id, operation_key, "
                    "resource_key, catalog_dataset_id, catalog_resource_id, "
                    "evidence_snapshot_id, assertion_sha256, classification, "
                    "relationship_type, relationship_basis, rights_state, observed_facts, "
                    "inferences, unknowns, dimensions, ranking_formula_version, "
                    "relationship_adjustment, missing_count, priority_score, "
                    "priority_bucket, rationale, commit_complete) "
                    "SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "'POSSIBLY_RELEVANT', 'UNKNOWN', 'NO_DETERMINISTIC_LINK', "
                    "'RIGHTS_UNKNOWN', PARSE_JSON('[]'), PARSE_JSON('[]'), "
                    "PARSE_JSON('[]'), PARSE_JSON('{}'), 'recommendation-priority-v1', "
                    "-2, 7, 0, 'LOW', 'DEV_ACCEPTANCE_ROLLBACK_FAULT', TRUE",
                    (
                        version_id,
                        recommendation_id,
                        args.run_id,
                        operation_key,
                        args.resource_key,
                        candidate[0],
                        candidate[1],
                        snapshot,
                        "0" * 64,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AssertionError("recommendation insert did not reach one row")
                cursor.execute(
                    "INSERT INTO DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE ("
                    "recommendation_version_id, observation_id, catalog_dataset_id, "
                    "catalog_resource_id, field_name, metadata_sha256, observed_at) "
                    "SELECT %s, observation_id, catalog_dataset_id, catalog_resource_id, "
                    "'title', metadata_sha256, observed_at "
                    "FROM DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS "
                    "WHERE discovery_run_id = %s AND resource_key = %s AND observation_id = %s",
                    (version_id, snapshot, args.resource_key, observation[0]),
                )
                if cursor.rowcount != 1:
                    raise AssertionError("evidence insert did not reach one row")
                cursor.execute(
                    "INSERT INTO DATASET_DISCOVERY.SEARCH_EXPANSION_PROPOSALS ("
                    "proposal_id, recommendation_version_id, run_id, proposed_term, "
                    "catalog_scope, evidence_observation_ids, rationale, review_status) "
                    "SELECT %s, %s, %s, 'Lyme', 'DEV_ACCEPTANCE_TEST_ONLY', "
                    "PARSE_JSON(%s), 'DEV_ACCEPTANCE_ROLLBACK_FAULT', 'PENDING'",
                    (
                        f"{version_id}:proposal:0",
                        version_id,
                        args.run_id,
                        json.dumps([observation[0]]),
                    ),
                )
                if cursor.rowcount != 1:
                    raise AssertionError("proposal insert did not reach one row")
            inside = counts(connection, operation_key, args.run_id, args.resource_key, version_id)
            if inside != {
                "recommendation_rows": 1,
                "version_rows": 1,
                "evidence_rows": 1,
                "proposal_rows": 1,
                "receipt_rows": 1,
            }:
                raise AssertionError(f"uncommitted bundle shape differs: {inside}")
            raise ControlledFault("DATA449_AFTER_BUNDLE_INSERTS_BEFORE_COMMIT")
        except ControlledFault:
            command(connection, "ROLLBACK")
        except BaseException:
            command(connection, "ROLLBACK")
            raise
        after = counts(connection, operation_key, args.run_id, args.resource_key, version_id)
        if any(after.values()):
            raise AssertionError(f"rolled-back bundle left partial state: {after}")
        run_after = one(
            connection,
            "SELECT status, COUNT(*) FROM DATASET_DISCOVERY.RUNS WHERE run_id = %s GROUP BY status",
            (args.run_id,),
        )
        if run_after != ("RUNNING", 1):
            raise AssertionError("pre-existing run receipt changed during rollback")
        print(
            {
                "run_id": args.run_id,
                "recommendation_version_id": version_id,
                "fault": "DATA449_AFTER_BUNDLE_INSERTS_BEFORE_COMMIT",
                "uncommitted_rows": inside,
                "residual_rows": after,
                "pre_existing_run_receipt": "RUNNING",
            }
        )


if __name__ == "__main__":
    main()
