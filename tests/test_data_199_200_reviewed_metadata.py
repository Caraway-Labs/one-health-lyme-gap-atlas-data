"""Gate the reviewed #199/#200 packet against its exact source authority."""

from __future__ import annotations

import json
from pathlib import Path

from lyme_gap_atlas_data.semantic_metadata import validate_metadata_revisions

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/contracts/semantic-domain/data-199-200-metadata-reviewed-2026-10-04.json"
APPROVED = {
    (
        "cdc_atsdr_svi",
        "atsdr-svi-2022-county-layer",
        "b8b6bf61-c6a3-4538-b0df-1b88c61720b1",
    ),
    (
        "usda_ers",
        "rural-urban-continuum-codes-2023",
        "87872b36-93ab-4a34-b70e-29569192cb48",
    ),
}


def test_reviewed_packet_has_exact_source_bound_state_and_vintage_scope() -> None:
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    validate_metadata_revisions(packet, approved_source_versions=APPROVED)
    by_measure = {entry["measure"]["measure_id"]: entry for entry in packet}
    assert set(by_measure) == {
        "population_2022",
        "svi_percentile_2022",
        "uninsured_percentile_2022",
        "uninsured_percent_2022",
        "rucc_2023",
    }
    assert all(
        entry["steward_review"]
        == {"state": "REVIEWED", "reviewed_at": {"state": "KNOWN", "value": "2026-10-04"}}
        for entry in packet
    )
    rucc = by_measure["rucc_2023"]
    assert rucc["measure"]["semantic_version"] == "2.0.0"
    assert rucc["measure"]["temporal_semantics"] == "VINTAGE_YEAR"
    assert rucc["freshness"]["observation_period"] == {"state": "KNOWN", "value": "2023"}
    assert rucc["allowed_value_states"] == ["OBSERVED"]
    for name, entry in by_measure.items():
        if name != "rucc_2023":
            assert entry["freshness"]["observation_period"] == {
                "state": "KNOWN",
                "value": "2018-01-01/2022-12-31",
            }
            assert entry["allowed_value_states"] == ["OBSERVED", "ZERO", "MISSING"]
