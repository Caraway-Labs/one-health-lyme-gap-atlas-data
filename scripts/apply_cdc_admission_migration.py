"""Exact reviewed V156 through the existing immutable-image production workflow.

Does not register any human decision or move a release pointer. V150 stays pending.
"""

import json
import os
import re
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.cdc_consumer_admission import TARGET_BUNDLE_SHA256, TARGET_RELEASE_ID
from lyme_gap_atlas_data.migrations import apply_migrations, parse_reviewed_pending_set
from lyme_gap_atlas_data.sql_sessions import connect

VIEW = "LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V"
PROCEDURE = "GOVERNANCE.SP_REGISTER_CDC_TARGET_ADMISSION(VARCHAR, VARIANT, VARCHAR)"


def snapshot(settings: SnowflakeSettings, *, deployed: bool) -> list[tuple[Any, ...]]:
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        identity = cursor.fetchone()
        if (
            identity is None
            or identity[1] != "OH_LYME_PROD_MIGRATION_DEPLOYER"
            or identity[2] != "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
        ):
            raise ValueError("CDC_MIGRATION_IDENTITY")
        cursor.execute(
            "SELECT RELEASE_ID,BUNDLE_SHA256 FROM PRESENTATION.CURRENT_RELEASE_V LIMIT 2"
        )
        if cursor.fetchall() != [(TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256)]:
            raise ValueError("CDC_RELEASE_BINDING")
        cursor.execute(f"SHOW GRANTS ON VIEW {VIEW}")
        columns = [str(c[0]).lower() for c in cursor.description]
        grants = [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]
        if not any(
            g["privilege"] == "OWNERSHIP" and g["grantee_name"] == identity[1] for g in grants
        ):
            raise ValueError("CDC_EXISTING_OWNER_REQUIRED")
        if not any(
            g["privilege"] == "SELECT" and g["grantee_name"] == "OH_LYME_PROD_READ" for g in grants
        ):
            raise ValueError("CDC_EXISTING_READER_REQUIRED")
        stable = sorted(
            (g["privilege"], g["granted_to"], g["grantee_name"], g["grant_option"]) for g in grants
        )
        if deployed:
            cursor.execute(f"SHOW GRANTS ON PROCEDURE {PROCEDURE}")
            columns = [str(c[0]).lower() for c in cursor.description]
            procedure_grants = [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]
            if not any(
                g["privilege"] == "OWNERSHIP" and g["grantee_name"] == identity[1]
                for g in procedure_grants
            ):
                raise ValueError("CDC_STEWARD_PROCEDURE_OWNER_REQUIRED")
        return stable


def main() -> None:
    if (
        os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
        or os.environ.get("CDC_ADMISSION_ONLY") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or not os.environ.get("REVIEWED_COMMIT")
        or os.environ.get("REVIEWED_COMMIT") != os.environ.get("GITHUB_SHA")
        or not re.fullmatch(r"[0-9a-f]{40}", os.environ["REVIEWED_COMMIT"])
    ):
        raise SystemExit("CDC_PROTECTED_REVIEWED_MAIN_REQUIRED")
    settings = SnowflakeSettings()
    expected = parse_reviewed_pending_set(os.environ["EXPECTED_PENDING_JSON"])
    before = snapshot(settings, deployed=False)
    applied = apply_migrations(
        settings,
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        os.environ["GITHUB_SHA"],
        expected_pending=expected,
        cdc_admission_only=True,
    )
    if applied not in (["V156"], []) or snapshot(settings, deployed=True) != before:
        raise SystemExit("CDC_MIGRATION_GRANT_PARITY")
    print(
        json.dumps(
            {
                "applied": applied,
                "validated_resume": not applied,
                "grants_unchanged": True,
                "admission_registered": False,
            }
        )
    )


if __name__ == "__main__":
    main()
