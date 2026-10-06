"""Local checks for the bounded DEV publication contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)

publisher_path = Path(__file__).parents[1] / "scripts/publish_tier1_review_dev.py"
publisher_spec = importlib.util.spec_from_file_location("publish_tier1_review_dev", publisher_path)
assert publisher_spec is not None and publisher_spec.loader is not None
publisher = importlib.util.module_from_spec(publisher_spec)
publisher_spec.loader.exec_module(publisher)


def test_v140_is_dev_only_and_uses_dedicated_owner() -> None:
    migration = next(item for item in load_migrations() if item.version == "V140")
    assert (
        migration_execution_role(migration, DEV_DATABASE) == "OH_LYME_DEV_TIER1_PUBLICATION_OWNER"
    )
    assert "V140" in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V140" not in {item["version"] for item in migration_plan(PROD_DATABASE)}
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, PROD_DATABASE)


def test_digest_uses_original_sorted_python_json_bytes() -> None:
    rows = [
        {"z": 0.6000441944790827, "county_fips": "01001", "reasons": [{"code": "A"}]},
        {"z": 1.0870527819718128, "county_fips": "01003", "reasons": [{"code": "B"}]},
    ]
    canonical = [publisher.canonical_row(row) for row in rows]
    expected = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert hashlib.sha256(("[" + ",".join(canonical) + "]").encode()).hexdigest() == expected
    changed = canonical.copy()
    changed[0] = changed[0].replace("0.6000441944790827", "0.6000441944790828")
    assert hashlib.sha256(("[" + ",".join(changed) + "]").encode()).hexdigest() != expected


def test_migration_hashes_row_json_and_compares_both_fips_directions() -> None:
    source = (
        Path(__file__).parents[1] / "migrations/V140__dev_tier1_county_review_publication.sql"
    ).read_text(encoding="utf-8")
    assert "LISTAGG(row_json, ',') WITHIN GROUP (ORDER BY county_fips)" in source
    assert "SHA2('[' || LISTAGG" in source
    assert "SHA2(TO_JSON" not in source
    assert source.count("EXCEPT SELECT") == 2
    assert "TRY_PARSE_JSON(row_json)" in source
    assert "UPDATE FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK" in source
    assert "q('COMMIT')" in source
    assert "q('ROLLBACK')" in source


def test_publisher_sql_literal_preserves_apostrophes() -> None:
    assert publisher.sql_literal("publisher's row") == "'publisher''s row'"


def test_lost_acknowledgment_response_recognizes_approved_batch() -> None:
    assert publisher.procedure_state([{"SP_BEGIN": {"STATE": "APPROVED"}}]) == "APPROVED"
    assert publisher.procedure_state([{"SP_BEGIN": '{"state":"STAGING"}'}]) == "STAGING"
    with pytest.raises(ValueError, match="Unexpected publication state"):
        publisher.procedure_state([{"SP_BEGIN": {"state": "FAILED"}}])
