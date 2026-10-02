"""Keep audit references tied to existing contracts, never runtime claims."""

import json
from pathlib import Path

from lyme_gap_atlas_data.semantic_source_mappings import load_mapping_registry

ROOT = Path(__file__).parents[1]


def test_readiness_inventory_resolves_existing_identities_and_evidence() -> None:
    audit = json.loads(
        (ROOT / "docs/contracts/interoperability/provenance-readiness-v1.json").read_text()
    )
    registry = load_mapping_registry(
        ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )
    assert audit["evidence_basis"] == "REPOSITORY_CONTRACT_AUDIT_NOT_RUNTIME"
    assert {row["family"] for row in audit["representatives"]} == {
        "human",
        "tick_pathogen",
        "svi_rucc",
        "environmental",
    }
    for contract in audit["contracts"]:
        assert (ROOT / contract["evidence"]).is_file()
        assert contract["version"] in (ROOT / contract["evidence"]).read_text()
    for row in audit["representatives"]:
        for evidence in row.get("evidence", []):
            assert (ROOT / evidence).is_file()
        for mapping_id in row["mapping_ids"]:
            assert mapping_id in registry
        for test in row["tests"]:
            assert (ROOT / test).is_file()
    human = registry["human_surveillance"]
    human_evidence = next(row for row in audit["representatives"] if row["family"] == "human")
    assert "migrations/V128__current_source_methodology_metadata.sql" in human_evidence["evidence"]
    assert "tests/test_current_source_methodology_projection.py" in human_evidence["tests"]
    assert (human["source_id"], human["dataset_id"], human["measure_id"]) == (
        "cdc_lyme",
        "x5j9-wybp",
        "case_count_floor_2023",
    )
