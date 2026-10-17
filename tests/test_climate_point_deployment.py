"""Offline deployment guards; never evidence of actual PROD state."""

import runpy
from copy import deepcopy
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import climate_point_deployment as point


@pytest.mark.parametrize(
    "fault", [None, "release", "bundle", "owner", "reader", "definition", "capture", "manifest"]
)
def test_snapshot_fails_closed_and_retains_exact_grants(monkeypatch, fault):
    extension = {
        "target_environment": "prod",
        "ingestion_run_id": "d0e1e30b-49f1-5400-8345-af0b3e975114",
        "capture_membership_sha256": (
            "8a577c0450024808a2c1bfcfe60b9a5cbe569cc6bbb229170894bdd5a117e4bf"
        ),
        "row_count": 389856,
    }
    validator = Mock(side_effect=ValueError("bad manifest") if fault == "manifest" else None)
    monkeypatch.setattr(point, "validate_extension", validator)
    if fault == "capture":
        extension["ingestion_run_id"] = "different"
    grants = [
        ("OWNERSHIP", "ROLE", point.OWNER, "true"),
        ("SELECT", "ROLE", "OH_LYME_PROD_READ", "false"),
    ]
    if fault == "owner":
        grants[0] = ("OWNERSHIP", "ROLE", "other", "true")
    if fault == "reader":
        grants.pop()
    cursor = Mock()
    cursor.description = [(x,) for x in ("privilege", "granted_to", "grantee_name", "grant_option")]
    cursor.fetchall.side_effect = [
        [
            (
                "other" if fault == "release" else point.RELEASE,
                "other" if fault == "bundle" else point.BUNDLE,
                deepcopy(extension),
            )
        ],
        grants,
    ]
    source = (point.ROOT / "migrations/V154__prod_climate_membership_point_lookup.sql").read_text()
    cursor.fetchone.return_value = ("SELECT 1" if fault == "definition" else source,)
    body = runpy.run_path(str(point.ROOT / "scripts/verify_climate_dev_views.py"))["body"]
    if fault:
        with pytest.raises(ValueError):
            point.snapshot(cursor, body, optimized=True)
    else:
        result = point.snapshot(cursor, body, optimized=True)
        assert result["release"] == point.RELEASE and result["row_count"] == 389856
        assert len(result["grants"]) == 2
    assert all(
        call.args[0].startswith(("SELECT ", "SHOW GRANTS"))
        for call in cursor.execute.call_args_list
    )
