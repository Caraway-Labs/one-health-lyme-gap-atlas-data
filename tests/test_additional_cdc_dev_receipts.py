"""Owner decision is real; prepared receipts do not deploy or self-register."""

import json
from pathlib import Path

from lyme_gap_atlas_data.intelligence_items import identity_hash, validate_record
from lyme_gap_atlas_data.intelligence_metadata import NativeMetadataPolicy


def test_final_dev_receipts_match_actual_approved_scope_and_remain_unloaded():
    root = Path(__file__).parents[1]
    config = root / "config/intelligence"
    package = json.loads((config / "additional-cdc-dev-policy-receipts.json").read_text())
    assert package["environment"] == "DEV"
    assert package["approved_budget_usd"] == 5
    assert package["maximum_sequential_runs"] == 4
    assert {row["source_id"] for row in package["receipts"]} == {"cdc-mmwr", "cdc-newsroom"}
    for receipt in package["receipts"]:
        source = json.loads((config / f"{receipt['source_id']}-source-v1.json").read_text())
        validate_record("source", source)
        assert source["state"] == "manual"
        assert source["topics"] == source["geographies"] == []
        assert source["access_use"]["public_excerpt_permitted"] is False
        assert source["approval"]["decision_ref"] == package["decision_ref"]
        assert source["trust_review"]["decision_ref"] == package["decision_ref"]
        assert receipt["source_sha256"] == identity_hash(source)
        document = receipt["native_policy"]
        policy = NativeMetadataPolicy(
            **{
                **document,
                **{
                    key: frozenset(document[key])
                    for key in ("inventory", "permitted_paths", "required_paths")
                },
            }
        )
        policy.validate(source)
        assert len(policy.permitted_paths) == 8
        assert {"item/description", "item/category"} <= policy.permitted_paths
        assert receipt["pass_bounds"] == {
            "maximum_items": 3000,
            "maximum_normalized_bytes": 32_000_000,
        }
    active_receipts = json.loads((config / "pilot-policy-receipts.json").read_text())["receipts"]
    assert not {"cdc-mmwr", "cdc-newsroom"} & {row["source_id"] for row in active_receipts}
