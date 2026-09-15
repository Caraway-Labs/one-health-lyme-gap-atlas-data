"""Contract checks for the frozen Alpha parity manifest (#270)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO / "docs" / "contracts" / "alpha-parity"
MANIFEST = BASELINE_DIR / "alpha-2026-08-06-baseline.json"
CHECKSUM = BASELINE_DIR / "alpha-2026-08-06-baseline.sha256"


def test_alpha_baseline_is_checksum_bound_and_metadata_only() -> None:
    manifest_bytes = MANIFEST.read_bytes()
    expected = CHECKSUM.read_text(encoding="utf-8").strip()
    assert expected != "PENDING_MANIFEST_CHECKSUM"
    assert hashlib.sha256(manifest_bytes).hexdigest() == expected

    manifest = json.loads(manifest_bytes)
    assert manifest["manifest_schema"] == "atlas-alpha-parity-baseline/v1"
    assert manifest["release_id"] == "alpha-2026-08-06"
    assert manifest["methodology_version"] == "alpha-0.2.0"
    assert manifest["retention"]["alpha_poc_database_mutated"] is False
    assert manifest["retention"]["manifest_is_metadata_only"] is True
    assert manifest["retention"]["raw_source_files_copied"] is False


def test_alpha_baseline_covers_counties_fields_sources_and_allowed_differences() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    coverage = manifest["coverage"]
    assert coverage["feature_count"] == 3144
    assert coverage["unique_fips"] == coverage["feature_count"]
    assert sum(coverage["geometry_types"].values()) == coverage["feature_count"]

    profiles = manifest["field_profiles"]
    for field in (
        "fips",
        "human_status",
        "case_count_floor_2023",
        "tick_status",
        "burgdorferi_status",
        "svi_percentile",
        "rucc_2023",
        "evidence_completeness",
        "default",
    ):
        assert field in profiles
        assert profiles[field]["present_count"] + profiles[field]["null_count"] == 3144

    source_fields = {
        field for source in manifest["source_contributions"] for field in source["fields"]
    }
    assert set(profiles) == source_fields
    assert set(manifest["allowed_difference_categories"]) == {
        "SOURCE_REFRESH",
        "SOURCE_REVISION",
        "MISSINGNESS_VALUE_STATE",
        "GEOGRAPHY_SCOPE",
        "GEOMETRY",
        "METHODOLOGY",
        "DEFECT",
    }
