"""Offline forward migration and security envelope checks."""

import hashlib
from pathlib import Path

import pytest

from lyme_gap_atlas_data import migrations

ROOT = Path(__file__).parents[1]


def test_proactive_forward_migration_is_exact_prod_only_and_preserves_v150():
    migration = next(m for m in migrations.load_migrations() if m.version == "V162")
    pinned = migrations.PROD_PROACTIVE_INTELLIGENCE_CLEANUP_MIGRATION
    assert migration.sha256 == pinned["sha256"]
    assert migrations.is_intelligence_prerequisite_batch([pinned])
    assert migrations.is_intelligence_prerequisite_batch(
        [migrations.PROD_INTELLIGENCE_CLEANUP_MIGRATION, pinned]
    )
    for batch in (
        [pinned, migrations.PROD_INTELLIGENCE_CLEANUP_MIGRATION],
        [dict(pinned, sha256="f" * 64)],
    ):
        with pytest.raises(ValueError, match="exact and alone"):
            migrations.is_intelligence_prerequisite_batch(batch)
    assert "V162" not in {m["version"] for m in migrations.migration_plan(migrations.DEV_DATABASE)}
    with pytest.raises(ValueError, match="PROD-only"):
        migrations.render_migration(migration, migrations.DEV_DATABASE)
    historical = next(m for m in migrations.load_migrations() if m.version == "V150")
    assert historical.sha256 == migrations.PROD_INTELLIGENCE_CLEANUP_MIGRATION["sha256"]
    old_body = historical.source.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
    body = migration.source.split("AS\n$$\n", 1)[1].split("\n$$;", 1)[0]
    expected = old_body.replace(
        "<=CURRENT_TIMESTAMP();", "<=DATEADD(hour,48,CURRENT_TIMESTAMP());"
    ).replace(">CURRENT_TIMESTAMP();", ">DATEADD(hour,48,CURRENT_TIMESTAMP());")
    # Only eligibility and the complete shared-claim protection are strengthened.
    before, after = "    SELECT COUNT(*) INTO :active_claims", "    IF (active_claims <> 0)"
    assert body.split(before)[0] == expected.split(before)[0]
    assert body.split(after)[1] == expected.split(after)[1]
    assert "LEFT JOIN GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS l" in body
    assert "l.DOCUMENT_KEY IS NULL" in body
    assert "COALESCE(l.DOCUMENT:source_id::VARCHAR,'')<>'cdc-eid-expedited'" in body
    assert "TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR) IS NULL" in body
    assert "TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:captured_at::VARCHAR) IS NULL" in body
    body_hash = hashlib.sha256(body.strip().encode()).hexdigest()
    assert f"'{body_hash}' AS PROCEDURE_BODY_SHA256" in migration.source
    assert "CREATE OR REPLACE PROCEDURE" in migration.source
    assert "COPY GRANTS\n" not in migration.source
    assert "GRANT USAGE ON PROCEDURE" not in migration.source
    assert "WHERE VERSION='V162'" in migration.source
    handoff = (
        ROOT / "docs/contracts/intelligence/v2/prod-proactive-cleanup-owner-handoff-review.sql"
    ).read_text()
    assert body_hash in handoff
    assert "WHERE MIGRATION_SHA256='{{ V162_MIGRATION_SHA256 }}'" in handoff
    assert handoff.index("GRANT OWNERSHIP ON PROCEDURE") < handoff.index("GRANT USAGE ON PROCEDURE")


def test_protected_hosted_route_pins_new_hash_without_accepting_mixed_sets():
    workflow = (ROOT / ".github/workflows/promote-prod.yml").read_text()
    pinned = migrations.PROD_PROACTIVE_INTELLIGENCE_CLEANUP_MIGRATION
    assert pinned["sha256"] in workflow and pinned["filename"] in workflow
    assert (
        'guard_true protected_intelligence_prerequisite "$PROTECTED_INTELLIGENCE_PREREQUISITE"'
        in workflow
    )
