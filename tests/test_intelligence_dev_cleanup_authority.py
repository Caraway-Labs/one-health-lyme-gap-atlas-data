"""Credential-free checks for the DEV exact-plan cleanup authority."""

from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data.intelligence_items import canonical_json
from lyme_gap_atlas_data.intelligence_raw_cleanup import (
    ObjectRawDelete,
    approved_dev_plan,
    dev_cleanup_scope,
    load_exact_plan,
)
from lyme_gap_atlas_data.intelligence_retention import CleanupPlan, RawCopy, capture_lease

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
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT" in sql
    assert "OH_LYME_DEV_RUNTIME" not in sql
    assert "ONE_HEALTH_LYME_GAP_ATLAS_PROD" not in sql
    assert "DELETE FROM GOVERNANCE.INGESTION_RUN_NORMALIZED" not in sql
    assert "DATEADD(day,30" in sql
    assert "a.DOCUMENT:outcome::VARCHAR='pending'" in sql
    assert "a.DOCUMENT:copy_sha256::VARCHAR=:P_COPY_SHA256" in sql
    assert "c.value:source_id::VARCHAR='cdc-eid-expedited'" in sql
    assert "l.DOCUMENT:source_id::VARCHAR='cdc-eid-expedited'" in sql
    assert "CREATE ROLE" not in sql
    assert "GRANT USAGE ON DATABASE" not in sql
    assert "GRANT USAGE ON SCHEMA GOVERNANCE" not in sql


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
