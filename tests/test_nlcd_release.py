"""The MRLC release extension uses real capture identity and keeps the baseline frozen."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lyme_gap_atlas_data import nlcd_release as nlcd
from lyme_gap_atlas_data.ingestion.adapters import _normalized_record
from lyme_gap_atlas_data.ingestion.identity import (
    canonical_source_row,
    deterministic_record_id,
    source_row_hash,
)
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.source_evidence import _definition_payload

ROOT = Path(__file__).resolve().parents[1]


def extension() -> dict[str, Any]:
    return {
        "contract_version": nlcd.CONTRACT,
        "artifact_sha256": nlcd.SHA,
        "resource_key": nlcd.RESOURCE,
        "source_key": nlcd.SOURCE_KEY,
        "source_version_id": "00000000-0000-4000-8000-000000000001",
        "source_decision_id": "00000000-0000-4000-8000-000000000002",
        "ingestion_run_id": "00000000-0000-4000-8000-000000000003",
        "artifact_id": "actual-artifact-receipt",
        "definition_version": 1,
        "row_count": 14,
        "review_evidence": {
            "commit": "a" * 40,
            "url": "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/610#pullrequestreview-123",
            "reviewer": "independent fixture reviewer",
        },
    }


class Ledger:
    def __init__(self) -> None:
        self.scope = extension()
        self.current: list[tuple[Any, ...]] = []
        self.approval = [("CONDITIONAL", self.scope["source_decision_id"], None)]
        self.quality = (2, 0)
        self.captures = []
        for record in nlcd.retained_envelope()["records"]:
            record_id = deterministic_record_id(nlcd.RESOURCE, 1, record)
            normalized = _normalized_record(nlcd.retained_definition(), record)
            source_hash = source_row_hash(record)
            normalized_hash = hashlib.sha256(canonical_source_row(normalized).encode()).hexdigest()
            capture_id = hashlib.sha256(
                f"capture:{self.scope['ingestion_run_id']}:{record_id}".encode()
            ).hexdigest()
            revision = hashlib.sha256(
                f"record-revision:{record_id}:{nlcd.SHA}:{source_hash}:{normalized_hash}:{nlcd.TRANSFORM}".encode()
            ).hexdigest()
            self.captures.append(
                (
                    capture_id,
                    revision,
                    record_id,
                    source_hash,
                    normalized_hash,
                    nlcd.TRANSFORM,
                    normalized,
                    datetime(2026, 10, 6, tzinfo=UTC),
                )
            )

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        assert sql.count("%s") == len(params)
        if "DATA_SOURCE_VERSIONS" in sql:
            self.current = self.approval
        elif "INGESTION_RUNS" in sql:
            self.current = [(nlcd.RESOURCE, "COMPLETED")]
        elif "RAW_ARTIFACTS" in sql:
            self.current = [(nlcd.SHA, 29058)]
        elif "DATA_QUALITY_RESULTS" in sql:
            self.current = [self.quality]
        elif "GOVERNED_SOURCE_RECORD_REVISIONS" in sql:
            self.current = self.captures
        elif "SEMANTIC_DATA_SOURCES" in sql:
            self.current = [
                (
                    nlcd.RESOURCE,
                    "mrlc_annual_nlcd_derived_county_aggregates",
                    "annual-nlcd-c1v2-2025-reviewed-demo-cohort",
                    "C1V2-2025",
                    self.scope["source_version_id"],
                    self.scope["ingestion_run_id"],
                    self.scope["artifact_id"],
                )
            ]
        elif "SEMANTIC_OBSERVATIONS" in sql:
            planned = nlcd.observation_rows(
                "release", self.scope, nlcd.verify_extension(Ledger(), self.scope)
            )
            self.current = [(*row[:10], json.loads(row[10]), *row[11:]) for row in planned]
        else:
            raise AssertionError(sql)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.current

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.current[0] if self.current else None


def test_unchanged_seven_measure_values_and_zero_map_to_existing_semantic_storage() -> None:
    ledger = Ledger()
    captures = nlcd.verify_extension(ledger, ledger.scope)
    observations = nlcd.observation_rows("release", ledger.scope, captures)
    assert len(observations) == len({row[0] for row in observations}) == 14
    expected = {
        (r["county_fips"], nlcd.MEASURES[r["measure"]]): r["value"]
        for r in nlcd.retained_envelope()["records"]
    }
    assert {(row[3], row[2]): json.loads(row[10]) for row in observations} == expected
    zero = next(
        row
        for row in observations
        if row[3] == "51013" and row[2] == nlcd.MEASURES["AGRICULTURE_AREA_SHARE"]
    )
    assert json.loads(zero[10]) == 0 and zero[11] == "ZERO"
    assert {row[14] for row in observations} == {"2025"}
    assert {row[15] for row in observations} == {"atlas-annual-nlcd-mrlc-local-county/1"}
    assert (
        nlcd.verify_persisted_extension(
            ledger, "release", manifest={"nlcd_extension": ledger.scope}
        )
        == 14
    )


@pytest.mark.parametrize(
    "failure", ["unapproved", "quality", "missing", "duplicate", "hash", "payload", "revision"]
)
def test_publication_rejects_invalid_or_changed_immutable_capture(failure: str) -> None:
    ledger = Ledger()
    if failure == "unapproved":
        ledger.approval = [("PENDING", None, None)]
    elif failure == "quality":
        ledger.quality = (2, 1)
    elif failure == "missing":
        ledger.captures.pop()
    elif failure == "duplicate":
        ledger.captures[1] = ledger.captures[0]
    else:
        row = list(ledger.captures[0])
        if failure == "hash":
            row[4] = "0" * 64
        elif failure == "revision":
            row[1] = "0" * 64
        else:
            row[6] = copy.deepcopy(row[6])
            row[6]["record"]["value"] = 0.123  # All recorded hashes deliberately unchanged.
        ledger.captures[0] = tuple(row)
    with pytest.raises(ValueError, match="NLCD_"):
        nlcd.verify_extension(ledger, ledger.scope)


def test_reviewed_evidence_contains_the_exact_admission_pins() -> None:
    definition = load_source_definition(
        ROOT / "config/sources/mrlc_annual_nlcd_c1v2_2025_demo_cohort.yml"
    )
    evidence = _definition_payload(definition)
    assert evidence["aggregate_artifact_sha256"] == nlcd.SHA
    assert evidence["county_fips"] == ["09110", "51013"]
    assert evidence["maximum_rows"] == 14
    assert evidence["calculation_code_revision"] == "a1dca40aa049f5c8db4c819f20230843bc8041cf"


def test_baseline_release_counts_and_grants_are_not_relaxed() -> None:
    from lyme_gap_atlas_data.migrations import load_migrations, migration_execution_role

    release = (ROOT / "src/lyme_gap_atlas_data/semantic_release.py").read_text()
    assert "source_key<>'context_nlcd_2025'" in release
    assert "EXPECTED_COUNTIES * EXPECTED_OBSERVATIONS_PER_COUNTY" in release
    for version in ("V138", "V139"):
        migration = next(m for m in load_migrations(ROOT / "migrations") if m.version == version)
        assert "COPY GRANTS" in migration.source
        assert "\nGRANT " not in migration.source
        assert (
            migration_execution_role(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
            == "OH_LYME_PROD_OWNER"
        )
