"""Synthetic target authority; never claims retained PROD admission."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_cdc_consumer_runtime as donor_tests
from test_cdc_consumer_admission import REGISTRY
from test_semantic_governance import _ReleaseConnection

from lyme_gap_atlas_data import semantic_release
from lyme_gap_atlas_data.cdc_consumer_admission import (
    BUNDLE_SHA256,
    RELEASE_ID,
    SLICES,
    TARGET_BUNDLE_SHA256,
    TARGET_RELEASE_ID,
)
from lyme_gap_atlas_data.cdc_consumer_runtime import (
    AUTHORITY_SQL,
    CDCConsumerUnavailable,
    _inputs,
    _metadata,
    _project,
)
from lyme_gap_atlas_data.cdc_promotion import (
    CDCPromotionBlocked,
    _withdrawal_approved,
    validate_candidate_rows,
    verify_cdc_candidate,
)
from lyme_gap_atlas_data.semantic_source_mappings import map_record

PACKAGE = Path(__file__).parents[1] / "docs/contracts/semantic-domain/cdc-2025"


@pytest.fixture
def runtime_case(tmp_path):
    return donor_tests.runtime_case.__wrapped__(tmp_path)


def target_case(runtime_case, measure="scapularis_status", value="Reported"):
    original_query, row, _, root = runtime_case(measure, value)
    for file in ("release-binding-2026-10-15.json", f"{measure}.revision-3.metadata.json"):
        (root / file).write_bytes((PACKAGE / file).read_bytes())
    metadata = _metadata(root, measure, TARGET_RELEASE_ID)
    row["release_id"] = TARGET_RELEASE_ID
    row["release_bundle_sha256"] = TARGET_BUNDLE_SHA256
    facts = row["cdc_runtime_authority"]
    donor_id = row["observation_id"]
    row["observation_id"] = "synthetic-target-observation"
    facts.update(donor_record_equivalent=True, donor_observation_id=donor_id)
    packet = facts["review_decisions"][0]["conditions"][0]["cdc_consumer_admission"]
    old_binding = packet["observation_bindings"][donor_id]
    packet.update(
        release_id=TARGET_RELEASE_ID,
        bundle_sha256=TARGET_BUNDLE_SHA256,
        metadata_revision_id=metadata["revision_id"],
        reviewed_at="2026-10-17",
        observation_bindings={
            row["observation_id"]: dict(old_binding, donor_observation_id=donor_id)
        },
        restricted_copy_reuse={
            "donor_release_id": RELEASE_ID,
            "donor_bundle_sha256": BUNDLE_SHA256,
            "attestation_ids": [a["attestation_id"] for a in facts["attestations"]],
        },
    )
    facts["review_decisions"][0]["decided_at"] = "2026-10-17"
    record, authority = _inputs(row, metadata)
    record.pop("release")
    authority["releases"] = {}
    revision = map_record(record, metadata, authority, REGISTRY)["observation"]["revision_id"]
    packet["observation_bindings"][row["observation_id"]]["semantic_revision_id"] = revision

    def query(sql, params):
        if sql == AUTHORITY_SQL:
            assert params == (
                TARGET_RELEASE_ID,
                measure,
                "13081",
                SLICES[measure]["source_version_id"],
            )
            return [copy.deepcopy(row)]
        return original_query(sql, params)

    return query, row, metadata, root


@pytest.mark.parametrize(
    "measure,value,normalized",
    [
        ("scapularis_status", "Established", "established"),
        ("scapularis_status", "Reported", "detected"),
        ("burgdorferi_status", "Present", "detected"),
        ("burgdorferi_status", "No records", "unknown"),
    ],
)
def test_target_projection_retains_values_and_real_donor_receipt(
    runtime_case, measure, value, normalized
):
    query, row, _, root = target_case(runtime_case, measure, value)
    result = _project(query, root, measure, "13081", "prod", release_id=TARGET_RELEASE_ID)
    assert result["semantic"]["release"]["id"] == TARGET_RELEASE_ID
    assert result["semantic"]["observation"]["value"] == value
    assert result["surveillance_evidence"]["normalized_state"] == normalized
    assert all(
        a["semantic_release_id"] == RELEASE_ID for a in row["cdc_runtime_authority"]["attestations"]
    )
    public = json.dumps(result)
    for forbidden in (
        "attestation_ids",
        "observation_bindings",
        "donor_record_equivalent",
        "donor_observation_id",
    ):
        assert forbidden not in public


@pytest.mark.parametrize(
    "tamper",
    ["receipt", "donor", "link", "metadata", "record", "revision", "review", "status", "source"],
)
def test_target_fails_closed_without_exact_authority(runtime_case, tamper):
    query, row, _, root = target_case(runtime_case)
    facts = row["cdc_runtime_authority"]
    packet = facts["review_decisions"][0]["conditions"][0]["cdc_consumer_admission"]
    binding = packet["observation_bindings"][row["observation_id"]]
    if tamper == "receipt":
        packet["restricted_copy_reuse"]["attestation_ids"] = ["invented"]
    elif tamper == "donor":
        facts["donor_record_equivalent"] = False
    elif tamper == "link":
        binding["donor_observation_id"] = "unrelated"
    elif tamper == "metadata":
        packet["metadata_revision_id"] = "wrong"
    elif tamper in {"record", "revision"}:
        binding["record_id" if tamper == "record" else "semantic_revision_id"] = "wrong"
    elif tamper == "review":
        facts["review_decisions"][0]["active_steward"] = False
    elif tamper == "status":
        facts["release_status"] = "CANDIDATE"
    else:
        row["source_version_id"] = "wrong"
    with pytest.raises(ValueError):
        _project(query, root, "scapularis_status", "13081", "prod", release_id=TARGET_RELEASE_ID)


def test_candidate_validates_actual_lifecycle_without_serving(runtime_case):
    query, row, metadata, root = target_case(runtime_case)
    row["cdc_runtime_authority"]["release_status"] = "CANDIDATE"
    assert validate_candidate_rows([row], metadata, REGISTRY, {"13081"}, TARGET_RELEASE_ID) == 1
    with pytest.raises(CDCConsumerUnavailable):
        _project(query, root, "scapularis_status", "13081", "prod", release_id=TARGET_RELEASE_ID)
    assert row["cdc_runtime_authority"]["release_status"] == "CANDIDATE"


@pytest.mark.parametrize(
    "case", ["missing", "duplicate", "same_count_different_county", "bad_record", "wrong_lifecycle"]
)
def test_candidate_rejects_membership_loss_and_bad_authority(runtime_case, case):
    _, row, metadata, _ = target_case(runtime_case)
    row["cdc_runtime_authority"]["release_status"] = "CANDIDATE"
    rows = [row]
    expected = {"13081"}
    if case == "missing":
        rows = []
    elif case == "duplicate":
        rows = [row, row]
    elif case == "same_count_different_county":
        expected = {"06001"}
    elif case == "bad_record":
        row["conformed_record_id"] = "wrong"
    else:
        row["cdc_runtime_authority"]["release_status"] = "PUBLISHED"
    with pytest.raises(CDCPromotionBlocked):
        validate_candidate_rows(rows, metadata, REGISTRY, expected, TARGET_RELEASE_ID)


def test_new_release_binding_required_before_any_candidate_io():
    class NoIO:
        def execute(self, *args):
            raise AssertionError("must reject before candidate queries")

    with pytest.raises(CDCPromotionBlocked):
        verify_cdc_candidate(NoIO(), "unreviewed-next-release", "a" * 64, TARGET_RELEASE_ID)


def test_intentional_removal_needs_packaged_contract_and_independent_review():
    configured = {
        "decision_id": "synthetic-removal",
        "decision_reference": "SYNTHETIC-OWNER-REVIEW",
    }
    review = dict(
        configured,
        active_steward=True,
        reviewer="SYNTHETIC",
        decided_at="2026-10-17",
        decision="APPROVED",
        conditions=[
            {
                "cdc_consumer_withdrawal": {
                    "release_id": TARGET_RELEASE_ID,
                    "bundle_sha256": TARGET_BUNDLE_SHA256,
                    "measure_id": "scapularis_status",
                    "decision_reference": configured["decision_reference"],
                }
            }
        ],
    )
    assert not _withdrawal_approved(None, [review], TARGET_RELEASE_ID, "scapularis_status")
    assert not _withdrawal_approved(configured, [], TARGET_RELEASE_ID, "scapularis_status")
    assert _withdrawal_approved(configured, [review], TARGET_RELEASE_ID, "scapularis_status")
    assert not _withdrawal_approved(
        configured, [review, review], TARGET_RELEASE_ID, "scapularis_status"
    )
    review["active_steward"] = False
    assert not _withdrawal_approved(configured, [review], TARGET_RELEASE_ID, "scapularis_status")


def test_cdc_gate_blocks_before_retirement_and_pointer_change(monkeypatch):
    connection = _ReleaseConnection(
        [
            ("CANDIDATE", "a" * 64),
            (3144, 3144, 44016),
            ("ONE_HEALTH_LYME_GAP_ATLAS_PROD",),
            (TARGET_RELEASE_ID,),
        ]
    )
    monkeypatch.setattr(semantic_release, "connect", lambda _: connection)
    monkeypatch.setattr(
        semantic_release, "_verify_restricted_final_copy_attestations", lambda *_: None
    )
    monkeypatch.setattr(semantic_release, "verify_persisted_extension", lambda *_, **__: None)
    with pytest.raises(semantic_release.SemanticReleaseBlocked, match="CDC consumer"):
        semantic_release.publish_semantic_release(
            SimpleNamespace(snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD"),
            "unreviewed-next-release",
            reason="synthetic regression",
        )
    assert connection.rolled_back and not connection.committed
    assert not any("UPDATE " in sql or "MERGE " in sql for sql in connection.sql.statements)


def test_real_signed_date_survives_later_registration(runtime_case):
    query, row, _, root = target_case(runtime_case)
    row["cdc_runtime_authority"]["review_decisions"][0]["decided_at"] = "2026-10-18"
    assert (
        _project(query, root, "scapularis_status", "13081", "prod", release_id=TARGET_RELEASE_ID)[
            "semantic"
        ]["release"]["id"]
        == TARGET_RELEASE_ID
    )
    row["cdc_runtime_authority"]["review_decisions"][0]["decided_at"] = "2026-10-16"
    with pytest.raises(ValueError):
        _project(query, root, "scapularis_status", "13081", "prod", release_id=TARGET_RELEASE_ID)


class CandidateCursor:
    """Exercise the complete SQL/read path, including deliberately invalid extra rows."""

    def __init__(self, store, raw_extra=None):
        self.store = store
        self.raw_extra = raw_extra
        self.statements = []
        self.buffer = []

    def execute(self, sql, params):
        self.statements.append(sql)
        rows = copy.deepcopy(self.store[(params[0], params[1])])
        if "FROM PRESENTATION.SEMANTIC_OBSERVATIONS" in sql:
            rows = [
                dict(
                    observation_id=r["observation_id"],
                    **r.get(
                        "persisted_interpretation",
                        {"value": "synthetic", "value_state": "REPORTED"},
                    ),
                )
                for r in rows
            ]
            if self.raw_extra and params[0] == TARGET_RELEASE_ID:
                rows.append(
                    {
                        "observation_id": "synthetic-hidden-orphan",
                        "value": None,
                        "value_state": "UNKNOWN",
                    }
                )
        elif sql == AUTHORITY_SQL:
            rows = [
                r
                for r in rows
                if r["county_fips"] == params[2] and r["source_version_id"] == params[3]
            ]
        else:
            assert "source_version_id=%s" not in sql and "record_match_kind=" not in sql
            for row in rows:
                facts = row["cdc_runtime_authority"]
                if isinstance(facts, dict):
                    facts.pop("review_decisions", None)
                    facts.pop("attestations", None)
        keys = list(rows[0]) if rows else list(next(iter(self.store.values()))[0])
        self.description = [(k.upper(),) for k in keys]
        self.buffer = [tuple(row[k] for k in keys) for row in rows]

    def fetchmany(self, size):
        batch, self.buffer = self.buffer[:size], self.buffer[size:]
        return batch


def promotion_case(runtime_case, monkeypatch):
    from lyme_gap_atlas_data import cdc_promotion

    store = {}
    for measure, value in (("scapularis_status", "Reported"), ("burgdorferi_status", "Present")):
        _, prior, _, root = runtime_case(measure, value)
        store[(RELEASE_ID, measure)] = [copy.deepcopy(prior)]
        _, candidate, _, root = target_case(runtime_case, measure, value)
        candidate["cdc_runtime_authority"]["release_status"] = "CANDIDATE"
        store[(TARGET_RELEASE_ID, measure)] = [candidate]
    monkeypatch.setattr(cdc_promotion, "_resources", lambda: root)
    return store


def test_full_candidate_read_path_validates_both_measures(runtime_case, monkeypatch):
    store = promotion_case(runtime_case, monkeypatch)
    cursor = CandidateCursor(store)
    assert verify_cdc_candidate(cursor, TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256, RELEASE_ID) == {
        "scapularis_status": 1,
        "burgdorferi_status": 1,
    }
    assert all(sql.startswith("SELECT") for sql in cursor.statements)


def test_raw_source_orphan_blocks_promotion(runtime_case, monkeypatch):
    store = promotion_case(runtime_case, monkeypatch)
    with pytest.raises(CDCPromotionBlocked, match="lineage omits"):
        verify_cdc_candidate(
            CandidateCursor(store, raw_extra=True),
            TARGET_RELEASE_ID,
            TARGET_BUNDLE_SHA256,
            RELEASE_ID,
        )


@pytest.mark.parametrize("changed", [False, True])
def test_excluded_interpretation_is_preserved(runtime_case, monkeypatch, changed):
    store = promotion_case(runtime_case, monkeypatch)
    for release in (RELEASE_ID, TARGET_RELEASE_ID):
        extra = copy.deepcopy(store[(release, "scapularis_status")][0])
        extra["observation_id"] = release + "-excluded"
        extra["county_fips"] = "06001"
        extra["record_match_kind"] = "UNMATCHED"
        extra["cdc_runtime_authority"] = None
        extra["persisted_interpretation"] = {"value": None, "value_state": "UNKNOWN"}
        if changed and release == TARGET_RELEASE_ID:
            extra["persisted_interpretation"]["value_state"] = "NEGATIVE"
        store[(release, "scapularis_status")].append(extra)
    if changed:
        with pytest.raises(CDCPromotionBlocked, match="excluded observation changed"):
            verify_cdc_candidate(
                CandidateCursor(store), TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256, RELEASE_ID
            )
    else:
        assert (
            verify_cdc_candidate(
                CandidateCursor(store), TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256, RELEASE_ID
            )["scapularis_status"]
            == 1
        )


@pytest.mark.parametrize(
    "case",
    [
        "extra_same_county",
        "extra_other_county",
        "unmatched_extra",
        "lost_predecessor_match",
        "lost_predecessor_row",
    ],
)
def test_complete_candidate_path_cannot_hide_invalid_rows(runtime_case, monkeypatch, case):
    store = promotion_case(runtime_case, monkeypatch)
    if case.startswith("lost_predecessor"):
        row = store[(RELEASE_ID, "scapularis_status")][0]
        if case == "lost_predecessor_match":
            row["record_match_kind"] = "UNMATCHED"
        else:
            row["observation_id"] = "replaced-predecessor-id"
    else:
        extra = copy.deepcopy(store[(TARGET_RELEASE_ID, "scapularis_status")][0])
        extra["observation_id"] = "synthetic-invalid-extra"
        if case != "extra_same_county":
            extra["county_fips"] = "06001"
        extra["source_version_id"] = "wrong-source"
        if case == "unmatched_extra":
            extra["record_match_kind"] = "UNMATCHED"
        store[(TARGET_RELEASE_ID, "scapularis_status")].append(extra)
    with pytest.raises(CDCPromotionBlocked):
        verify_cdc_candidate(
            CandidateCursor(store), TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256, RELEASE_ID
        )
