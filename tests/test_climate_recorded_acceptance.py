"""Recording receipts bind exact accepted content without inventing review times."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from lyme_gap_atlas_data.climate_release import validate_extension, verify_recorded_acceptance
from lyme_gap_atlas_data.climate_source_review import DRAFT_METADATA_REVISIONS, INPUTS
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id, validate_metadata

STAMP = "2026-10-03T03:38:53.059198Z"


def candidate():
    root = Path(__file__).resolve().parents[1] / "docs/contracts/climate"
    packet = json.loads((root / "january-2025-metadata-source-review-packet.json").read_text())
    metadata = deepcopy(packet["metadata_proposals"])
    for item in metadata:
        item["metadata_revision"] = 2
        item["freshness"]["metadata_revised_at"] = {"state": "KNOWN", "value": "2026-10-03"}
        item["visibility"] = "CONSUMER_SAFE"
        item["provenance"]["source_version_id"] = {"state": "KNOWN", "value": "fixture-noaa"}
        item["steward_review"] = {
            "state": "REVIEWED",
            "reviewed_at": {"state": "UNKNOWN", "value": None},
            "acceptance_recorded_at": {"state": "KNOWN", "value": STAMP},
        }
        item["revision_id"] = metadata_revision_id(item)
    return {
        "metadata": metadata,
        "sources": {
            key: source | {"source_version_id": "fixture-" + key}
            for key, source in zip(("noaa", "tiger"), INPUTS, strict=True)
        },
    }


class Cursor:
    def __init__(self):
        self.reviewer = "MATTHEWCARAWAY"
        self.original = {"state": "UNKNOWN", "value": None}
        self.recorded = STAMP
        self.decision_resource = None
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))

    def fetchall(self):
        return [
            (
                self.reviewer,
                datetime.fromisoformat(STAMP),
                {
                    "accepted_metadata_revisions": sorted(DRAFT_METADATA_REVISIONS),
                    "acceptance_provenance": {
                        "original_decision_at": self.original,
                        "ledger_recorded_at": self.recorded,
                        "timestamp_basis": "LEDGER_RECORDING_ACTION_NOT_ORIGINAL_ACCEPTANCE",
                    },
                },
                self.queries[-1][1][0],
                "APPROVED_WITH_CONDITIONS",
                self.decision_resource or self.queries[-1][1][1],
            )
        ]


def test_exact_acceptance_with_unknown_original_date_has_separate_recording_time():
    document = candidate()
    cursor = Cursor()
    for item in document["metadata"]:
        validate_metadata(item, approved_climate_metadata_revisions={item["revision_id"]})
        assert item["steward_review"]["reviewed_at"] == {"state": "UNKNOWN", "value": None}
        assert item["freshness"]["metadata_revised_at"] == {"state": "KNOWN", "value": "2026-10-03"}
    verify_recorded_acceptance(cursor, document)
    assert len(cursor.queries) == 2
    assert all(sql.startswith("SELECT") for sql, _ in cursor.queries)
    assert cursor.queries[0][1][:2] == ("fixture-noaa", INPUTS[0]["resource_key"])
    assert cursor.queries[1][1][:2] == ("fixture-tiger", INPUTS[1]["resource_key"])


@pytest.mark.parametrize(
    "mutation", ["reviewer", "original", "recorded", "content", "mixed", "resource"]
)
def test_receipt_cannot_authorize_wrong_identity_timestamp_content_or_partial_set(mutation):
    document = candidate()
    cursor = Cursor()
    if mutation == "reviewer":
        cursor.reviewer = "unrelated"
    elif mutation == "original":
        cursor.original = {"state": "KNOWN", "value": STAMP}
    elif mutation == "recorded":
        cursor.recorded = "2026-10-03T00:00:00+00:00"
    elif mutation == "content":
        document["metadata"][0]["definition"] += " changed"
    elif mutation == "resource":
        cursor.decision_resource = "unrelated-resource"
    else:
        del document["metadata"][0]["steward_review"]["acceptance_recorded_at"]
    with pytest.raises(ValueError, match="CLIMATE_"):
        verify_recorded_acceptance(cursor, document)


def test_recorded_field_does_not_bypass_exposure_allowlist_or_invent_original_time():
    item = candidate()["metadata"][0]
    with pytest.raises(ValueError, match="separate exposure approval"):
        validate_metadata(item)
    item["steward_review"]["reviewed_at"] = {"state": "KNOWN", "value": "2026-10-03"}
    item["revision_id"] = metadata_revision_id(item)
    with pytest.raises(ValueError, match="exact January scope"):
        validate_metadata(item, approved_climate_metadata_revisions={item["revision_id"]})


@pytest.mark.parametrize("field", ["artifact_id", "resource_key"])
def test_unrelated_tiger_binding_cannot_enter_release(field):
    from test_climate_release import extension

    document = extension()
    document["sources"]["tiger"][field] = "unrelated"
    with pytest.raises(ValueError, match="CLIMATE_TIGER_"):
        validate_extension(document)
