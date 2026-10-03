"""Authority, idempotence and transaction boundaries, not live Snowflake proof."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lyme_gap_atlas_data.climate_source_review import (
    DRAFT_METADATA_REVISIONS,
    INPUTS,
    RESOURCE_KEY,
    inspect_retained_inputs,
    prepare_recorded_acceptance,
    reconcile,
    record_steward_decision,
    register_pending_inputs,
)


class Cursor:
    def __init__(self, role="OH_LYME_DEV_RUNTIME", registered=False):
        self.role = role
        self.registered = registered
        self.statements = []
        self.rows = []
        self.corrupt = False
        self.conflict = False
        self.fail_second_review = False
        self.resource_url = None
        self.canonical_url = None
        self.dataset_key = "FIXTURE_DEFAULT"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        self.rows = []
        if sql.startswith("SELECT CURRENT_USER"):
            self.rows = [("MATTHEWCARAWAY", self.role, "ONE_HEALTH_LYME_GAP_ATLAS_DEV")]
        elif sql == "SELECT CURRENT_DATABASE()":
            self.rows = [("ONE_HEALTH_LYME_GAP_ATLAS_DEV",)]
        elif "FROM GOVERNANCE.INGESTION_RUNS" in sql:
            self.rows = [(RESOURCE_KEY, "COMPLETED")]
        elif "FROM GOVERNANCE.RAW_ARTIFACTS" in sql:
            source = next(s for s in INPUTS if s["artifact_id"] == params[0])
            self.rows = [("wrong" if self.corrupt else source["sha256"], source["byte_count"])]
        elif "FROM GOVERNANCE.CATALOG_RESOURCES" in sql:
            if self.registered or self.conflict:
                source = next(s for s in INPUTS if s["resource_key"] == params[0])
                self.rows = [
                    (
                        "unrelated" if self.conflict else params[0],
                        "linked-dataset",
                        False,
                        self.resource_url or source["url"],
                        self.canonical_url or source["url"],
                        source["dataset_key"]
                        if self.dataset_key == "FIXTURE_DEFAULT"
                        else self.dataset_key,
                    )
                ]
        elif "FROM GOVERNANCE.DATA_SOURCE_VERSIONS" in sql and self.registered:
            source = next(s for s in INPUTS if s["artifact_id"] == params[1])
            self.rows = [
                ("pending-version", source["resource_key"], source["artifact_id"], "PENDING", None)
            ]
        elif "FROM GOVERNANCE.APPROVAL_STEWARDS" in sql:
            self.rows = [(1,)]
        if (
            self.fail_second_review
            and sql.startswith("INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS")
            and params[1] == INPUTS[1]["resource_key"]
        ):
            raise RuntimeError("simulated second write failure")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class Connection:
    def __init__(self, cursor):
        self.value = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.value

    def autocommit(self, enabled):
        assert enabled is False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def decision():
    return {
        "reviewer": "MATTHEWCARAWAY",
        "reviewed_at": datetime.now(UTC).isoformat(),
        "evidence": "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/443#issuecomment-123",
        "rationale": "Fixture reviewer accepts exact definitions with January weather-only "
        "conditions.",
        "accepted_metadata_revisions": sorted(DRAFT_METADATA_REVISIONS),
    }


def accepted_record():
    root = Path(__file__).resolve().parents[1] / "docs/contracts/climate"
    packet = json.loads((root / "january-2025-metadata-source-review-packet.json").read_text())
    acceptance = json.loads((root / "january-2025-product-approval.json").read_text())
    return packet, acceptance


def test_recording_preserves_unknown_original_time_and_exact_content():
    packet, acceptance = accepted_record()
    stamp = datetime.now(UTC).isoformat()
    record = prepare_recorded_acceptance(packet, acceptance, recorded_at=stamp)
    cursor = Cursor("OH_LYME_DEV_OWNER", registered=True)
    record_steward_decision(cursor, record)
    writes = [
        params
        for sql, params in cursor.statements
        if sql.startswith("INSERT INTO GOVERNANCE.MANUAL")
    ]
    assert len(writes) == 2
    for params in writes:
        conditions = json.loads(params[3])
        assert conditions["acceptance_provenance"]["original_decision_at"] == {
            "state": "UNKNOWN",
            "value": None,
        }
        assert conditions["acceptance_provenance"]["ledger_recorded_at"] == stamp
        assert params[5] == stamp


def test_changed_definition_cannot_reuse_accepted_revision_id():
    packet, acceptance = accepted_record()
    packet["metadata_proposals"][0]["definition"] += " changed"
    with pytest.raises(ValueError, match="ACCEPTANCE_CONTENT_HASHES"):
        prepare_recorded_acceptance(packet, acceptance, recorded_at=datetime.now(UTC).isoformat())


def test_recording_rejects_invented_original_time_before_any_write():
    packet, acceptance = accepted_record()
    record = prepare_recorded_acceptance(
        packet, acceptance, recorded_at=datetime.now(UTC).isoformat()
    )
    record["acceptance_provenance"]["original_decision_at"] = {
        "state": "KNOWN",
        "value": record["reviewed_at"],
    }
    cursor = Cursor("OH_LYME_DEV_OWNER", registered=True)
    with pytest.raises(ValueError, match="ACCEPTANCE_PROVENANCE"):
        record_steward_decision(cursor, record)
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


def test_inspection_is_read_only_and_retained_corruption_blocks_registration():
    cursor = Cursor()
    assert len(inspect_retained_inputs(cursor)) == 2
    assert all(sql.startswith("SELECT") for sql, _ in cursor.statements)
    cursor.corrupt = True
    with pytest.raises(ValueError, match="RETAINED_ARTIFACT"):
        register_pending_inputs(cursor)
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


def test_pending_registration_has_no_approval_activation_or_grant_and_reuses_existing():
    cursor = Cursor()
    ids = register_pending_inputs(cursor)
    assert len(set(ids)) == 2
    writes = [(sql, params) for sql, params in cursor.statements if sql.startswith("INSERT")]
    assert len(writes) == 6
    version_writes = [sql for sql, _ in writes if "DATA_SOURCE_VERSIONS" in sql]
    assert all("'PENDING',NULL" in sql for sql in version_writes)
    assert all("MANUAL_REVIEW_DECISIONS" not in sql and "GRANT" not in sql for sql, _ in writes)
    assert all("FALSE" in sql for sql, _ in writes if "CATALOG_RESOURCES" in sql)
    existing = Cursor(registered=True)
    register_pending_inputs(existing)
    assert not any(sql.startswith("INSERT") for sql, _ in existing.statements)


@pytest.mark.parametrize("role", ["OH_LYME_DEV_READ", "OH_LYME_DEV_RUNTIME", "ACCOUNTADMIN"])
def test_only_existing_owner_can_record_actual_steward_decision(role):
    cursor = Cursor(role, registered=True)
    with pytest.raises(ValueError, match="REVIEW_IDENTITY"):
        record_steward_decision(cursor, decision())
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


def test_generic_product_approval_and_wrong_revisions_cannot_approve_source():
    cursor = Cursor("OH_LYME_DEV_OWNER", registered=True)
    with pytest.raises(ValueError, match="STEWARD_DECISION_FIELDS"):
        record_steward_decision(cursor, {"product_approval": True})
    actual = decision()
    actual["accepted_metadata_revisions"][0] = "metadata-revision:v1:" + "f" * 64
    with pytest.raises(ValueError, match="STEWARD_EXACT_DEFINITIONS"):
        record_steward_decision(cursor, actual)
    assert not any(sql.startswith("INSERT") for sql, _ in cursor.statements)


def test_conflicting_catalog_identity_is_not_replaced():
    cursor = Cursor()
    cursor.conflict = True
    with pytest.raises(ValueError, match="CATALOG_RESOURCE_CONFLICT"):
        register_pending_inputs(cursor)
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cursor.statements)


def test_review_is_atomic_append_only_and_rollback_covers_second_input_failure():
    cursor = Cursor("OH_LYME_DEV_OWNER", registered=True)
    connection = Connection(cursor)
    ids = reconcile(connection, phase="record-steward", decision=decision())
    assert len(set(ids)) == 2 and connection.committed
    assert not any(sql.startswith(("UPDATE", "GRANT", "CALL")) for sql, _ in cursor.statements)
    cursor = Cursor("OH_LYME_DEV_OWNER", registered=True)
    cursor.fail_second_review = True
    connection = Connection(cursor)
    with pytest.raises(RuntimeError):
        reconcile(connection, phase="record-steward", decision=decision())
    assert connection.rolled_back and not connection.committed


def test_inspect_never_commits():
    connection = Connection(Cursor())
    reconcile(connection, phase="inspect")
    assert connection.rolled_back and not connection.committed


@pytest.mark.parametrize("phase", ["register-pending", "record-steward"])
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("resource_url", "https://example.org/wrong", "CATALOG_RESOURCE_URL_CONFLICT"),
        ("canonical_url", "https://example.org/wrong", "CATALOG_RESOURCE_URL_CONFLICT"),
        ("dataset_key", "unrelated-dataset", "CATALOG_RESOURCE_DATASET_CONFLICT"),
        ("dataset_key", None, "CATALOG_RESOURCE_DATASET_CONFLICT"),
    ],
)
def test_existing_key_cannot_bind_wrong_urls_dataset_or_orphan(phase, field, value, code):
    role = "OH_LYME_DEV_OWNER" if phase == "record-steward" else "OH_LYME_DEV_RUNTIME"
    cursor = Cursor(role, registered=True)
    setattr(cursor, field, value)
    connection = Connection(cursor)
    with pytest.raises(ValueError, match=code):
        reconcile(connection, phase=phase, decision=decision())
    assert connection.rolled_back and not connection.committed
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cursor.statements)
