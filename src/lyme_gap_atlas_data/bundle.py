"""Read and validate the immutable Alpha bundle."""

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_SHA256 = "dd7408c7ce0f8c55623c3319cec813c0e28f3b0c81929197b1958f2a4a47be7c"
EXPECTED_COUNTIES = 3_144


def seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "seed" / "atlas-v0.2.0.json.gz"


def load_bundle(path: Path | None = None) -> dict[str, Any]:
    with gzip.open(path or seed_path(), "rb") as stream:
        raw = stream.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Atlas seed checksum mismatch: {digest}")
    bundle: dict[str, Any] = json.loads(raw)
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: dict[str, Any]) -> None:
    if bundle.get("schema_version") != "0.2.0":
        raise ValueError("Expected Alpha schema version 0.2.0")
    features = bundle["feature_collection"]["features"]
    if len(features) != EXPECTED_COUNTIES:
        raise ValueError(f"Expected {EXPECTED_COUNTIES} counties, found {len(features)}")
    fips = [feature["properties"]["fips"] for feature in features]
    if len(set(fips)) != len(fips) or any(len(value) != 5 or not value.isdigit() for value in fips):
        raise ValueError("County FIPS must be unique five-digit strings")
    for feature in features:
        properties = feature["properties"]
        if properties["human_status"] == "no_county_linked_record" and (
            properties["case_count_floor_2023"] is not None
            or properties["incidence_floor_2023"] is not None
        ):
            raise ValueError(f"Missing-human county {properties['fips']} contains a case value")
        if not 0 <= properties["default"]["score"] <= 100:
            raise ValueError(f"County {properties['fips']} has an invalid score")
