"""Offline PROD EID cleanup scope and authority checks; no live credentials."""

import hashlib
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data.intelligence_items import canonical_json
from lyme_gap_atlas_data.intelligence_raw_cleanup import (
    ObjectRawDelete,
    load_exact_plan,
    prod_cleanup_scope,
)
from lyme_gap_atlas_data.intelligence_retention import CleanupPlan, RawCopy, capture_lease
from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    PROD_INTELLIGENCE_CLEANUP_MIGRATION,
    is_intelligence_prerequisite_batch,
    load_migrations,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).parents[1]
MIGRATION_PATH = ROOT / "migrations/V150__prod_intelligence_raw_cleanup_authority.sql"


def test_v150_is_pinned_prod_only_and_checkpoint_delete_is_exact() -> None:
    migration = next(item for item in load_migrations() if item.version == "V150")
    sql = migration.source
    body = sql.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
    body_hash = hashlib.sha256(body.strip().encode()).hexdigest()
    assert migration.sha256 == PROD_INTELLIGENCE_CLEANUP_MIGRATION["sha256"]
    assert migration.filename == PROD_INTELLIGENCE_CLEANUP_MIGRATION["filename"]
    assert "V150" in {item["version"] for item in migration_plan(PROD_DATABASE)}
    assert "V150" not in {item["version"] for item in migration_plan(DEV_DATABASE)}
    reviewed = [
        {"version": migration.version, "filename": migration.filename, "sha256": migration.sha256}
    ]
    assert is_intelligence_prerequisite_batch(reviewed)
    with pytest.raises(ValueError, match="exact and alone"):
        is_intelligence_prerequisite_batch(
            reviewed + [{"version": "V148", "filename": "other.sql", "sha256": "a" * 64}]
        )
    assert "USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD" in render_migration(
        migration, PROD_DATABASE
    )
    with pytest.raises(ValueError, match="PROD-only"):
        render_migration(migration, DEV_DATABASE)
    assert f"'{body_hash}' AS PROCEDURE_BODY_SHA256" in sql
    assert "INVOKER_ROLE() <> 'OH_LYME_PROD_INTELLIGENCE_RAW_PURGE_OWNER'" in body
    assert "CURRENT_DATABASE()='ONE_HEALTH_LYME_GAP_ATLAS_PROD'" in body
    assert "DATEADD(day,30" in body
    assert "DELETE FROM GOVERNANCE.INGESTION_RUN_PAYLOADS" in body
    assert "DELETE FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES" not in body
    assert "DELETE FROM CONFORMED.INTELLIGENCE_ITEM_REVISIONS" not in body
    assert "GRANT USAGE ON PROCEDURE" not in sql
    assert "GRANT OWNERSHIP ON PROCEDURE" not in sql
    assert "GRANT SELECT, DELETE ON TABLE GOVERNANCE.INGESTION_RUN_PAYLOADS" not in sql


def test_one_synthetic_prod_spaces_target_is_exactly_scoped_and_idempotent() -> None:
    lease = capture_lease(
        source_id="cdc-eid-expedited",
        registry_version=1,
        source_sha256="a" * 64,
        capture_id="synthetic-proof-680",
        artifact_sha256="35347e7199b7892e7a0202ed72eafc0147f5a28d1042f27a59d595c9d45fa6b2",
        captured_at="2026-09-01T00:00:00Z",
        policy_ref="reviewed-raw30",
        permitted=lambda *_: True,
    )
    gate = SimpleNamespace(environment="PROD", lease=lambda _: lease)
    key = f"prod/prod/cdc-eid-expedited/synthetic-proof-680/{lease.artifact_sha256}.bin"
    copy = RawCopy(
        "PROD",
        "cdc-eid-expedited",
        "raw_object",
        f"s3://one-health-lyme-gap-atlas-data-prod/{key}",
        lease.sha256,
    )
    events: list[tuple[str, str]] = []

    class Client:
        exists = True

        def head_object(self, **kwargs: str) -> None:
            events.append(("head", kwargs["Key"]))
            if not self.exists:
                error = RuntimeError("synthetic object absent")
                error.response = {"Error": {"Code": "404"}}
                raise error

        def delete_object(self, **kwargs: str) -> None:
            events.append(("delete", kwargs["Key"]))
            self.exists = False

    client = Client()
    driver = ObjectRawDelete(
        gate,
        client,
        bucket="one-health-lyme-gap-atlas-data-prod",
        prefix="prod",
    )
    assert prod_cleanup_scope(copy, driver)
    assert driver(copy)
    assert not driver(copy)
    assert events == [("head", key), ("delete", key), ("head", key)]
    assert not prod_cleanup_scope(
        RawCopy("DEV", copy.source_id, copy.kind, copy.locator, copy.lease_sha256), driver
    )
    assert not prod_cleanup_scope(
        RawCopy("PROD", "another-feed", copy.kind, copy.locator, copy.lease_sha256), driver
    )


def test_exact_prod_plan_rejects_dev_or_unlisted_targets(tmp_path: Path) -> None:
    copy = RawCopy(
        "PROD",
        "cdc-eid-expedited",
        "checkpoint_payload",
        "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_PROD/GOVERNANCE/INGESTION_RUN_PAYLOADS/synthetic-proof-680",
        "a" * 64,
    )
    plan = CleanupPlan(
        "PROD",
        ("cdc-eid-expedited",),
        "2026-10-01T00:00:00Z",
        (copy,),
        "b" * 64,
    )
    path = tmp_path / "prod-plan.json"
    path.write_text(canonical_json(asdict(plan)), encoding="utf-8")
    assert path.stat().st_size < 1024 * 1024
    assert load_exact_plan(path, plan.sha256, environment="PROD") == plan
    with pytest.raises(PermissionError, match="PLAN_CHANGED"):
        load_exact_plan(path, plan.sha256)


def test_prod_cleanup_templates_keep_owner_and_executor_separate() -> None:
    bootstrap = (
        ROOT / "docs/contracts/intelligence/v2/prod-raw-cleanup-security-bootstrap-review.sql"
    ).read_text()
    handoff = (
        ROOT / "docs/contracts/intelligence/v2/prod-raw-cleanup-owner-handoff-review.sql"
    ).read_text()
    assert "CREATE ROLE IF NOT EXISTS OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP;" in bootstrap
    assert "CREATE ROLE IF NOT EXISTS OH_LYME_PROD_INTELLIGENCE_RAW_PURGE_OWNER;" in bootstrap
    assert "GRANT SELECT, DELETE ON TABLE" in bootstrap
    assert "OH_LYME_PROD_RUNTIME" not in bootstrap
    transfer = handoff.index("GRANT OWNERSHIP ON PROCEDURE")
    usage = handoff.index("GRANT USAGE ON PROCEDURE")
    assert "REVOKE CURRENT GRANTS" in handoff[transfer:usage]
    assert transfer < usage
    assert "{{ V150_MIGRATION_SHA256 }}" in handoff
    assert "{{ APPROVED_HANDOFF_REF }}" in handoff


def test_prod_runner_has_fixed_prod_storage_and_separate_approval_identity() -> None:
    runner = (ROOT / "scripts/intelligence_raw_cleanup_prod.py").read_text()
    assert 'DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"' in runner
    assert 'EXECUTOR_ROLE = "OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP"' in runner
    assert 'APPROVER_ROLE = "OH_LYME_PROD_MIGRATION_DEPLOYER"' in runner
    assert 'settings.spaces_bucket != "one-health-lyme-gap-atlas-data-prod"' in runner
    assert 'settings.spaces_prefix != "prod"' in runner
    assert "execute_reviewed_prod_plan" in runner
