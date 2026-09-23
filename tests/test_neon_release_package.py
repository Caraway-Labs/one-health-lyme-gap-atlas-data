from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.ingestion.neon_release_package import NeonReleasePackageAdapter
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    validate_source_definition,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "config" / "sources" / "neon_tick_release_2026.yml"


def _fixture(tmp_path: Path, *, result: str = "positive", taxon: str = "Ixodes scapularis") -> None:
    files = {
        "field.csv": (  # noqa: E501
            "siteID,plotID,eventID,sampleID,collectDate,samplingMethod,totalSampledArea,decimalLatitude,decimalLongitude,coordinateUncertainty,samplingImpractical,dataQF\nBLAN,BLAN_001,event-1,sample-1,2016-05-01,drag,100,38,-78.5,10,false,\n"
        ),
        "taxonomy.csv": "sampleID,subsampleID,scientificName,sexOrAge,individualCount,dataQF\n"  # noqa: E501
        "sample-1,sub-1," + taxon + ",nymph,2,\n",
        "pathogen.csv": "subsampleID,testingID,batchID,testedDate,testResult,testPathogenName,individualCount,dataQF\n"  # noqa: E501
        "sub-1,test-1,batch-1,2016-05-02," + result + ",Borrelia burgdorferi sensu lato,1,\n",
        "qa.csv": "batchID,qaStatus\nbatch-1,pass\n",
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
    observations = [row["record"]["canonical_observation"] for row in records]
    collection = next(
        row for row in observations if row["observation_type"] == "COLLECTION_ABUNDANCE"
    )
    testing = next(row for row in observations if row["observation_type"] == "PATHOGEN_TESTING")
    assert collection["county_relationship"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    assert collection["ticks_collected"] == 2
    assert "normalized_abundance" not in collection
    assert testing["ticks_tested"] == 1 and testing["ticks_positive"] == 1
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
