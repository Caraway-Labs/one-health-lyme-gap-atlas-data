import hashlib
import json
from pathlib import Path

from lyme_gap_atlas_data.semantic_domain import CONTRACT_VERSION as DOMAIN_VERSION
from lyme_gap_atlas_data.semantic_domain import observation_key, revision_id
from lyme_gap_atlas_data.semantic_lineage import (
    CONTRACT_VERSION,
    lineage_id,
    validate_lineages,
)

root = Path(__file__).parents[1]
metadata = {
    m["measure"]["measure_id"]: m
    for m in json.loads(
        (
            root / "docs/contracts/semantic-domain/data-199-200-metadata-reviewed-2026-10-04.json"
        ).read_text()
    )
}
release_id = "governed-2026-09-18-unknown-coverage"
bundle = "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026"
svi_run = "331f367d-9282-4936-9b49-a480db995016"
rucc_run = "f65bd68a-27de-4ad4-81a5-424ee24af3b6"
svi_art = "cdc_atsdr_svi_2022_county:dc042342a2e5abc108af67b439ec04c8"
rucc_art = "usda_ers_rucc_2023:ec455ee2a8bc5fc8e070575ea5bee7dc"
svi_sha = "dc042342a2e5abc108af67b439ec04c86da8b61f9bdd1cf1b1e5ee0462dea7b2"
rucc_sha = "ec455ee2a8bc5fc8e070575ea5bee7dce46fc6037f8c3449cbf56e8b45331fa7"
records = {
    "c58b55a250a6afdcb59dbf98eb9cfe0e2bab02ba556744dfec246200a092e8ad": (
        "72cb2c0621651d0ab52ff8cf36c38fcebd5889ff5cfa6358a43e732c1a2f684d",
        svi_run,
        "2026-09-17T21:15:53.882255-07:00",
    ),
    "f993a2933084e9a681a801f8ef1f630eccbcf114ff2a0153cf881e420487f151": (
        "17050efe02176802b4ca9b0c4884a43efecec71872c3f95862fa8073c5b784d5",
        svi_run,
        "2026-09-17T21:15:54.030784-07:00",
    ),
    "2c5230eaaa8f4fcbcbe2fd72d043de2993f349f49dd58e41713294d11bff819d": (
        "1acf6bb0b8b6b26235a65f28e87b060104b57b234ce8636464c78e759955244d",
        svi_run,
        "2026-09-17T21:15:54.025582-07:00",
    ),
    "52808306cb77832eda0dccc2c904fa7eb592571b72d0c060fd30ef300b5140d7": (
        "2c4cef6dd5a1cb464cfeb034c1058354c21d30c1a364fda3b55b4981dc6b17c7",
        rucc_run,
        "2026-09-17T21:28:59.032390-07:00",
    ),
}
# Every tuple below is a physical PRESENTATION.SEMANTIC_OBSERVATIONS row from Read A:
# measure, FIPS, state, value, observation ID, source record ID, source row hash.
rows = [
    (
        "population_2022",
        "01001",
        "OBSERVED",
        58761,
        "023503b74cdfa89172376deb94584e556b6cb42a572988f1f773753ef5e3b54b",
        "c58b55a250a6afdcb59dbf98eb9cfe0e2bab02ba556744dfec246200a092e8ad",
        "72cb2c0621651d0ab52ff8cf36c38fcebd5889ff5cfa6358a43e732c1a2f684d",
    ),
    (
        "rucc_2023",
        "01001",
        "OBSERVED",
        2,
        "68901d993964f08944244e984eab18af99345c325f2f9f3df360e9f85c25227b",
        "52808306cb77832eda0dccc2c904fa7eb592571b72d0c060fd30ef300b5140d7",
        "2c4cef6dd5a1cb464cfeb034c1058354c21d30c1a364fda3b55b4981dc6b17c7",
    ),
    (
        "svi_percentile_2022",
        "01001",
        "OBSERVED",
        0.2663,
        "df84bd7b1c38ba9f9882d985680696c6a7ba0ed55411d93b3b3e629f2be0a926",
        "c58b55a250a6afdcb59dbf98eb9cfe0e2bab02ba556744dfec246200a092e8ad",
        "72cb2c0621651d0ab52ff8cf36c38fcebd5889ff5cfa6358a43e732c1a2f684d",
    ),
    (
        "svi_percentile_2022",
        "49029",
        "ZERO",
        0,
        "e4ae33785a6afb2e59c6dbe3a77b58837f2d9277a2b63647b81f8a8dd3f3390c",
        "f993a2933084e9a681a801f8ef1f630eccbcf114ff2a0153cf881e420487f151",
        "17050efe02176802b4ca9b0c4884a43efecec71872c3f95862fa8073c5b784d5",
    ),
    (
        "uninsured_percent_2022",
        "01001",
        "OBSERVED",
        7.4,
        "86352c2c3f74c0342f1b5aa40a61e04281461dd0ec7335ed5e4284d4b1f7210c",
        "c58b55a250a6afdcb59dbf98eb9cfe0e2bab02ba556744dfec246200a092e8ad",
        "72cb2c0621651d0ab52ff8cf36c38fcebd5889ff5cfa6358a43e732c1a2f684d",
    ),
    (
        "uninsured_percent_2022",
        "48301",
        "ZERO",
        0,
        "5740c205aeaa9aa5a63ae99feff67723199c8459cdcf1ffee434cb3b28d9665b",
        "2c5230eaaa8f4fcbcbe2fd72d043de2993f349f49dd58e41713294d11bff819d",
        "1acf6bb0b8b6b26235a65f28e87b060104b57b234ce8636464c78e759955244d",
    ),
    (
        "uninsured_percentile_2022",
        "01001",
        "OBSERVED",
        0.412,
        "48aff5062f0a89c47be90896199b078740e9c0e6537a52e7c80741d9fb228763",
        "c58b55a250a6afdcb59dbf98eb9cfe0e2bab02ba556744dfec246200a092e8ad",
        "72cb2c0621651d0ab52ff8cf36c38fcebd5889ff5cfa6358a43e732c1a2f684d",
    ),
    (
        "uninsured_percentile_2022",
        "48301",
        "ZERO",
        0,
        "bb6a47674bf818b4cd9ae8ebaa947d6d9aaf71110e9e5e48e4a1d4307954ff0c",
        "2c5230eaaa8f4fcbcbe2fd72d043de2993f349f49dd58e41713294d11bff819d",
        "1acf6bb0b8b6b26235a65f28e87b060104b57b234ce8636464c78e759955244d",
    ),
]
registry = {
    k: {}
    for k in (
        "source_versions",
        "runs",
        "artifacts",
        "records",
        "proofs",
        "inputs",
        "results",
        "releases",
    )
}
lineages = []
for measure_id, fips, state, value, physical_id, record_id, observed_hash in rows:
    m = metadata[measure_id]
    measure = m["measure"]
    prov = m["provenance"]
    rucc = measure_id == "rucc_2023"
    run_id, artifact_id, artifact_sha = (
        (rucc_run, rucc_art, rucc_sha) if rucc else (svi_run, svi_art, svi_sha)
    )
    row_hash, record_run, retrieved = records[record_id]
    assert record_run == run_id
    assert observed_hash == row_hash
    version = prov["source_version_id"]["value"]
    source_id = prov["source_id"]["value"]
    dataset_id = prov["dataset_id"]["value"]
    vintage = prov["source_vintage"]["value"]
    publisher = prov["publisher"]["value"]
    resource_key = "usda_ers_rucc_2023" if rucc else "cdc_atsdr_svi_2022_county"
    registry["source_versions"][version] = dict(
        source_id=source_id,
        dataset_id=dataset_id,
        resource_key=resource_key,
        source_vintage=vintage,
        publisher=publisher,
    )
    registry["runs"][run_id] = dict(source_version_id=version, dataset_id=dataset_id)
    registry["artifacts"][artifact_id] = dict(
        ingestion_run_id=run_id, source_version_id=version, sha256=artifact_sha
    )
    legacy_revision = (
        "legacy:v1:" + hashlib.sha256(f"{run_id}|{record_id}|{row_hash}".encode()).hexdigest()
    )
    edge = dict(
        publisher=publisher,
        source_id=source_id,
        dataset_id=dataset_id,
        resource_key=resource_key,
        source_version_id=version,
        source_vintage=vintage,
        ingestion_run_id=run_id,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha,
        record_id=record_id,
        source_record_id=record_id,
        source_row_hash=row_hash,
        canonical_record_id=record_id,
        record_revision=legacy_revision,
        record_kind="CANONICAL",
        normalization_ref=None,
        eligibility_ref=None,
    )
    registry["records"][record_id] = {
        k: edge[k]
        for k in (
            "artifact_id",
            "ingestion_run_id",
            "source_version_id",
            "source_record_id",
            "source_row_hash",
            "canonical_record_id",
            "record_revision",
            "record_kind",
        )
    }
    temporal = (
        {"semantics": "VINTAGE_YEAR", "year": "2023"}
        if rucc
        else {"semantics": "PERIOD", "start": "2018-01-01", "end": "2022-12-31"}
    )
    observation = dict(
        contract_version=DOMAIN_VERSION,
        measure_id=measure_id,
        measure_version=measure["semantic_version"],
        unit=measure["unit"],
        denominator=measure["denominator"],
        origin="REPORTED",
        geography={
            "grain": "COUNTY",
            "county_fips": fips,
            "representativeness": "COUNTY_NATIVE_STATUS",
        },
        temporal=temporal,
        strata={},
        provenance=dict(
            source_id=source_id,
            dataset_id=dataset_id,
            source_version_id=version,
            source_vintage=vintage,
            ingestion_run_id=run_id,
            artifact_id=artifact_id,
            source_record_id=record_id,
            source_row_hash=row_hash,
            retrieved_at=retrieved,
        ),
        value_state=state,
        value=value,
    )
    observation["observation_key"] = observation_key(observation, measure)
    observation["revision_id"] = revision_id(observation)
    lineage = dict(
        contract_version=CONTRACT_VERSION,
        visibility="INTERNAL",
        semantic_observation_id=observation["observation_key"],
        semantic_revision_id=observation["revision_id"],
        metadata_revision_id=m["revision_id"],
        metadata=m,
        observation=observation,
        edges=[edge],
        input_ids=[],
        transformation=dict(
            id="semantic_county_assembly",
            version="semantic_county_assembly_v1",
            methodology_version=measure["methodology_version"],
        ),
        result=None,
        release=dict(release_id=release_id, bundle_sha256=bundle, observation_id=physical_id),
    )
    lineage["lineage_id"] = lineage_id(lineage)
    lineages.append(lineage)
registry["releases"][release_id] = dict(
    bundle_sha256=bundle,
    semantic_revision_ids=[x["semantic_revision_id"] for x in lineages],
    observation_ids=[x["release"]["observation_id"] for x in lineages],
)
validate_lineages(lineages, registry)
measure_count = len({item["observation"]["measure_id"] for item in lineages})
print(
    f"#193 PASS: {len(lineages)} live physical observations; "
    f"{len(records)} exact historical conformed records; "
    f"{measure_count} reviewed measures; 3 ZERO examples"
)
