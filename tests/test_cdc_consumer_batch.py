"""Synthetic admission only; SQL semantics are separately checked read-only."""

import copy
import json
from dataclasses import asdict

import pytest
import test_cdc_consumer_runtime as donor_tests
from test_cdc_consumer_admission import REGISTRY
from test_cdc_current_release import target_case

from lyme_gap_atlas_data import cdc_consumer_batch as batch
from lyme_gap_atlas_data.cdc_consumer_admission import RELEASE_ID, TARGET_RELEASE_ID
from lyme_gap_atlas_data.cdc_consumer_runtime import (
    AUTHORITY_SQL,
    IDENTITY_SQL,
    CDCConsumerUnavailable,
    _inputs,
    _project,
)
from lyme_gap_atlas_data.semantic_source_mappings import map_record

IDENTITY = {
    "USER": "SYNTHETIC",
    "ROLE": "OH_LYME_PROD_READ",
    "DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
    "WAREHOUSE": "COMPUTE_WH",
}


def envelope(rows):
    shared = {k: copy.deepcopy(rows[0]["cdc_runtime_authority"][k]) for k in batch._SHARED}
    records = copy.deepcopy(rows)
    consistent = all(
        {k: r["cdc_runtime_authority"][k] for k in batch._SHARED} == shared for r in rows
    )
    for row in records:
        for key in batch._SHARED:
            row["cdc_runtime_authority"].pop(key)
    return {"shared_authority": shared, "shared_consistent": consistent, "records": records}


@pytest.fixture
def batch_case(tmp_path):
    def build(count=2, measure="scapularis_status", value="Reported", release=TARGET_RELEASE_ID):
        runtime = donor_tests.runtime_case.__wrapped__(tmp_path)
        rows = []
        bindings = {}
        for i in range(count):
            if release == TARGET_RELEASE_ID:
                _, row, metadata, root = target_case(runtime, measure, value)
            else:
                _, row, metadata, root = runtime(measure, value)
            facts = row["cdc_runtime_authority"]
            packet = facts["review_decisions"][0]["conditions"][0]["cdc_consumer_admission"]
            binding = next(iter(packet["observation_bindings"].values()))
            row["observation_id"] += f"-{i}"
            row["county_fips"] = f"{i + 1:05d}"
            facts["record_county"] = row["county_fips"]
            for field in (
                "conformed_record_id",
                "governed_source_record_id",
                "semantic_source_record_id",
            ):
                row[field] += f"-{i}"
            binding["record_id"] = row["conformed_record_id"]
            packet["observation_bindings"] = {row["observation_id"]: binding}
            record, authority = _inputs(row, metadata)
            record.pop("release")
            authority["releases"] = {}
            binding["semantic_revision_id"] = map_record(record, metadata, authority, REGISTRY)[
                "observation"
            ]["revision_id"]
            bindings.update(packet["observation_bindings"])
            rows.append(row)
        reviews = copy.deepcopy(rows[0]["cdc_runtime_authority"]["review_decisions"])
        reviews[0]["conditions"][0]["cdc_consumer_admission"]["observation_bindings"] = bindings
        for row in rows:
            row["cdc_runtime_authority"]["review_decisions"] = copy.deepcopy(reviews)
        return rows, metadata, root

    return build


def query_for(rows, calls=None, payload=None):
    def query(sql, params):
        if calls is not None:
            calls.append((sql, params))
        if sql == IDENTITY_SQL:
            return [copy.deepcopy(IDENTITY)]
        return [
            {"BATCH_AUTHORITY": copy.deepcopy(payload if payload is not None else envelope(rows))}
        ]

    return query


@pytest.mark.parametrize("release", [RELEASE_ID, TARGET_RELEASE_ID])
@pytest.mark.parametrize("count", [1, 2, 5, 10, 50])
@pytest.mark.parametrize(
    "measure,value,state",
    [
        ("scapularis_status", "Established", "established"),
        ("scapularis_status", "Reported", "detected"),
        ("burgdorferi_status", "Present", "detected"),
        ("burgdorferi_status", "No records", "unknown"),
    ],
)
def test_exact_singleton_parity_and_query_counts(batch_case, release, count, measure, value, state):
    rows, _, root = batch_case(count, measure, value, release)
    requested = tuple(r["county_fips"] for r in reversed(rows))
    calls = []
    before = copy.deepcopy(rows)
    result = batch._project_batch(query_for(rows, calls), root, measure, requested, "prod", release)

    def singleton_query(sql, params):
        if sql == IDENTITY_SQL:
            return [IDENTITY]
        assert sql == AUTHORITY_SQL
        return [copy.deepcopy(next(r for r in rows if r["county_fips"] == params[2]))]

    expected = tuple(
        _project(singleton_query, root, measure, c, "prod", release_id=release) for c in requested
    )
    assert result.observations == expected
    assert result.county_fips == requested
    assert result.contract_version == batch.CONTRACT_VERSION
    assert len(calls) == 2
    assert calls[1][1] == (release, measure, rows[0]["source_version_id"], *requested)
    assert all(x["surveillance_evidence"]["normalized_state"] == state for x in result.observations)
    assert rows == before
    safe = json.dumps(asdict(result))
    for forbidden in (
        "shared_authority",
        "review_decisions",
        "attestations",
        "observation_bindings",
        "donor_observation_id",
        "artifact_id",
        "conformed_record_id",
        "synthetic-evidence-run",
    ):
        assert forbidden not in safe


@pytest.mark.parametrize(
    "counties",
    [
        [],
        ["00001"] * 2,
        ["00001"] * 51,
        "00001",
        ["1"],
        ["00001' OR TRUE"],
        ["000001"],
        ["１２３４５"],
        [None],
        None,
        {"00001"},
        (str(i) for i in range(100)),
    ],
)
def test_bad_input_has_no_sql(batch_case, counties):
    rows, _, root = batch_case()
    calls = []
    with pytest.raises(CDCConsumerUnavailable):
        batch._project_batch(
            query_for(rows, calls), root, "scapularis_status", counties, "prod", TARGET_RELEASE_ID
        )
    assert not calls


@pytest.mark.parametrize(
    "tamper",
    [
        "missing",
        "duplicate",
        "extra",
        "duplicate_observation",
        "wrong_county",
        "wrong_release",
        "wrong_source",
        "wrong_bundle",
        "wrong_measure",
        "inconsistent",
        "null_shared",
        "bad_records",
        "bad_facts",
        "embedded_proof",
        "missing_field",
        "extra_field",
    ],
)
def test_malformed_envelope_fails_whole_batch(batch_case, tamper):
    rows, _, root = batch_case()
    value = envelope(rows)
    records = value["records"]
    if tamper == "missing":
        records.pop()
    elif tamper == "duplicate":
        records[1] = copy.deepcopy(records[0])
    elif tamper == "extra":
        records.append(copy.deepcopy(records[0]))
    elif tamper == "duplicate_observation":
        records[1]["observation_id"] = records[0]["observation_id"]
    elif tamper.startswith("wrong_"):
        field = {
            "county": "county_fips",
            "release": "release_id",
            "source": "source_version_id",
            "bundle": "release_bundle_sha256",
            "measure": "measure_id",
        }[tamper[6:]]
        records[1][field] = "wrong"
    elif tamper == "inconsistent":
        value["shared_consistent"] = False
    elif tamper == "null_shared":
        value["shared_authority"]["attestations"] = None
    elif tamper == "bad_records":
        value["records"] = {}
    elif tamper == "bad_facts":
        records[1]["cdc_runtime_authority"] = None
    elif tamper == "embedded_proof":
        records[1]["cdc_runtime_authority"]["review_decisions"] = []
    elif tamper == "missing_field":
        records[1].pop("semantic_source_row_hash")
    else:
        records[1]["private_extra"] = "not accepted"
    with pytest.raises((CDCConsumerUnavailable, ValueError)):
        batch._project_batch(
            query_for(rows, payload=value),
            root,
            "scapularis_status",
            [r["county_fips"] for r in rows],
            "prod",
            TARGET_RELEASE_ID,
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "source_retired_at",
        "source_status",
        "evidence_status",
        "derivation_mode",
        "value",
        "publisher_value",
        "coverage_state",
        "workbook_sha256",
        "donor_record_equivalent",
        "donor_observation_id",
        "active_steward",
        "reviewer",
        "metadata_revision_id",
        "record_id",
        "semantic_revision_id",
        "receipt",
        "release_status",
        "row_hash",
    ],
)
def test_second_county_invalid_authority_cannot_return_partial(batch_case, tamper):
    rows, _, root = batch_case()
    facts = rows[1]["cdc_runtime_authority"]
    if tamper in {
        "active_steward",
        "reviewer",
        "metadata_revision_id",
        "record_id",
        "semantic_revision_id",
        "receipt",
    }:
        for row in rows:
            review = row["cdc_runtime_authority"]["review_decisions"][0]
            packet = review["conditions"][0]["cdc_consumer_admission"]
            if tamper in {"active_steward", "reviewer"}:
                review[tamper] = False if tamper == "active_steward" else ""
            elif tamper == "metadata_revision_id":
                packet[tamper] = "wrong"
            elif tamper == "receipt":
                packet["restricted_copy_reuse"]["attestation_ids"] = ["invented"]
            else:
                packet["observation_bindings"][rows[1]["observation_id"]][tamper] = "wrong"
    elif tamper == "row_hash":
        rows[1]["governed_source_row_hash"] = "f" * 64
    else:
        facts[tamper] = {
            "coverage_state": "UNKNOWN_SOURCE_COVERAGE",
            "donor_record_equivalent": False,
        }.get(tamper, "wrong")
    with pytest.raises(ValueError):
        batch._project_batch(
            query_for(rows),
            root,
            "scapularis_status",
            [r["county_fips"] for r in rows],
            "prod",
            TARGET_RELEASE_ID,
        )


def test_public_entry_sanitizes_driver_and_validation_errors(batch_case, monkeypatch):
    rows, _, root = batch_case()
    monkeypatch.setattr(batch, "_resources", lambda: root)
    result = batch.produce_cdc_batch_v1(query_for(rows), "scapularis_status", ["00001", "00002"])
    assert len(result.observations) == 2

    def fail(sql, params):
        raise RuntimeError("private workbook contents and credentials")

    with pytest.raises(CDCConsumerUnavailable) as error:
        batch.produce_cdc_batch_v1(fail, "scapularis_status", ["00001"])
    assert "private workbook" not in str(error.value)
    assert error.value.__suppress_context__

    def cancel(sql, params):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        batch.produce_cdc_batch_v1(cancel, "scapularis_status", ["00001"])


@pytest.mark.parametrize("field", ["USER", "ROLE", "DATABASE", "WAREHOUSE"])
def test_identity_rejection_before_authority(batch_case, field):
    _, _, root = batch_case()
    calls = []

    def query(sql, params):
        calls.append(sql)
        return [{**IDENTITY, field: ""}]

    with pytest.raises(CDCConsumerUnavailable):
        batch._project_batch(query, root, "scapularis_status", ["00001"], "prod", TARGET_RELEASE_ID)
    assert calls == [IDENTITY_SQL]


def test_sql_bounds_and_parameterization():
    sql = batch._authority_sql(50)
    assert sql.count("%s") == 53
    assert "PARTITION BY county_fips" in sql and "<= 2" in sql
    assert "COALESCE(shared=shared_anchor, FALSE)" in sql
    assert "FIRST_VALUE(shared)" in sql
    assert "OBJECT_DELETE(cdc_runtime_authority" in sql
    assert "FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V" in sql
    for forbidden in ("CONFORMED.", "GOVERNANCE.", "ALTER ", "CREATE ", "GRANT ", "UPDATE "):
        assert forbidden not in sql


def test_json_envelope_and_transport_bound(batch_case, monkeypatch):
    rows, _, root = batch_case()
    value = json.dumps(envelope(rows))
    query = query_for(rows, payload=value)
    assert (
        len(
            batch._project_batch(
                query, root, "scapularis_status", ["00001", "00002"], "prod", TARGET_RELEASE_ID
            ).observations
        )
        == 2
    )
    monkeypatch.setattr(batch, "MAX_ENVELOPE_BYTES", 20)
    with pytest.raises(CDCConsumerUnavailable):
        batch._project_batch(
            query, root, "scapularis_status", ["00001", "00002"], "prod", TARGET_RELEASE_ID
        )
