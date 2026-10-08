"""Credential-free checks for the DEV exact-plan cleanup authority."""

import hashlib
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data.intelligence_items import canonical_json
from lyme_gap_atlas_data.intelligence_raw_cleanup import (
    ObjectRawDelete,
    approved_dev_plan,
    dev_cleanup_scope,
    execute_reviewed_dev_plan,
    load_exact_plan,
    verify_dev_cleanup_handoff,
)
from lyme_gap_atlas_data.intelligence_raw_runtime import SnowflakeRawLedger
from lyme_gap_atlas_data.intelligence_retention import CleanupPlan, RawCopy, capture_lease
from lyme_gap_atlas_data.migrations import load_migrations

MIGRATION = (
    Path(__file__).parents[1] / "migrations/V143__dev_intelligence_raw_cleanup_authority.sql"
)


def plan() -> CleanupPlan:
    return CleanupPlan(
        "DEV",
        ("cdc-eid-expedited",),
        "2026-10-31T00:00:00Z",
        (
            RawCopy(
                "DEV",
                "cdc-eid-expedited",
                "checkpoint_payload",
                "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_DEV/GOVERNANCE/INGESTION_RUN_PAYLOADS/run-1",
                "a" * 64,
            ),
        ),
        "b" * 64,
    )


class Connection:
    def __init__(self, rows: list[tuple[object, ...]], identity: tuple[str, ...]) -> None:
        self.rows = rows
        self.identity = identity
        self.sql: list[str] = []

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def cursor(self) -> "Connection":
        return self

    def execute(self, sql: str, params: tuple[str, ...] = ()) -> None:
        self.sql.append(sql)
        self.result = [self.identity] if "CURRENT_USER" in sql else self.rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.result


IDENTITY = (
    "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP_SVC",
    "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP",
    "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
    "OH_LYME_DEV_INGEST_XS_WH",
)


def test_only_one_exact_attributable_approval_is_accepted() -> None:
    selected = plan()
    row = (canonical_json(asdict(selected)), "reviewer-svc", "review-ref", "approved-time")
    connection = Connection([row], IDENTITY)
    assert approved_dev_plan(lambda: connection, selected)
    assert not approved_dev_plan(lambda: Connection([], IDENTITY), selected)
    assert not approved_dev_plan(lambda: Connection([row, row], IDENTITY), selected)
    assert all("DELETE" not in sql for sql in connection.sql)


def test_wrong_identity_or_mutated_approval_fails_before_execution() -> None:
    selected = plan()
    row = (canonical_json(asdict(selected)), "reviewer-svc", "review-ref", "approved-time")
    with pytest.raises(PermissionError, match="IDENTITY_REQUIRED"):
        approved_dev_plan(lambda: Connection([row], ("wrong", *IDENTITY[1:])), selected)
    with pytest.raises(PermissionError, match="PLAN_CHANGED"):
        approved_dev_plan(lambda: Connection([(row[0] + " ", *row[1:])], IDENTITY), selected)
    with pytest.raises(PermissionError, match="PLAN_CHANGED"):
        approved_dev_plan(
            lambda: Connection([row], IDENTITY), replace(selected, inventory_sha256="c" * 64)
        )


def test_migration_has_only_scoped_dev_authority() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "USE DATABASE {{ DATABASE }}" in sql
    assert "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER" in sql
    assert "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP" in sql
    assert "GRANT SELECT, DELETE ON TABLE GOVERNANCE.INGESTION_RUN_PAYLOADS" not in sql
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT" not in sql
    assert "GRANT OWNERSHIP ON PROCEDURE" not in sql
    assert "OH_LYME_DEV_RUNTIME" not in sql
    assert "ONE_HEALTH_LYME_GAP_ATLAS_PROD" not in sql
    assert "DELETE FROM GOVERNANCE.INGESTION_RUN_NORMALIZED" not in sql
    assert "DATEADD(day,30" in sql
    assert "INVOKER_ROLE() <> 'OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER'" in sql
    assert "IF (handoff_count <> 1) THEN RAISE denied; END IF;" in sql
    assert (
        "GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS\n"
        "    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER"
    ) in sql
    assert "a.DOCUMENT:outcome::VARCHAR='pending'" in sql
    assert "a.DOCUMENT:copy_sha256::VARCHAR=:P_COPY_SHA256" in sql
    assert "c.value:source_id::VARCHAR='cdc-eid-expedited'" in sql
    assert "l.DOCUMENT:source_id::VARCHAR='cdc-eid-expedited'" in sql
    assert "CREATE ROLE" not in sql
    assert "GRANT USAGE ON DATABASE" not in sql
    assert "GRANT USAGE ON SCHEMA GOVERNANCE" not in sql


def test_security_owner_handoff_grants_usage_only_after_transfer() -> None:
    path = (
        Path(__file__).parents[1]
        / "docs/contracts/intelligence/v2/dev-raw-cleanup-owner-handoff-review.sql"
    )
    sql = path.read_text(encoding="utf-8")
    transfer = sql.index("GRANT OWNERSHIP ON PROCEDURE")
    usage = sql.index("GRANT USAGE ON PROCEDURE")
    assert "USE ROLE SECURITYADMIN" in sql
    assert "REVOKE CURRENT GRANTS" in sql[transfer:usage]
    assert "COPY CURRENT GRANTS" not in sql
    assert transfer < usage
    assert "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER" in sql
    migration = next(item for item in load_migrations() if item.version == "V143")
    body = migration.source.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
    assert migration.sha256 in sql
    assert hashlib.sha256(body.strip().encode()).hexdigest() in sql


def test_private_plan_file_requires_exact_canonical_checksum(tmp_path: Path) -> None:
    selected = plan()
    path = tmp_path / "private-plan.json"
    path.write_text(canonical_json(asdict(selected)), encoding="utf-8")
    assert load_exact_plan(path, selected.sha256) == selected
    with pytest.raises(PermissionError, match="PLAN_CHANGED"):
        load_exact_plan(path, "f" * 64)
    path.write_text(canonical_json({**asdict(selected), "extra_target": True}), encoding="utf-8")
    with pytest.raises(PermissionError, match="PLAN_INVALID"):
        load_exact_plan(path, selected.sha256)


def test_dev_scope_only_actual_eid_raw_surfaces() -> None:
    lease = capture_lease(
        source_id="cdc-eid-expedited",
        registry_version=1,
        source_sha256="a" * 64,
        capture_id="capture-1",
        artifact_sha256="b" * 64,
        captured_at="2026-09-01T00:00:00Z",
        policy_ref="reviewed-raw30",
        permitted=lambda *_: True,
    )
    gate = SimpleNamespace(environment="DEV", lease=lambda _: lease)
    driver = ObjectRawDelete(
        gate, object(), bucket="one-health-lyme-gap-atlas-data-dev", prefix="dev"
    )
    object_copy = RawCopy(
        "DEV",
        "cdc-eid-expedited",
        "raw_object",
        "s3://one-health-lyme-gap-atlas-data-dev/dev/dev/cdc-eid-expedited/"
        "run-1/" + "b" * 64 + ".bin",
        lease.sha256,
    )
    assert dev_cleanup_scope(object_copy, driver)
    assert not dev_cleanup_scope(replace(object_copy, source_id="nih-news-releases"), driver)
    assert not dev_cleanup_scope(replace(object_copy, locator="s3://other-bucket/dev/raw"), driver)
    assert not dev_cleanup_scope(
        replace(object_copy, kind="local_checkpoint", locator="file:///private/payload.json"),
        driver,
    )
    assert not dev_cleanup_scope(
        replace(
            object_copy,
            kind="checkpoint_payload",
            locator="snowflake://ONE_HEALTH_LYME_GAP_ATLAS_DEV/GOVERNANCE/INGESTION_RUN_NORMALIZED/run-1",
        ),
        driver,
    )


class HandoffConnection(Connection):
    def __init__(
        self,
        *,
        owner: str = "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER",
        body_sha256: str | None = None,
        grants: list[tuple[str, str, str, bool]] | None = None,
        present: bool = True,
        attested: bool = True,
        created_on: str = "created-at",
        duplicate_attestation: bool = False,
        migration_sha256: str | None = None,
    ) -> None:
        super().__init__([], IDENTITY)
        migration = next(item for item in load_migrations() if item.version == "V143")
        expected_body = migration.source.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
        body_hash = hashlib.sha256(expected_body.strip().encode()).hexdigest()
        self.attestations = (
            [
                (
                    migration_sha256 or migration.sha256,
                    body_sha256 or body_hash,
                    "created-at",
                    owner,
                    "approved-handoff-1",
                    "reviewer-svc",
                    "attested-at",
                )
            ]
            if attested
            else []
        )
        if duplicate_attestation:
            self.attestations *= 2
        self.procedure = (
            [
                (
                    created_on,
                    "PURGE_INTELLIGENCE_RAW_CHECKPOINT",
                    "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                    "GOVERNANCE",
                    4,
                    4,
                )
            ]
            if present
            else []
        )
        self.grants = (
            grants
            if grants is not None
            else [
                ("OWNERSHIP", "ROLE", "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER", False),
                ("USAGE", "ROLE", "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP", False),
            ]
        )

    def execute(self, sql: str, params: tuple[str, ...] = ()) -> None:
        self.sql.append(sql)
        if "CURRENT_USER" in sql:
            self.result = [IDENTITY]
        elif "INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS" in sql:
            self.result = self.attestations
        elif '"created_on"' in sql:
            self.result = self.procedure
        elif "RESULT_SCAN" in sql:
            self.result = self.grants
        else:
            self.result = []


def test_handoff_preflight_requires_exact_owner_definition_and_grants() -> None:
    valid = HandoffConnection()
    verify_dev_cleanup_handoff(lambda: valid)
    assert not any("INFORMATION_SCHEMA.PROCEDURES" in sql or "GET_DDL" in sql for sql in valid.sql)
    verify_dev_cleanup_handoff(
        lambda: HandoffConnection(
            grants=[
                ("OWNERSHIP", "ROLE", "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER", True),
                ("USAGE", "ROLE", "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP", False),
            ]
        )
    )
    for connection in (
        HandoffConnection(present=False),  # partial V143, no procedure
        HandoffConnection(attested=False),  # missing handoff
        HandoffConnection(duplicate_attestation=True),
        HandoffConnection(migration_sha256="f" * 64),
        HandoffConnection(owner="OH_LYME_DEV_MIGRATION_DEPLOYER"),
        HandoffConnection(body_sha256="f" * 64),
        HandoffConnection(created_on="replaced-at"),
        HandoffConnection(grants=[]),  # handoff may have succeeded, USAGE missing
        HandoffConnection(
            grants=[
                ("OWNERSHIP", "ROLE", "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER", False),
                ("USAGE", "ROLE", "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP", False),
                ("USAGE", "ROLE", "OH_LYME_DEV_RUNTIME", False),
            ]
        ),
    ):
        with pytest.raises(PermissionError, match="HANDOFF_REQUIRED"):
            verify_dev_cleanup_handoff(lambda selected=connection: selected)


def test_executor_refuses_partial_handoff_before_delete() -> None:
    connection = HandoffConnection(attested=False)
    gate = SimpleNamespace(
        environment="DEV",
        ledger=SnowflakeRawLedger(
            lambda: connection, "DEV", expected_role="OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP"
        ),
    )
    with pytest.raises(PermissionError, match="HANDOFF_REQUIRED"):
        execute_reviewed_dev_plan(
            gate,
            plan(),
            factory=lambda: connection,
            spaces_client=object(),
            bucket="one-health-lyme-gap-atlas-data-dev",
            prefix="dev",
        )
    assert not any("DELETE" in sql or "CALL GOVERNANCE.PURGE" in sql for sql in connection.sql)
