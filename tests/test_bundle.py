from lyme_gap_atlas_data.bundle import EXPECTED_COUNTIES, load_bundle


def test_packaged_alpha_bundle_is_exact_and_valid() -> None:
    bundle = load_bundle()
    assert bundle["schema_version"] == "0.2.0"
    assert len(bundle["feature_collection"]["features"]) == EXPECTED_COUNTIES
    assert bundle["generated_at"] == "2026-08-06T05:37:16Z"


def test_bundle_preserves_missing_human_semantics() -> None:
    features = load_bundle()["feature_collection"]["features"]
    missing = [f for f in features if f["properties"]["human_status"] == "no_county_linked_record"]
    assert missing
    assert all(f["properties"]["case_count_floor_2023"] is None for f in missing)
