"""Protected V160-only installation; diagnostic reads use the separate READ caller."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.migrations import (
    PROD_DATABASE,
    apply_migrations,
    load_migrations,
    parse_reviewed_pending_set,
    render_migration,
)
from lyme_gap_atlas_data.sql_sessions import connect

ROOT = Path(__file__).parents[1]
PROPOSAL_SHA = "3173d5da48e807092bd31c134dd1ae1a352a71cb24f77b7861869ca36a79ad7a"
REVOKE_SHA = "51dbef07150869e228a31fe50b037e25c5873f77a6dd4321e7cbf3cc5c711c01"
NAMES = tuple(
    f"LINEAGE_AUDIT.RETAINED_MODEL_{name}_V"
    for name in ("RELEASES", "SOURCES", "MEMBERSHIP", "OBSERVATIONS")
)


def verify_artifacts():
    texts = []
    for suffix, expected in (("proposal", PROPOSAL_SHA), ("revoke", REVOKE_SHA)):
        text = (
            ROOT / f"sql/validation/release-integrity-retained-diagnostic-{suffix}.sql"
        ).read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != expected:
            raise ValueError("LINEAGE_AUTHORIZED_SQL_CHANGED")
        texts.append(text)
    migration = next(m for m in load_migrations() if m.version == "V160")
    rendered = render_migration(migration, PROD_DATABASE)
    if rendered[rendered.index("USE DATABASE ") :] != texts[0][texts[0].index("USE DATABASE ") :]:
        raise ValueError("LINEAGE_MIGRATION_DIFFERS_FROM_AUTHORIZED_SQL")
    if datetime.now(UTC) >= datetime(2026, 10, 25, tzinfo=UTC):
        raise ValueError("LINEAGE_AUTHORIZATION_EXPIRED")
    return migration


def snapshot(settings):
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        identity = cursor.fetchone()
        if identity != (
            "OH_LYME_PROD_MIGRATION_DEPLOY_SVC",
            "OH_LYME_PROD_MIGRATION_DEPLOYER",
            PROD_DATABASE,
            "OH_LYME_PROD_APPROVAL_XS_WH",
        ):
            raise ValueError("LINEAGE_INSTALLATION_IDENTITY")
        cursor.execute(
            "SELECT version,filename,sha256,deployment_commit,applied_by,applied_at "
            "FROM GOVERNANCE.SCHEMA_MIGRATIONS WHERE version<>'V160' ORDER BY version,applied_at"
        )
        ledger = cursor.fetchall()
        cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V")
        release = cursor.fetchall()
        cursor.execute(
            "SELECT model_id,model_version,batch_id,batch_version,COUNT(*) "
            "FROM PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V "
            "GROUP BY model_id,model_version,batch_id,batch_version ORDER BY model_id"
        )
        models = cursor.fetchall()
        if len(release) != 1 or len(models) != 2 or any(row[-1] != 3144 for row in models):
            raise ValueError("LINEAGE_PRODUCTION_BASELINE")
        return {"identity": identity, "ledger": ledger, "release": release, "models": models}


def main():
    commit = os.environ.get("REVIEWED_COMMIT", "")
    if (
        os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
        or os.environ.get("RETAINED_LINEAGE_ONLY") != "true"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or commit != os.environ.get("GITHUB_SHA")
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise SystemExit("LINEAGE_PROTECTED_REVIEWED_MAIN_REQUIRED")
    migration = verify_artifacts()
    settings = SnowflakeSettings()
    before = snapshot(settings)
    receipts = []
    result = {
        "source_commit": commit,
        "migration_sha256": migration.sha256,
        "proposal_sha256": PROPOSAL_SHA,
        "query_receipts": receipts,
        "status": "incomplete",
    }
    try:
        applied = apply_migrations(
            settings,
            PROD_DATABASE,
            commit,
            expected_pending=parse_reviewed_pending_set(os.environ["EXPECTED_PENDING_JSON"]),
            retained_lineage_only=True,
            execution_receipts=receipts,
        )
        if not set(applied) <= {"V160"} or snapshot(settings) != before:
            raise ValueError("LINEAGE_UNRELATED_LEDGER_RELEASE_OR_MODELS_CHANGED")
        views = []
        with connect(settings) as connection, connection.cursor() as cursor:
            for name in NAMES:
                cursor.execute("SELECT GET_DDL('VIEW',%s)", (name,))
                ddl = cursor.fetchone()[0]
                cursor.execute(f"SHOW GRANTS ON VIEW {name}")
                columns = [c[0].lower() for c in cursor.description]
                grants = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
                if not any(
                    g["privilege"] == "SELECT"
                    and g["grantee_name"] == "OH_LYME_PROD_READ"
                    and g["grant_option"] == "false"
                    for g in grants
                ):
                    raise ValueError("LINEAGE_READER_GRANT")
                views.append({"name": name, "ddl": ddl, "grants": grants})
        result.update(
            status="PASS",
            applied=applied,
            baseline=before,
            views=views,
            unrelated_ledger_unchanged=True,
            models_unchanged=True,
            release_pointer_unchanged=True,
            scientific_decision_recorded=False,
        )
    except Exception as exc:
        result.update(
            status="FAIL", error_type=type(exc).__name__, query_id=getattr(exc, "sfqid", None)
        )
        raise
    finally:
        Path("retained-lineage-installation-receipt.json").write_text(
            json.dumps(result, default=str, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps({k: result[k] for k in ("status", "applied", "source_commit", "query_receipts")})
    )


if __name__ == "__main__":
    main()
