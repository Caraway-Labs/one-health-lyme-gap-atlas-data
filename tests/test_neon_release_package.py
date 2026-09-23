from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.ingestion import neon_release_package
from lyme_gap_atlas_data.ingestion.neon_release_package import (
    NeonReleasePackageAdapter,
    _select_package_file,
)
from lyme_gap_atlas_data.ingestion.runtime import evaluate_quality_rules
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    validate_source_definition,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "config" / "sources" / "neon_tick_release_2026.yml"


def test_neon_qa_support_file_must_be_the_single_native_member() -> None:
    files = [
        {
            "name": "NEON.D02.BLAN.DP1.10092.001.tck_pathogenqa.20251204T225314Z.csv",
            "url": "https://example.test/qa",
            "md5": "digest",
        },
        {
            "name": "NEON.D02.BLAN.DP1.10092.001.tck_pathogen.2016-05.expanded.csv",
            "url": "https://example.test/pathogen",
            "md5": "digest",
        },
    ]

    selected = _select_package_file(files, "tck_pathogenqa", requires_expanded=False)

    assert selected["name"].endswith("tck_pathogenqa.20251204T225314Z.csv")


def _fixture(
    tmp_path: Path,
    *,
    result: str = "positive",
    taxon: str = "Ixodes scapularis",
    pathogen: str = "Borrelia burgdorferi sensu lato",
) -> None:
    files = {
        "field.csv": (  # noqa: E501
            "siteID,plotID,eventID,sampleID,collectDate,samplingMethod,totalSampledArea,decimalLatitude,decimalLongitude,coordinateUncertainty,samplingImpractical,dataQF\nBLAN,BLAN_001,event-1,sample-1,2016-05-01,drag,100,38,-78.5,10,false,\n"
        ),
        "taxonomy.csv": "sampleID,subsampleID,scientificName,sexOrAge,individualCount,dataQF\n"  # noqa: E501
        "sample-1,sub-1," + taxon + ",nymph,2,\n",
        "pathogen.csv": "subsampleID,testingID,batchID,testedDate,testResult,testPathogenName,individualCount,dataQF\n"  # noqa: E501
        "sub-1,test-1,batch-1,2016-05-02," + result + "," + pathogen + ",1,\n",
        "qa.csv": "batchID,uid,qaStatus\nbatch-1,qa-1,pass\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "name": "field.csv",
                        "fixture": "field.csv",
                        "table": "tck_fielddata",
                        "source_uri": "https://example.test/field",
                    },
                    {
                        "name": "taxonomy.csv",
                        "fixture": "taxonomy.csv",
                        "table": "tck_taxonomyProcessed",
                        "source_uri": "https://example.test/taxonomy",
                    },
                    {
                        "name": "pathogen.csv",
                        "fixture": "pathogen.csv",
                        "table": "tck_pathogen",
                        "source_uri": "https://example.test/pathogen",
                    },
                    {
                        "name": "qa.csv",
                        "fixture": "qa.csv",
                        "table": "tck_pathogenqa",
                        "source_uri": "https://example.test/qa",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_neon_fixture_harmonizes_individual_test_and_retains_artifact_set(tmp_path: Path) -> None:
    _fixture(tmp_path)
    definition = load_source_definition(DEFINITION)
    assert validate_source_definition(definition).ok
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)
    assert acquired.artifacts[0].name == "neon-release-package-manifest.json"
    assert len(acquired.artifacts) == 5
    adapter = NeonReleasePackageAdapter()
    assert adapter.validate_payload(definition, acquired.payload).ok
    records = adapter.normalize(definition, acquired.payload).records
    detail = adapter.normalize(definition, acquired.payload).detail
    observations = [row["record"]["canonical_observation"] for row in records]
    collection = next(
        row for row in observations if row["observation_type"] == "COLLECTION_ABUNDANCE"
    )
    testing = next(row for row in observations if row["observation_type"] == "PATHOGEN_TESTING")
    assert collection["county_relationship"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    assert collection["ticks_collected"] == 2
    assert "normalized_abundance" not in collection
    assert testing["ticks_tested"] == 1 and testing["ticks_positive"] == 1
    assert detail["registry_version"] == "1.0.4"
    schema = json.loads(
        (
            ROOT
            / "docs"
            / "contracts"
            / "tick-surveillance"
            / "canonical-tick-surveillance-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = [
        error.message
        for row in observations
        for error in Draft202012Validator(schema).iter_errors(row)
    ]
    assert errors == []


def test_neon_quality_rules_apply_to_canonical_records_after_native_validation(
    tmp_path: Path,
) -> None:
    _fixture(tmp_path)
    definition = load_source_definition(DEFINITION)
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)
    normalized = NeonReleasePackageAdapter().normalize(definition, acquired.payload)

    results = evaluate_quality_rules(definition, normalized.records)

    assert [(result["rule_id"], result["status"]) for result in results] == [
        ("neon_canonical_record_count", "PASSED"),
        ("neon_value_state_preservation", "PASSED"),
    ]


def test_neon_unknown_mapping_and_blank_result_fail_closed(tmp_path: Path) -> None:
    _fixture(tmp_path, taxon="Ixodes inventedus")
    definition = load_source_definition(DEFINITION)
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)
    with pytest.raises(ValueError, match="unapproved mapping"):
        NeonReleasePackageAdapter().normalize(definition, acquired.payload)
    _fixture(tmp_path, result="")
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)
    with pytest.raises(ValueError, match="blank pathogen test result"):
        NeonReleasePackageAdapter().normalize(definition, acquired.payload)


@pytest.mark.parametrize(
    ("pathogen", "disposition"),
    [
        ("HardTick DNA Quality", "NON_PATHOGEN_ASSAY_QC"),
        ("Ixodes pacificus", "NON_PATHOGEN_TICK_IDENTIFICATION"),
    ],
)
def test_neon_non_pathogen_assays_are_traceable_without_pathogen_observations(
    tmp_path: Path, pathogen: str, disposition: str
) -> None:
    _fixture(tmp_path, pathogen=pathogen)
    definition = load_source_definition(DEFINITION)
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)

    normalized = NeonReleasePackageAdapter().normalize(definition, acquired.payload)

    assert [
        row["record"]["canonical_observation"]["observation_type"] for row in normalized.records
    ] == ["COLLECTION_ABUNDANCE"]
    assert normalized.detail == {
        "canonical_observation_count": 1,
        "registry_version": "1.0.4",
        "supporting_assay_count": 1,
        "supporting_assays": [
            {
                "source_record_id": (
                    "RELEASE-2026:DP1.10092.001:event-1:sample-1:sub-1:test-1:" + pathogen
                ),
                "source_value": pathogen,
                "test_result": "positive",
                "test_protocol_version": None,
                "disposition": disposition,
                "normalization": {
                    "source_value": pathogen,
                    "canonical_id": None,
                    "canonical_label": None,
                    "status": "UNSUPPORTED",
                    "mapping_rule_id": (
                        "ASSAY_NEON_HARDTICK_DNA_QUALITY_V1"
                        if pathogen == "HardTick DNA Quality"
                        else "ASSAY_NEON_IXODES_PACIFICUS_IDENTIFICATION_V1"
                    ),
                    "registry_id": "tick-surveillance-normalization-v1",
                    "registry_version": "1.0.4",
                    "source_context": {
                        "publisher": "NSF NEON",
                        "dataset_id": "DP1.10092.001",
                        "source_version": "RELEASE-2026",
                    },
                    "disposition": disposition,
                },
            }
        ],
    }
    assert acquired.payload["tables"]["tck_pathogen"][0]["testPathogenName"] == pathogen


def test_neon_normalization_pins_registry_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path)
    definition = load_source_definition(DEFINITION)
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)
    monkeypatch.setattr(
        neon_release_package, "load_registry", lambda: {"registry_version": "1.0.5"}
    )

    with pytest.raises(ValueError, match="registry version is not pinned"):
        NeonReleasePackageAdapter().normalize(definition, acquired.payload)


def test_neon_qa_batch_grouping_is_retained_without_a_canonical_join(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / "qa.csv").write_text(
        "batchID,uid,qaStatus\nbatch-1,qa-1,pass\nbatch-1,qa-2,pass\n",
        encoding="utf-8",
    )
    definition = load_source_definition(DEFINITION)
    acquired = NeonReleasePackageAdapter().acquire(definition, fixture_dir=tmp_path)

    records = NeonReleasePackageAdapter().normalize(definition, acquired.payload).records

    assert len(records) == 2
    assert records[1]["record"]["source_quality_context"] == {}
