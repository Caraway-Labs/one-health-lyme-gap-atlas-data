"""Fabricated contract demonstration; no clinical acquisition or Atlas persistence."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date


def synthetic_observations() -> list[dict[str, str]]:
    """FHIR-like excerpts with invented people, counties and local assay codes."""
    return [
        {
            "resourceType": "Observation",
            "id": "fake-1",
            "subject": "fake-person-1",
            "code": "LOCAL-LYME-SCREEN",
            "value": "positive",
            "effective": "2026-09-28",
            "county": "24001",
            "status": "final",
        },
        {
            "resourceType": "Observation",
            "id": "fake-2",
            "subject": "fake-person-2",
            "code": "LOCAL-LYME-SCREEN",
            "value": "negative",
            "effective": "2026-09-29",
            "county": "24001",
            "status": "final",
        },
        {
            "resourceType": "Observation",
            "id": "fake-3",
            "subject": "fake-person-3",
            "code": "LOCAL-LYME-SCREEN",
            "value": "positive",
            "effective": "2026-09-30",
            "county": "24001",
            "status": "final",
        },
        {
            "resourceType": "Observation",
            "id": "fake-4",
            "subject": "fake-person-4",
            "code": "LOCAL-LYME-SCREEN",
            "value": "negative",
            "effective": "2026-10-01",
            "county": "24001",
            "status": "final",
        },
        {
            "resourceType": "Observation",
            "id": "fake-5",
            "subject": "fake-person-5",
            "code": "LOCAL-LYME-SCREEN",
            "value": "negative",
            "effective": "2026-10-02",
            "county": "24001",
            "status": "final",
        },
        {
            "resourceType": "Observation",
            "id": "fake-6",
            "subject": "fake-person-1",
            "code": "LOCAL-LYME-SCREEN",
            "value": "positive",
            "effective": "2026-09-28",
            "county": "24001",
            "status": "corrected",
        },
    ]


def aggregate(rows: list[dict[str, str]], *, minimum_cell: int = 3) -> list[dict[str, object]]:
    """Demonstrate event deduplication and fixture-only suppression before Atlas."""
    deduplicated: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        if row["code"] != "LOCAL-LYME-SCREEN" or row["value"] not in {"positive", "negative"}:
            continue
        key = (row["subject"], row["code"], row["effective"])
        if key not in deduplicated or row["status"] == "corrected":
            deduplicated[key] = row
    groups: dict[tuple[str, date], list[dict[str, str]]] = defaultdict(list)
    for row in deduplicated.values():
        day = date.fromisoformat(row["effective"])
        start = day.fromordinal(day.toordinal() - day.weekday())
        groups[(row["county"], start)].append(row)
    output = []
    for (county, start), events in sorted(groups.items()):
        positive = sum(row["value"] == "positive" for row in events)
        suppressed = len(events) < minimum_cell or 0 < positive < minimum_cell
        output.append(
            {
                "contract_version": "atlas-clinical-lab-signal-v1",
                "status": "SYNTHETIC_FUTURE_CONCEPT",
                "signal_id": "lyme_positivity_proportion",
                "county_fips": county,
                "geography_grain": "COUNTY",
                "time_grain": "ISO_WEEK",
                "period_start": start.isoformat(),
                "period_end": date.fromordinal(start.toordinal() + 6).isoformat(),
                "numerator": None if suppressed else positive,
                "denominator": None if suppressed else len(events),
                "value": None if suppressed else positive / len(events),
                "value_state": "SUPPRESSED"
                if suppressed
                else "ZERO"
                if positive == 0
                else "OBSERVED",
                "unit": "proportion_of_interpretable_test_events",
                "source_organization": "FABRICATED_LAB",
                "source_id": "synthetic_lab",
                "dataset_id": "synthetic_lab_weekly",
                "source_version": "fixture-1",
                "source_vintage": "2026-fixture",
                "acquired_at": "2026-10-04T00:00:00Z",
                "method_version": "synthetic-demo-v1",
                "transformation_version": "synthetic-demo-v1",
                "terminology_version": "UNVALIDATED_LOCAL_FIXTURE",
                "lineage_digest": "synthetic-only-no-source-artifact",
                "representativeness": "FABRICATED_NOT_POPULATION_REPRESENTATIVE",
                "limitations": (
                    "Not a surveillance case count, population incidence, production signal "
                    "or approved LOINC mapping."
                ),
            }
        )
    return output


if __name__ == "__main__":
    print(json.dumps(aggregate(synthetic_observations()), indent=2))
