from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from lyme_gap_atlas_data import pathogen_surveillance as pathogen


def workbook_bytes(
    *,
    headers: tuple[str, ...] = pathogen.EXPECTED_HEADERS,
    rows: list[tuple[object, ...]] | None = None,
) -> bytes:
    workbook = Workbook()
    agreement = workbook.active
    agreement.title = "Data Use Agreement"
    agreement.append(["Access to ArboNET Tick Module data is limited to the Requestor."])
    agreement.append(["These data should not be provided to other persons."])
    agreement.append(["ArboNET will be appropriately referenced."])
    agreement.append(["A final copy of publications will be provided to CDC."])
    terms = workbook.create_sheet("Classification Terms")
    terms.append(["County classification", "Definition"])
    terms.append(["Present", "A pathogen was identified in host-seeking Ixodes ticks."])
    terms.append(["No records", "This should not be interpreted as pathogen absence."])
    data = workbook.create_sheet("Ixodes Pathogens 2025")
    data.append(["Tickborne pathogens through Dec. 31, 2025"])
    data.append(list(headers))
    source_rows = rows or [
        (
            f"{1000 + index:05d}",
            "Fixture State",
            f"Fixture County {index}",
            *sum(
                (
                    ["Present" if index % 2 else "No records", f"Fixture source {column}"]
                    for column in range(7)
                ),
                [],
            ),
        )
        for index in range(1, 31)
    ]
    for row in source_rows:
        data.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_pathogen_profile_is_private_dev_evidence_only() -> None:
    profile = pathogen.load_pathogen_profile()
    assert profile["resource_key"] == pathogen.RESOURCE_KEY
    assert profile["onboarding_environments"] == ["dev"]
    assert profile["onboarding_mode"] == "EVIDENCE_ONLY"
    assert profile["allowed_status_values"] == ["Present", "No records"]
    assert profile["landing_page_url"].startswith("https://www.cdc.gov/")


def test_parser_preserves_distinct_pathogen_status_semantics() -> None:
    evidence = pathogen.parse_pathogen_workbook(
        workbook_bytes(), pathogen.load_pathogen_profile(), sample_limit=25
    )
    assert evidence.valid_county_row_count == 30
    assert evidence.blank_fips_row_count == 0
    assert len(evidence.sample) == 25
    assert evidence.sample[0]["FIPS_Code"] == "01001"
    assert evidence.schema["observation_type"] == "PATHOGEN_PRESENCE_STATUS"
    assert evidence.schema["embedded_data_use_agreement_validated"] is True
    assert evidence.schema["full_dataset_quality_validated"] is False
    assert evidence.schema["dataset_as_of"] == "2025-12-31"
    json.dumps(evidence.schema, sort_keys=True, separators=(",", ":"))


def test_parser_counts_blank_fips_rows_but_rejects_invalid_values() -> None:
    row = ("01001", "State", "County", *sum((["Present", "source"] for _ in range(7)), []))
    blank = (None, "", "", *sum((["No records", "source"] for _ in range(7)), []))
    evidence = pathogen.parse_pathogen_workbook(
        workbook_bytes(rows=[row, blank]), pathogen.load_pathogen_profile(), sample_limit=1
    )
    assert evidence.valid_county_row_count == 1
    assert evidence.blank_fips_row_count == 1
    malformed = (
        "not-a-fips",
        "State",
        "County",
        *sum((["Present", "source"] for _ in range(7)), []),
    )
    with pytest.raises(ValueError, match="five-character county FIPS"):
        pathogen.parse_pathogen_workbook(
            workbook_bytes(rows=[malformed]), pathogen.load_pathogen_profile(), sample_limit=1
        )


def test_parser_rejects_status_relabeling_and_schema_changes() -> None:
    bad_status = ("01001", "State", "County", *sum((["Absent", "source"] for _ in range(7)), []))
    with pytest.raises(ValueError, match="unreviewed pathogen-status"):
        pathogen.parse_pathogen_workbook(
            workbook_bytes(rows=[bad_status]), pathogen.load_pathogen_profile(), sample_limit=1
        )
    changed_headers = ("Changed", *pathogen.EXPECTED_HEADERS[1:])
    with pytest.raises(ValueError, match="schema changed"):
        pathogen.parse_pathogen_workbook(
            workbook_bytes(headers=changed_headers),
            pathogen.load_pathogen_profile(),
            sample_limit=1,
        )


def test_pathogen_capture_contract_is_private_and_profile_bound() -> None:
    workflow = Path(".github/workflows/capture-dev-cdc-tick-surveillance-operator.yml").read_text(
        encoding="utf-8"
    )
    cli = Path("src/lyme_gap_atlas_data/cli.py").read_text(encoding="utf-8")
    publisher = Path("scripts/publish_tick_operator_evidence.py").read_text(encoding="utf-8")
    assert "source_kind" in workflow
    assert "cdc-pathogen-surveillance-sample" in workflow
    assert '"$SOURCE_KIND-operator-evidence-$RETRIEVAL_ID"' in workflow
    assert "cdc-pathogen-surveillance-sample" in cli
    assert "--source-kind" in publisher
    assert "GitHub artifact" not in workflow
