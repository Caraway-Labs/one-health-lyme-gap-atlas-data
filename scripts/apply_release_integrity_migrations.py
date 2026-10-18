"""Install only reviewed V157/V158 using the existing protected image promotion.

No approval, batch publication, source retagging or release-pointer movement.
The complete pending inventory is reviewed even though unrelated DDL is deferred.
"""

import json
import os
import re

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.migrations import apply_migrations, parse_reviewed_pending_set
from lyme_gap_atlas_data.sql_sessions import connect

TARGETS = {"V157", "V158"}
RELEASE = "governed-2026-10-15-january-climate-prod"
BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"


def snapshot(settings):
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        context = cursor.fetchone()
        if (
            context is None
            or not context[0]
            or not context[3]
            or tuple(context[1:3])
            != ("OH_LYME_PROD_MIGRATION_DEPLOYER", "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
        ):
            raise ValueError("INTEGRITY_MIGRATION_IDENTITY")
        cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V")
        if cursor.fetchall() != [(RELEASE, BUNDLE)]:
            raise ValueError("INTEGRITY_RELEASE_BINDING")
        cursor.execute(
            "SELECT version,filename,sha256,deployment_commit,applied_by,applied_at "
            "FROM GOVERNANCE.SCHEMA_MIGRATIONS ORDER BY version,applied_at"
        )
        return [tuple(row) for row in cursor.fetchall() if row[0] not in TARGETS]


def main():
    commit = os.environ.get("REVIEWED_COMMIT", "")
    if (
        os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
        or os.environ.get("RELEASE_INTEGRITY_ONLY") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or commit != os.environ.get("GITHUB_SHA")
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise SystemExit("INTEGRITY_PROTECTED_REVIEWED_MAIN_REQUIRED")
    source = os.environ.get("RI706_VALIDATED_SOURCE_COMMIT", "")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RI706_VALIDATED_MERGE_COMMIT") != commit
        or not re.fullmatch(r"[0-9a-f]{40}", source)
    ):
        raise SystemExit("INTEGRITY_DEV_TESTED_SOURCE_RECEIPT_REQUIRED")
    settings = SnowflakeSettings()
    reviewed = parse_reviewed_pending_set(os.environ["EXPECTED_PENDING_JSON"])
    before = snapshot(settings)
    applied = apply_migrations(
        settings,
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        source,
        expected_pending=reviewed,
        release_integrity_only=True,
    )
    if not set(applied) <= TARGETS or snapshot(settings) != before:
        raise SystemExit("INTEGRITY_UNRELATED_LEDGER_OR_POINTER_CHANGED")
    print(
        json.dumps(
            {
                "applied": applied,
                "source_commit": source,
                "merged_main_commit": commit,
                "unrelated_ledger_unchanged": True,
                "release_pointer_unchanged": True,
                "decisions_recorded": False,
                "batches_published": False,
            }
        )
    )


if __name__ == "__main__":
    main()
