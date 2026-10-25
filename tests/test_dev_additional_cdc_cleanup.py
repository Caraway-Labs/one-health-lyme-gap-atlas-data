"""Synthetic exact-plan behavior; not a live purge or Snowflake proof."""

import hashlib
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_intelligence_retention import Ledger

from lyme_gap_atlas_data.intelligence_items import canonical_json
from lyme_gap_atlas_data.intelligence_raw_cleanup import (
    DEV_CLEANUP_SOURCE_IDS,
    dev_cleanup_scope,
    load_exact_plan,
)
from lyme_gap_atlas_data.intelligence_retention import (
    RawCopy,
    capture_lease,
    execute_cleanup,
    plan_cleanup,
)
from lyme_gap_atlas_data.migrations import (
    DEV_FEED_EXPANSION_CLEANUP_MIGRATION,
    is_intelligence_prerequisite_batch,
    load_migrations,
    render_migration,
)


@pytest.mark.parametrize("sid", sorted(DEV_CLEANUP_SOURCE_IDS))
def test_each_dev_source_preserves_expiry_exact_approval_audit_and_live_claims(sid, tmp_path):
    def lease(at):
        return capture_lease(
            source_id=sid,
            registry_version=1,
            source_sha256="a" * 64,
            capture_id=at.replace(":", ""),
            artifact_sha256="b" * 64,
            captured_at=at,
            policy_ref="synthetic-reviewed-30d",
            permitted=lambda *_: True,
        )

    original = lease("2026-09-01T00:00:00Z")
    copy = RawCopy(
        "DEV",
        sid,
        "checkpoint_payload",
        "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_DEV/GOVERNANCE/INGESTION_RUN_PAYLOADS/run-1",
        original.sha256,
    )
    ledger = Ledger([original], [copy])

    def scope(item):
        return dev_cleanup_scope(item, object())

    def plan(now):
        return plan_cleanup(ledger, environment="DEV", source_ids=(sid,), now=now, scope=scope)

    assert plan("2026-09-30T23:59:59.999999Z").copies == ()
    selected = plan("2026-10-01T00:00:00Z")
    assert selected.copies == (copy,)
    path = tmp_path / "plan.json"
    path.write_text(canonical_json(asdict(selected)))
    assert load_exact_plan(path, selected.sha256) == selected
    mutated = replace(selected, source_ids=("nih-news-releases",))
    path.write_text(canonical_json(asdict(mutated)))
    with pytest.raises(PermissionError):
        load_exact_plan(path, mutated.sha256)
    mixed = replace(selected, source_ids=("cdc-mmwr", "cdc-newsroom"))
    path.write_text(canonical_json(asdict(mixed)))
    with pytest.raises(PermissionError):
        load_exact_plan(path, mixed.sha256)
    calls, audit = [], []
    args = dict(
        now="2026-10-01T00:00:00Z",
        scope=scope,
        delete={"checkpoint_payload": lambda value: calls.append(value) or True},
        audit=audit.append,
    )
    with pytest.raises(PermissionError):
        execute_cleanup(selected, ledger, approved=None, **args)
    assert calls == audit == []
    live = lease("2026-09-20T00:00:00Z")
    ledger.leases[live.sha256] = live
    ledger.inventory += (replace(copy, lease_sha256=live.sha256),)
    assert plan("2026-10-01T00:00:00Z").copies == ()
    with pytest.raises(PermissionError):
        execute_cleanup(selected, ledger, approved=lambda _: True, **args)
    assert calls == audit == []
    ledger.inventory = (copy,)
    receipts = execute_cleanup(
        selected, ledger, approved=lambda digest: digest == selected.sha256, **args
    )
    assert calls == [copy]
    assert [entry.outcome for entry in audit] == ["pending", "deleted"]
    assert receipts[0].outcome == "deleted"
    assert not scope(replace(copy, source_id="cdc-outbreaks"))
    assert not scope(replace(copy, environment="PROD"))


def test_v172_is_pinned_dev_only_and_rejects_bundling():
    migration = next(row for row in load_migrations() if row.version == "V172")
    assert migration.sha256 == DEV_FEED_EXPANSION_CLEANUP_MIGRATION["sha256"]
    assert is_intelligence_prerequisite_batch([DEV_FEED_EXPANSION_CLEANUP_MIGRATION])
    with pytest.raises(ValueError):
        is_intelligence_prerequisite_batch(
            [DEV_FEED_EXPANSION_CLEANUP_MIGRATION, DEV_FEED_EXPANSION_CLEANUP_MIGRATION]
        )
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    body = migration.source.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
    digest = hashlib.sha256(body.strip().encode()).hexdigest()
    assert digest in migration.source
    handoff = (
        Path(__file__).parents[1]
        / "docs/contracts/intelligence/v2/dev-additional-feed-cleanup-owner-handoff-review.sql"
    ).read_text()
    assert migration.sha256 in handoff and digest in handoff
    assert "GRANT USAGE ON PROCEDURE" not in migration.source
    assert "GRANT OWNERSHIP" not in migration.source
    assert "COPY GRANTS AS" not in migration.source
    assert "ONE_HEALTH_LYME_GAP_ATLAS_PROD" not in migration.source
