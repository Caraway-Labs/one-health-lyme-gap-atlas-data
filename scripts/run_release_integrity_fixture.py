"""Protected fixed-schema DEV installer; synthetic evidence is never owner approval."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import threading
import time
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from prepare_release_integrity_dev_plan import SCHEMAS, render_fixture
from publish_surveillance_situations import verify
from pydantic import SecretStr

from lyme_gap_atlas_data.migrations import load_migrations
from lyme_gap_atlas_data.sql_sessions import connect

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
MARKER = "RI706_DEV_SYNTHETIC_TEST_ONLY_NOT_SCIENTIFIC_APPROVAL"
SOURCES = ("human", "tick", "pathogen", "context_svi", "context_rucc")
OLD = "governed-2026-09-18-unknown-coverage"
OLD_BUNDLE = "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026"
FROZEN = "governed-2026-10-15-january-climate-prod"
BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"
TARGETS = {"V157", "V158"}
ROLES = {
    "migration": "MIGRATION_DEPLOYER",
    "owner": "OWNER",
    "publisher": "ML_PUBLISHER",
    "reader": "READ",
    "runtime": "RUNTIME",
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def binding_from_environment():
    commit = os.environ.get("REVIEWED_COMMIT", "")
    image = os.environ.get("RI706_IMAGE_DIGEST", "")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RI706_FIXTURE_MODE") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "Caraway-Labs/one-health-lyme-gap-atlas-data"
        or commit != os.environ.get("GITHUB_SHA")
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    ):
        raise ValueError("RI706_PROTECTED_EXACT_COMMIT_IMAGE_REQUIRED")
    review = json.loads(Path(os.environ["RI706_REVIEW_RECEIPT"]).read_text())
    if review.get("reviewed_commit") != commit or review.get("scope") != MARKER:
        raise ValueError("RI706_REVIEW_BINDING_REQUIRED")
    selected = [m for m in load_migrations() if m.version in TARGETS]
    artifacts = [
        {
            "version": m.version,
            "filename": m.filename,
            "source_sha256": m.sha256,
            "rendered_sha256": digest(render_fixture(m)),
        }
        for m in selected
    ]
    if (
        artifacts != json.loads(os.environ["RI706_EXPECTED_ARTIFACTS"])
        or {a["version"] for a in artifacts} != TARGETS
    ):
        raise ValueError("RI706_EXACT_SOURCE_AND_RENDERED_CHECKSUMS_REQUIRED")
    return {"marker": MARKER, "commit": commit, "image_digest": image, "artifacts": artifacts}


def retained_installation_binding(binding):
    review = json.loads(Path(os.environ["RI706_REVIEW_RECEIPT"]).read_text())
    recovery = review.get("owner_authorization", {}).get("binding", {}).get("recovery")
    if not recovery:
        return binding
    installed = recovery["installation_binding"]
    if (
        installed.get("artifacts") != binding["artifacts"]
        or installed.get("marker") != MARKER
        or not re.fullmatch(r"[0-9a-f]{40}", installed.get("commit", ""))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", installed.get("image_digest", ""))
    ):
        raise PermissionError("RI706_RETAINED_INSTALLATION_BINDING_MISMATCH")
    return installed


class Fixture:
    def __init__(self, binding, receipt, *, installation_binding=None):
        self.binding, self.path = binding, receipt
        self.installation_binding = installation_binding or binding
        self.started = time.monotonic()
        self.receipt = {"binding": binding, "status": "INCOMPLETE", "queries": [], "cases": []}
        self.receipt["installation_binding"] = self.installation_binding
        self.settings = SnowflakeSettings()
        self.connections = []
        self.receipt_lock = threading.RLock()

    def save(self):
        with self.receipt_lock:
            temporary = self.path.with_suffix(".writing")
            temporary.write_text(json.dumps(self.receipt, indent=2, default=str) + "\n")
            temporary.replace(self.path)

    def open(self, profile="migration"):
        settings = self.settings
        if profile != "migration":
            prefix = "RI706_" + profile.upper() + "_"
            user, key = os.environ.get(prefix + "USER"), os.environ.get(prefix + "PRIVATE_KEY_B64")
            if not user or not key:
                raise PermissionError("RI706_MISSING_PROTECTED_" + profile.upper() + "_CREDENTIALS")
            settings = settings.model_copy(
                update={
                    "snowflake_user": user,
                    "snowflake_role": "OH_LYME_DEV_" + ROLES[profile],
                    "snowflake_private_key_b64": SecretStr(key),
                    "snowflake_private_key_passphrase": SecretStr(
                        os.environ[prefix + "PRIVATE_KEY_PASSPHRASE"]
                    )
                    if os.environ.get(prefix + "PRIVATE_KEY_PASSPHRASE")
                    else None,
                }
            )
        expected = "OH_LYME_DEV_" + ROLES[profile]
        if (
            settings.snowflake_database != DATABASE
            or settings.snowflake_auth_method != "key_pair"
            or settings.snowflake_role != expected
            or settings.snowflake_warehouse != "OH_LYME_DEV_INGEST_XS_WH"
            or (
                profile == "migration"
                and settings.snowflake_user != "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
            )
        ):
            raise PermissionError("RI706_EXACT_DEV_SERVICE_CONFIGURATION_REQUIRED")
        connection = connect(settings)
        self.connections.append(connection)
        self.query(connection, "secondary_roles_none", "USE SECONDARY ROLES NONE", live=True)
        context = self.query(
            connection,
            "context",
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()",
            live=True,
        )
        if context != [(settings.snowflake_user, expected, DATABASE, "OH_LYME_DEV_INGEST_XS_WH")]:
            raise PermissionError("RI706_ACTUAL_CONTEXT_MISMATCH")
        self.query(
            connection,
            "limits",
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60,"
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10,LOCK_TIMEOUT=10,ABORT_DETACHED_QUERY=TRUE,"
            "QUERY_TAG='RI706_DEV_SYNTHETIC_TEST_ONLY'",
            live=True,
        )
        forbidden = ["ACCOUNTADMIN", "OH_LYME_PROD_OWNER", "OH_LYME_PROD_MIGRATION_DEPLOYER"]
        if profile in {"reader", "publisher", "runtime"}:
            forbidden += ["OH_LYME_DEV_OWNER", "OH_LYME_DEV_MIGRATION_DEPLOYER"]
        inherited = self.query(
            connection,
            "forbidden_role_check",
            "SELECT " + ",".join("IS_ROLE_IN_SESSION('" + role + "')" for role in forbidden),
            live=True,
        )
        if inherited != [tuple(False for _ in forbidden)]:
            raise PermissionError("RI706_FORBIDDEN_INHERITED_AUTHORITY")
        self.receipt.setdefault("contexts", {})[profile] = context
        return connection

    def query(self, connection, label, sql, params=(), *, live=False):
        if time.monotonic() - self.started > 900:
            raise TimeoutError("RI706_900_SECOND_TOTAL_LIMIT")
        if "ONE_HEALTH_LYME_GAP_ATLAS_PROD" in sql.upper():
            raise ValueError("RI706_PRODUCTION_REFERENCE_FORBIDDEN")
        if live and not (
            sql.startswith(("SELECT ", "USE SECONDARY ROLES NONE", "ALTER SESSION SET "))
            and not re.search(
                r";|\b(INSERT|UPDATE|DELETE|CREATE|GRANT|CALL|DROP|ALTER TABLE)\b", sql
            )
        ):
            raise ValueError("RI706_LIVE_MUTATION_FORBIDDEN")
        if not live:
            for schema, target in SCHEMAS.items():
                sql = re.sub(r"\b" + schema + r"\.", target + ".", sql)
            if re.search(r"\b(?:FEATURE_STORE|PRESENTATION|GOVERNANCE)\.", sql):
                raise ValueError("RI706_UNISOLATED_REFERENCE")
        with connection.cursor() as cursor:
            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall() if cursor.description else []
                self.receipt["queries"].append(
                    {"label": label, "query_id": cursor.sfqid, "status": "PASS"}
                )
                if label.endswith(("_count", "_counts")) or label in {
                    "tier1_actual_eligibility",
                    "probability_integrity",
                    "atomic_state",
                }:
                    self.receipt.setdefault("aggregate_results", {})[label] = rows
                self.save()
                return rows
            except Exception as error:
                self.receipt["queries"].append(
                    {
                        "label": label,
                        "query_id": cursor.sfqid,
                        "status": "ERROR",
                        "error_code": getattr(error, "errno", None),
                        "sqlstate": getattr(error, "sqlstate", None),
                    }
                )
                self.save()
                raise

    def snapshot(self, connection):
        # Fixed read-only exceptions, never caller-supplied live SQL.
        return {
            "release": self.query(
                connection,
                "live_pointer_read_only",
                "SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V",
                live=True,
            ),
            "ledger": self.query(
                connection,
                "live_ledger_read_only",
                "SELECT version,filename,sha256,"
                "deployment_commit,applied_by,applied_at FROM GOVERNANCE.SCHEMA_MIGRATIONS "
                "ORDER BY version,filename,sha256,deployment_commit,applied_by,applied_at",
                live=True,
            ),
        }

    def install(self, connection, *, stop_after_v157=False):
        reusing = self.installation_binding != self.binding
        marker = json.dumps(self.installation_binding, sort_keys=True, separators=(",", ":"))
        rows = self.query(
            connection,
            "schema_preflight",
            "SELECT SCHEMA_NAME,COMMENT,SCHEMA_OWNER FROM "
            "INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME IN "
            "('RI706_GOVERNANCE','RI706_PRESENTATION','RI706_FEATURE_STORE')",
            live=True,
        )
        if any(
            comment != marker or owner != "OH_LYME_DEV_MIGRATION_DEPLOYER"
            for _, comment, owner in rows
        ):
            raise PermissionError("RI706_EXISTING_SCHEMA_BINDING_MISMATCH")
        present = {name for name, _, _ in rows}
        if reusing and present != set(SCHEMAS.values()):
            raise PermissionError("RI706_RETAINED_SCHEMAS_MUST_ALL_EXIST")
        for schema in ("RI706_GOVERNANCE", "RI706_PRESENTATION", "RI706_FEATURE_STORE"):
            if schema not in present:
                self.query(
                    connection,
                    "create_" + schema,
                    "CREATE SCHEMA " + schema + " COMMENT=%s",
                    (marker,),
                )
        if not reusing:
            self.query(
                connection,
                "fixture_ledger",
                (
                    "CREATE TABLE IF NOT EXISTS GOVERNANCE.SCHEMA_MIGRATIONS (version "
                    "VARCHAR,filename VARCHAR,sha256 VARCHAR,rendered_sha256 VARCHAR,d"
                    "eployment_commit VARCHAR,image_digest VARCHAR,marker VARCHAR,appl"
                    "ied_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP())"
                ),
            )
        ledger = self.query(
            connection,
            "fixture_ledger_read",
            (
                "SELECT version,sha256,rendered_sha256,deployment_commit,image_dig"
                "est,marker FROM GOVERNANCE.SCHEMA_MIGRATIONS ORDER BY version"
            ),
        )
        expected = {
            a["version"]: (
                a["source_sha256"],
                a["rendered_sha256"],
                self.installation_binding["commit"],
                self.installation_binding["image_digest"],
                MARKER,
            )
            for a in self.binding["artifacts"]
        }
        if len(ledger) != len({row[0] for row in ledger}) or any(
            row[0] not in expected or tuple(row[1:]) != expected[row[0]] for row in ledger
        ):
            raise PermissionError("RI706_IMMUTABLE_LEDGER_MISMATCH")
        if reusing and {row[0] for row in ledger} != TARGETS:
            raise PermissionError("RI706_RETAINED_PAIR_MUST_BE_COMPLETE")
        seed = self.query(
            connection,
            "seed_presence",
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA='RI706_GOVERNANCE' AND TABLE_NAME='SEED_RECEIPT'",
            live=True,
        )
        if seed == [(0,)]:
            if reusing:
                raise PermissionError("RI706_RETAINED_SEED_MUST_EXIST")
            from release_integrity_fixture_seed import seed_prerequisites

            seed_prerequisites(self, connection)
        elif self.query(
            connection, "seed_recovery", "SELECT marker FROM GOVERNANCE.SEED_RECEIPT"
        ) != [(MARKER,)]:
            raise PermissionError("RI706_PARTIAL_SEED_REQUIRES_REVIEW")
        installed = {row[0] for row in ledger}
        for migration in load_migrations():
            if migration.version not in TARGETS or migration.version in installed:
                continue
            if migration.version == "V158" and stop_after_v157:
                raise InterruptedError("RI706_SYNTHETIC_PARTIAL_INSTALL_RECOVERY_TEST")
            for cursor in connection.execute_stream(io.StringIO(render_fixture(migration))):
                self.receipt["queries"].append(
                    {
                        "label": "install_" + migration.version,
                        "query_id": cursor.sfqid,
                        "status": "PASS",
                    }
                )
                self.save()
            artifact = next(
                a for a in self.binding["artifacts"] if a["version"] == migration.version
            )
            self.query(
                connection,
                "record_" + migration.version,
                "INSERT INTO GOVERNANCE.SCHEMA_MIGRATIONS(version,filename,sha256,rendered_sha256,"
                "deployment_commit,image_digest,marker) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    migration.version,
                    migration.filename,
                    artifact["source_sha256"],
                    artifact["rendered_sha256"],
                    self.binding["commit"],
                    self.binding["image_digest"],
                    MARKER,
                ),
            )
            connection.commit()
        for role in () if reusing else ("OWNER", "ML_PUBLISHER", "READ", "RUNTIME"):
            for schema in SCHEMAS.values():
                self.query(
                    connection,
                    "fixture_schema_usage",
                    "GRANT USAGE ON SCHEMA " + schema + " TO ROLE OH_LYME_DEV_" + role,
                )
        self.receipt["installation"] = "PASS"
        self.receipt["installation_mode"] = (
            "REUSED_IMMUTABLE_PAIR" if reusing else "EXACT_INSTALL_OR_REPLAY"
        )
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--stop-after-v157", action="store_true")
    args = parser.parse_args()
    binding = binding_from_environment()
    if args.receipt.exists():
        raise ValueError("RI706_RECEIPT_MUST_BE_FRESH")
    documents = verify(args.handoff)
    fixture = Fixture(
        binding, args.receipt, installation_binding=retained_installation_binding(binding)
    )
    connection = fixture.open()
    before = fixture.snapshot(connection)
    fixture.receipt["live_before"] = before
    fixture.save()
    try:
        fixture.install(connection, stop_after_v157=args.stop_after_v157)
        if not args.install_only:
            from release_integrity_fixture_matrix import run_matrix

            run_matrix(fixture, connection, documents)
        fixture.receipt["status"] = "PASS"
    except InterruptedError:
        fixture.receipt["status"] = "PLANNED_PARTIAL_INSTALL_TEST"
        raise SystemExit(75) from None
    except Exception as error:
        fixture.receipt["status"] = "BLOCKED" if isinstance(error, PermissionError) else "FAIL"
        fixture.receipt["failure_type"] = type(error).__name__
        raise
    finally:
        try:
            after = fixture.snapshot(connection)
            fixture.receipt["live_after"] = after
            fixture.receipt["live_unchanged"] = before == after
            if before != after:
                fixture.receipt["status"] = "FAIL_LIVE_STATE_CHANGED"
                raise RuntimeError("RI706_LIVE_STATE_CHANGED")
        finally:
            fixture.save()
            for session in fixture.connections:
                session.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Connector exceptions can contain SQL/payloads; retain only redacted receipts.
        raise SystemExit("RI706_FAILED_SEE_REDACTED_RECEIPT") from None
