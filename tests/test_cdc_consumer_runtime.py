"""Synthetic retained decisions exercise runtime wiring, never PROD admission."""

import copy
import json
import shutil
from pathlib import Path

import pytest
from test_cdc_consumer_admission import PACKAGE, REGISTRY, controlled_case

from lyme_gap_atlas_data.cdc_consumer_admission import BUNDLE_SHA256, PERIOD, RELEASE_ID, SLICES
from lyme_gap_atlas_data.cdc_consumer_runtime import (
    AUTHORITY_SQL,
    PENDING_IDS,
    CDCConsumerUnavailable,
    _inputs,
    _metadata,
    _project,
)
from lyme_gap_atlas_data.semantic_source_mappings import map_record


@pytest.fixture
def runtime_case(tmp_path):
    def build(measure="scapularis_status", value="Reported", county="13081"):
        record, metadata, authority = controlled_case(measure, value)
        shutil.copyfile(PACKAGE / "release-binding.json", tmp_path / "release-binding.json")
        for name in SLICES:
            shutil.copyfile(PACKAGE / f"{name}.metadata.json", tmp_path / f"{name}.metadata.json")
        shutil.copyfile(
            PACKAGE.parent / "atlas-semantic-source-mappings-v1.json",
            tmp_path / "atlas-semantic-source-mappings-v1.json",
        )
        (tmp_path / f"{measure}.revision-2.metadata.json").write_text(json.dumps(metadata))
        edge = record["edges"][0]
        facts = {
            "source_vintage": f"through {PERIOD}",
            "source_status": "CONDITIONAL",
            "source_retired_at": None,
            "source_decision": "APPROVED_WITH_CONDITIONS",
            "source_decision_id": "test-source-review",
            "source_conditions": ["restricted"],
            "source_review_version": edge["source_version_id"],
            "source_review_resource": edge["resource_key"],
            "release_status": "PUBLISHED",
            "value": value,
            "publisher_value": value,
            "value_state": record["value_state"],
            "geography_semantics": "COUNTY_FIPS_5",
            "transformation_version": "semantic_county_assembly_v1",
            "derivation_status": "COMPLETED",
            "derivation_mode": "RESTRICTED_FULL_PROD",
            "evidence_run_id": "synthetic-evidence-run",
            "evidence_status": "COMPLETED",
            "evidence_mode": "EVIDENCE_ONLY",
            "evidence_resource": edge["resource_key"],
            "artifact_run_id": "synthetic-evidence-run",
            "artifact_type": "SOURCE_WORKBOOK_EVIDENCE",
            "source_definition_version": 1,
            "record_resource": edge["resource_key"],
            "record_county": county,
            "coverage_state": "OBSERVED",
            "workbook_sha256": edge["artifact_sha256"],
            "retrieved_at": record["retrieved_at"],
            "attestations": authority["releases"][RELEASE_ID][
                "restricted_source_publication_attestations"
            ],
        }
        row = dict(
            SLICES[measure],
            observation_id="test-physical-observation",
            release_id=RELEASE_ID,
            measure_id=measure,
            county_fips=county,
            temporal_window=f"through {PERIOD}",
            governed_source_version_id=edge["source_version_id"],
            ingestion_run_id=edge["ingestion_run_id"],
            governed_ingestion_run_id=edge["ingestion_run_id"],
            artifact_id=edge["artifact_id"],
            artifact_sha256=edge["artifact_sha256"],
            semantic_source_record_id=edge["source_record_id"],
            semantic_source_row_hash=edge["source_row_hash"],
            source_id=edge["source_id"],
            release_bundle_sha256=BUNDLE_SHA256,
            conformed_record_id=edge["record_id"],
            governed_source_record_id=edge["source_record_id"],
            governed_source_row_hash=edge["source_row_hash"],
            record_match_kind="RESTRICTED_CDC_CONFORMED",
            cdc_runtime_authority=facts,
        )
        packet = {
            "release_id": RELEASE_ID,
            "bundle_sha256": BUNDLE_SHA256,
            "scope": SLICES[measure],
            "metadata_revision_id": metadata["revision_id"],
            "decision_reference": "test-reviewed-decision",
            "observation_bindings": {
                row["observation_id"]: {
                    "record_id": edge["record_id"],
                    "semantic_revision_id": "placeholder",
                }
            },
        }
        facts["review_decisions"] = [
            {
                "decision_id": "test-scientific-review",
                "decision": "APPROVED",
                "reviewer": "SYNTHETIC_TEST_REVIEWER",
                "active_steward": True,
                "decided_at": "2026-10-11",
                "rationale": "synthetic review evidence only",
                "conditions": [{"cdc_consumer_admission": packet}],
            }
        ]
        mapped_record, snapshot = _inputs(row, metadata)
        mapped_record.pop("release")
        snapshot["releases"] = {}
        revision = map_record(mapped_record, metadata, snapshot, REGISTRY)["observation"][
            "revision_id"
        ]
        packet["observation_bindings"][row["observation_id"]]["semantic_revision_id"] = revision

        def query(sql, params):
            if sql == AUTHORITY_SQL:
                assert params == (RELEASE_ID, measure, county, edge["source_version_id"])
                return [copy.deepcopy(row)]
            assert not params
            return [
                {
                    "USER": "SYNTHETIC",
                    "ROLE": "OH_LYME_PROD_READ",
                    "DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                    "WAREHOUSE": "COMPUTE_WH",
                }
            ]

        return query, row, metadata, tmp_path

    return build


@pytest.mark.parametrize(
    "measure,value,county,state",
    [
        ("scapularis_status", "Established", "13081", "established"),
        ("scapularis_status", "Reported", "13081", "detected"),
        ("burgdorferi_status", "Present", "19135", "detected"),
        ("burgdorferi_status", "No records", "12047", "unknown"),
    ],
)
def test_runtime_writer_real_shape_synthetic_authority(runtime_case, measure, value, county, state):
    query, row, _, root = runtime_case(measure, value, county)
    result = _project(query, root, measure, county, "prod")
    assert result["surveillance_evidence"]["normalized_state"] == state
    assert result["semantic"]["observation"]["value"] == value
    assert result["semantic"]["release"] == {"id": RELEASE_ID, "bundle_sha256": BUNDLE_SHA256}
    text = json.dumps(result)
    for field in (
        "conformed_record_id",
        "ingestion_run_id",
        "artifact_id",
        "artifact_sha256",
        "governed_source_row_hash",
        "governed_source_record_id",
        "observation_id",
    ):
        assert row[field] not in text
    assert "synthetic-evidence-run" not in text
    assert "test-reviewed-decision" not in text


def test_packaged_pending_revision_fails_closed(runtime_case):
    query, _, metadata, root = runtime_case()
    shutil.copyfile(
        root / "scapularis_status.metadata.json",
        root / "scapularis_status.revision-2.metadata.json",
    )
    with pytest.raises(ValueError):
        _project(query, root, "scapularis_status", "13081", "prod")
    assert metadata["revision_id"] != PENDING_IDS["scapularis_status"]


@pytest.mark.parametrize(
    "tamper",
    [
        "reviewer",
        "decision_reference",
        "decided_at",
        "active_steward",
        "metadata",
        "scope",
        "release",
        "bundle",
        "observation",
        "record",
        "revision",
        "attestation",
        "evidence_run",
        "workbook",
        "row_hash",
        "source_version",
        "source_approval",
        "value",
        "placeholder",
        "geography_semantics",
        "transformation_version",
        "derivation_mode",
    ],
)
def test_runtime_authority_fail_closed(runtime_case, tamper):
    query, row, _, root = runtime_case()
    facts = row["cdc_runtime_authority"]
    review = facts["review_decisions"][0]
    packet = review["conditions"][0]["cdc_consumer_admission"]
    binding = packet["observation_bindings"][row["observation_id"]]
    if tamper in {"geography_semantics", "transformation_version", "derivation_mode"}:
        facts[tamper] = "wrong"
    elif tamper in {"reviewer", "decided_at", "active_steward"}:
        review.pop(tamper)
    elif tamper == "decision_reference":
        packet.pop(tamper)
    elif tamper == "metadata":
        packet["metadata_revision_id"] = "wrong"
    elif tamper == "scope":
        packet["scope"] = SLICES["burgdorferi_status"]
    elif tamper == "release":
        packet["release_id"] = "wrong"
    elif tamper == "bundle":
        packet["bundle_sha256"] = "f" * 64
    elif tamper == "observation":
        packet["observation_bindings"] = {}
    elif tamper == "record":
        binding["record_id"] = "wrong"
    elif tamper == "revision":
        binding["semantic_revision_id"] = "wrong"
    elif tamper == "attestation":
        facts["attestations"] = []
    elif tamper == "evidence_run":
        facts["evidence_run_id"] = row["ingestion_run_id"]
        facts["artifact_run_id"] = row["ingestion_run_id"]
    elif tamper == "workbook":
        facts["workbook_sha256"] = "f" * 64
    elif tamper == "row_hash":
        row["governed_source_row_hash"] = "f" * 64
    elif tamper == "source_version":
        row["governed_source_version_id"] = "wrong"
    elif tamper == "source_approval":
        facts["source_status"] = "REJECTED"
    elif tamper == "value":
        facts["publisher_value"] = "Established"
    elif tamper == "placeholder":
        facts["coverage_state"] = "UNKNOWN_SOURCE_COVERAGE"
    with pytest.raises(ValueError):
        _project(query, root, "scapularis_status", "13081", "prod")


def test_ambiguous_read_rejected(runtime_case):
    query, _, _, root = runtime_case()

    def duplicate(sql, params):
        rows = query(sql, params)
        return rows * 2 if sql == AUTHORITY_SQL else rows

    with pytest.raises(CDCConsumerUnavailable, match="exactly one"):
        _project(duplicate, root, "scapularis_status", "13081", "prod")


@pytest.mark.parametrize("county", ["13081' OR TRUE", "1", "000000"])
def test_unbounded_input_rejected(runtime_case, county):
    query, _, _, root = runtime_case()
    with pytest.raises(CDCConsumerUnavailable, match="unsupported"):
        _project(query, root, "scapularis_status", county, "prod")


def test_immutable_pending_identity_rejected(runtime_case):
    _, _, _, root = runtime_case()
    pending = json.loads((root / "scapularis_status.metadata.json").read_text())
    pending["label"] = "silent replacement"
    (root / "scapularis_status.metadata.json").write_text(json.dumps(pending))
    with pytest.raises(ValueError):
        _metadata(root, "scapularis_status")


def test_container_and_wheel_include_canonical_resources():
    root = Path(__file__).parents[1]
    assert (
        '"docs/contracts/semantic-domain/cdc-2025" = "lyme_gap_atlas_data/cdc_metadata"'
        in (root / "pyproject.toml").read_text()
    )
    assert "COPY docs/contracts/semantic-domain/cdc-2025" in (root / "Dockerfile").read_text()


def test_forward_view_retains_v148_and_reader_boundary():
    sql = (
        Path(__file__).parents[1] / "migrations/V149__cdc_runtime_reader_authority.sql"
    ).read_text()
    assert "SECURE VIEW LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V COPY GRANTS" in sql
    assert "GRANT " not in sql
    assert "UPDATE " not in sql
    assert "INSERT " not in sql
    assert "cdc_runtime_authority" in sql


@pytest.mark.parametrize("field", ["release_id", "bundle_sha256", "slices"])
def test_packaged_binding_scope_rejected(runtime_case, field):
    query, _, _, root = runtime_case()
    binding = json.loads((root / "release-binding.json").read_text())
    binding[field] = "wrong"
    (root / "release-binding.json").write_text(json.dumps(binding))
    with pytest.raises(CDCConsumerUnavailable, match="scope mismatch"):
        _project(query, root, "scapularis_status", "13081", "prod")


def test_duplicate_retained_reviews_rejected(runtime_case):
    query, row, _, root = runtime_case()
    row["cdc_runtime_authority"]["review_decisions"] *= 2
    with pytest.raises(CDCConsumerUnavailable, match="retained steward"):
        _project(query, root, "scapularis_status", "13081", "prod")


def test_unintended_reader_rejected(runtime_case):
    query, _, _, root = runtime_case()

    def elevated(sql, params):
        rows = query(sql, params)
        if sql != AUTHORITY_SQL:
            rows[0]["ROLE"] = "ACCOUNTADMIN"
        return rows

    with pytest.raises(CDCConsumerUnavailable, match="intended reader"):
        _project(elevated, root, "scapularis_status", "13081", "prod")


def test_named_operator_query_is_bounded_and_sanitized(runtime_case, monkeypatch):
    from types import SimpleNamespace

    from lyme_gap_atlas_data import cdc_consumer_runtime as runtime

    query, _, _, root = runtime_case()
    calls = []
    monkeypatch.setattr(runtime, "_resources", lambda: root)

    def run(command, **kwargs):
        calls.append(command)
        sql = command[-1]
        assert sql.startswith("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30; ")
        assert command[command.index("--connection") + 1] == "ATLAS_PROD_READ"
        assert command[command.index("--secondary-roles") + 1] == "NONE"
        assert kwargs["capture_output"] and kwargs["timeout"] == 60
        rows = (
            query(
                AUTHORITY_SQL,
                (
                    RELEASE_ID,
                    "scapularis_status",
                    "13081",
                    SLICES["scapularis_status"]["source_version_id"],
                ),
            )
            if "FROM LINEAGE_AUDIT" in sql
            else query("identity", ())
        )
        return SimpleNamespace(
            stdout=json.dumps([[{"status": "Statement executed successfully."}], rows])
        )

    monkeypatch.setattr(runtime.subprocess, "run", run)
    result = runtime.read_cdc_consumer_named("scapularis_status", "13081")
    assert result["surveillance_evidence"]["normalized_state"] == "detected"
    assert len(calls) == 2
    assert "LIMIT 2" in calls[-1][-1]
    assert "%s" not in calls[-1][-1]

    def denied(*args, **kwargs):
        raise RuntimeError("private workbook and source record diagnostic")

    monkeypatch.setattr(runtime.subprocess, "run", denied)
    with pytest.raises(CDCConsumerUnavailable, match="no fallback") as error:
        runtime.read_cdc_consumer_named("scapularis_status", "13081")
    assert "private workbook" not in str(error.value)


def test_cli_readback_failure_is_safe(monkeypatch):
    from typer.testing import CliRunner

    from lyme_gap_atlas_data import cli

    def reject(*args, **kwargs):
        raise CDCConsumerUnavailable("accepted CDC metadata resource unavailable")

    monkeypatch.setattr(cli, "read_cdc_consumer_named", reject)
    result = CliRunner().invoke(
        cli.app, ["pipeline", "cdc-consumer-readback", "scapularis_status", "13081"]
    )
    assert result.exit_code == 1
    assert result.output.strip() == "accepted CDC metadata resource unavailable"


@pytest.mark.parametrize("measure", tuple(SLICES))
def test_supplied_reviewed_revision_is_packaged_and_immutable(measure):
    """Real metadata approval is not sufficient without retained runtime authority."""
    from lyme_gap_atlas_data.cdc_consumer_runtime import _resources
    from lyme_gap_atlas_data.semantic_metadata import validate_metadata_revisions

    root = _resources()
    pending = json.loads(root.joinpath(f"{measure}.metadata.json").read_text())
    accepted = _metadata(root, measure)
    validate_metadata_revisions([pending, accepted])
    assert pending["revision_id"] == PENDING_IDS[measure]
    assert pending["steward_review"]["state"] == "PENDING"
    assert accepted["meaning_signature"] == pending["meaning_signature"]
    assert accepted["steward_review"]["reviewed_at"]["value"] == "2026-10-11"
    assert set(accepted["authority"].values()) == {"STEWARD_REVIEWED"}
    assert accepted["provenance"] == pending["provenance"]
