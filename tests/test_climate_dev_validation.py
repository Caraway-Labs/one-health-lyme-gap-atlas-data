"""Offline safety and scope checks; these do not claim live DEV validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyme_gap_atlas_data.climate_dev_validation import (
    DEV,
    ROLE,
    USER,
    WAREHOUSE,
    numeric_expressions,
    numeric_query,
    verify_dev,
)
from lyme_gap_atlas_data.climate_semantics import january_measure_definitions
from lyme_gap_atlas_data.migrations import PROD_DATABASE, load_migrations, migration_plan
from lyme_gap_atlas_data.semantic_metadata import (
    SemanticMetadataError,
    metadata_revision_id,
    validate_metadata,
)

ROOT = Path(__file__).parents[1]
SQL = (ROOT / "sql/january_climate_consumer_views.sql").read_text()


def test_v136_is_exact_reviewed_views_dev_only_without_grants() -> None:
    migration = next(item for item in load_migrations() if item.version == "V136")
    assert migration.source.endswith(SQL)
    assert "GRANT " not in migration.source
    assert "UPDATE " not in migration.source and "INSERT " not in migration.source
    assert "V136" in {item["version"] for item in migration_plan(DEV)}
    assert "V136" not in {item["version"] for item in migration_plan(PROD_DATABASE)}


def test_numeric_query_uses_all_actual_view_expressions_and_both_null_shapes() -> None:
    assert len(numeric_expressions(SQL)) == 21
    assert "OBJECT_CONSTRUCT(" in numeric_query(SQL, "NULL::VARIANT")
    assert "OBJECT_CONSTRUCT_KEEP_NULL(" in numeric_query(SQL, "PARSE_JSON('null')")


@pytest.mark.parametrize(
    "identity",
    [
        (USER, ROLE, PROD_DATABASE, WAREHOUSE),
        ("MATTHEWCARAWAY", ROLE, DEV, WAREHOUSE),
        (USER, "OH_LYME_DEV_READ", DEV, WAREHOUSE),
    ],
)
def test_identity_failure_precedes_any_fixture_table_or_release_write(identity) -> None:
    class Cursor:
        statements = []

        def execute(self, sql):
            self.statements.append(sql)

        def fetchone(self):
            return identity

    cursor = Cursor()
    with pytest.raises(ValueError, match="IDENTITY"):
        verify_dev(cursor, SQL, "offline-fixture")
    assert len(cursor.statements) == 1 and cursor.statements[0].startswith("SELECT CURRENT")


def test_large_manifest_is_fixture_only_and_temporary_table_is_removed(monkeypatch) -> None:
    import lyme_gap_atlas_data.climate_dev_validation as validation

    monkeypatch.setattr(
        validation,
        "CASES",
        (
            ("double", "fixture", 1.0),
            ("integer", "fixture", 1),
            ("decimal", "fixture", 1),
        ),
    )
    # Numeric parity is independently covered by the actual-expression offline harness.
    monkeypatch.setattr(
        validation, "decode_numeric_fields", lambda row: dict.fromkeys(validation.FIELDS, 1)
    )

    class Cursor:
        statements = []
        fixture = None
        numeric = 0
        description = []

        def execute(self, sql, parameters=None):
            self.statements.append(sql)
            if sql.startswith("WITH records"):
                kind = ("DOUBLE", "INTEGER", "DECIMAL")[self.numeric]
                self.numeric += 1
                row = {f"{field}_stored_type": kind for field in validation.FIELDS}
                row.update({f"{field}_is_sql_null": False for field in validation.FIELDS})
                self.description = [(name,) for name in row]
                self.row = tuple(row.values())
            if sql.startswith("INSERT"):
                self.fixture = json.loads(parameters[0])

        def fetchone(self):
            if self.statements[-1].startswith("SELECT CURRENT"):
                return USER, ROLE, DEV, WAREHOUSE
            if self.statements[-1].startswith("SELECT document"):
                return (json.dumps(self.fixture),)
            return self.row

    cursor = Cursor()
    report = verify_dev(cursor, SQL, "offline-fixture")
    assert cursor.fixture["fixture"] is True
    assert cursor.fixture["approved_source_versions"] == []
    assert cursor.fixture["metadata_review"] == "PENDING"
    assert report["fixture_capture_ids"] == 389856
    assert report["manifest_bytes"] > 16 * 1024 * 1024
    assert cursor.statements[-1].startswith("DROP TABLE PRESENTATION.CLIMATE_VALIDATION_")
    assert all("SEMANTIC_RELEASE" not in sql and "GRANT " not in sql for sql in cursor.statements)


def test_workflow_diagnostic_exits_before_guarded_migration_apply() -> None:
    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    mode = workflow.index('if [ "$DIAGNOSE_CLIMATE_DEV" = "true" ]; then')
    apply = workflow.rindex("apply-reviewed-dev-migrations")
    assert (
        mode
        < workflow.index("scripts/verify_climate_dev.py", mode)
        < workflow.index("exit 0", mode)
        < apply
    )
    early = workflow.split('if [ "$feed_batch" = "true" ]; then', 1)[1].split("exit 0", 1)[0]
    assert 'test "$DIAGNOSE_CLIMATE_DEV" != "true"' in early
    assert "expected_pending_json" in workflow


def test_real_review_packet_retains_unresolved_authority_and_no_invented_approval() -> None:
    packet = json.loads(
        (
            ROOT / "docs/contracts/climate/january-2025-metadata-source-review-packet.json"
        ).read_text()
    )
    assert packet["approved_source_versions"] == []
    assert packet["steward_approval"] is None and packet["review_evidence"] == []
    assert packet["source_authority_evidence"]["query_succeeded"] is True
    assert packet["source_authority_evidence"]["rows"] == []
    proposals = packet["metadata_proposals"]
    assert [item["measure"] for item in proposals] == january_measure_definitions()
    for item in proposals:
        assert item["steward_review"]["state"] == "PENDING"
        assert item["provenance"]["source_version_id"] == {"state": "UNKNOWN", "value": None}
        assert item["revision_id"] == metadata_revision_id(item)
        with pytest.raises(SemanticMetadataError, match="mandatory source_version_id"):
            validate_metadata(item)
