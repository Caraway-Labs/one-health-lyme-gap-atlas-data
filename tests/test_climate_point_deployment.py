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


@pytest.mark.parametrize("rows", [[(8, 8, 0, 0)], [(8, 9, 0, 1)], [(8, 8, 1, 0)], []])
def test_preapply_scientific_parity_checks_all_fields_without_mutation(rows):
    cursor = Mock()
    cursor.fetchall.return_value = rows
    if rows == [(8, 8, 0, 0)]:
        point.scientific_gate(cursor, optimized=False)
    else:
        with pytest.raises(ValueError, match="POINT_FULL_PROJECTION_PARITY"):
            point.scientific_gate(cursor, optimized=False)
    sql = cursor.execute.call_args.args[0]
    assert "SELECT * FROM baseline MINUS SELECT * FROM candidate" in sql
    assert "SELECT * FROM candidate MINUS SELECT * FROM baseline" in sql
    assert "48277" in sql and "02013" in sql and "2025-01-17" in sql


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "zero",
        "temperature",
        "tavg",
        "unit",
        "null",
        "coverage",
        "duplicate",
        "nan",
        "infinite",
        "boolean",
    ],
)
def test_full_scientific_readback_fails_on_changed_meaning(fault):
    fields = [
        "county_fips",
        "measure_id",
        "release_id",
        "value",
        "coverage_status",
        "value_state",
        "unit",
    ]
    records = []
    for county in ("02013", "48277"):
        for measure, value in (
            ("prcp", 0),
            ("tmin", -1.992294192037333),
            ("tmax", 16.29939307942125),
            ("tavg", 7.153611977327104),
        ):
            records.append(
                [
                    county,
                    f"nclimgrid_{measure}_county_day",
                    point.RELEASE,
                    value if county == "48277" else None,
                    "COMPLETE" if county == "48277" else "OUT_OF_SOURCE_COVERAGE",
                    ("ZERO" if measure == "prcp" else "OBSERVED")
                    if county == "48277"
                    else "UNAVAILABLE",
                    "mm" if measure == "prcp" else "degree_Celsius",
                ]
            )
    if fault == "nan":
        records[5][3] = float("nan")
    if fault == "infinite":
        records[5][3] = float("inf")
    if fault == "boolean":
        records[4][3] = False
    if fault == "zero":
        records[4][3] = None
    if fault == "temperature":
        records[5][3] = 0
    if fault == "tavg":
        records[7][3] = 7.0
    if fault == "unit":
        records[4][6] = "inches"
    if fault == "null":
        records[0][3] = 0
    if fault == "coverage":
        records[0][4] = "MISSING"
    if fault == "duplicate":
        records[-1] = records[-2]
    cursor = Mock()
    cursor.description = [(field,) for field in fields]
    cursor.fetchmany.return_value = records
    if fault:
        with pytest.raises(ValueError):
            point.scientific_gate(cursor, optimized=True)
    else:
        assert point.scientific_gate(cursor, optimized=True)["returned_rows"] == 8
    assert "SELECT *" in cursor.execute.call_args.args[0]
    assert "LIMIT 9" in cursor.execute.call_args.args[0]


@pytest.mark.parametrize("fault", [None, "size", "type", "auto_suspend", "auto_resume", "name"])
def test_warehouse_gate_rejects_changed_or_unknown_capacity(fault):
    cursor = Mock()
    config = {
        "name": "OH_LYME_PROD_APPROVAL_XS_WH",
        "type": "STANDARD",
        "size": "X-Small",
        "auto_suspend": 600,
        "auto_resume": True,
    }
    if fault:
        config[fault] = None
    cursor.description = [(key,) for key in config]
    cursor.fetchall.return_value = [tuple(config.values())]
    if fault:
        with pytest.raises(ValueError, match="POINT_WAREHOUSE_ASSUMPTIONS"):
            point.warehouse_gate(cursor)
    else:
        assert point.warehouse_gate(cursor)["size"] == "X-Small"
    assert cursor.execute.call_args.args[0].startswith("SHOW WAREHOUSES")
