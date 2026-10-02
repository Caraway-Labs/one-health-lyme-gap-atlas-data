"""DATA200 source-specific release checks; shared DATA202 checks have another owner."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from test_semantic_release import _manifest, _row

import lyme_gap_atlas_data.semantic_release as release


def _assemble(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], vintage: str = "2023"
) -> Any:
    monkeypatch.setattr(release, "EXPECTED_COUNTIES", 1)
    manifest = _manifest()
    manifest = replace(
        manifest,
        sources=tuple(
            replace(source, vintage=vintage) if source.source_key == "context_rucc" else source
            for source in manifest.sources
        ),
    )
    gates = {
        source.source_key: release.SourceGate(source, datetime(2026, 9, 15, tzinfo=UTC))
        for source in manifest.sources
    }
    return release._assemble_counties(
        manifest,
        {
            "context_svi": [
                _row(
                    {
                        "STCNTY": "01001",
                        "COUNTY": "Autauga",
                        "ST_ABBR": "AL",
                        "STATE": "Alabama",
                        "E_TOTPOP": 100,
                        "RPL_THEMES": 0.5,
                        "EPL_UNINSUR": 0.25,
                        "EP_UNINSUR": 5,
                        "geometry": {"type": "Polygon", "coordinates": []},
                    }
                )
            ],
            "context_rucc": rows,
            "human": [],
            "tick": [
                _row(
                    {
                        "FIPSCode": "01001",
                        "Ixodes_scapularis_County_Status": "No records",
                        "Ixodes_pacificus_county_status": "No records",
                    }
                )
            ],
            "pathogen": [_row({"FIPSCode": "01001", "burgdorferi_status": "No records"})],
        },
        gates,
    )


@pytest.mark.parametrize("code", range(1, 10))
@pytest.mark.parametrize("representation", [int, float, str])
def test_rucc_accepts_only_2023_categories_and_retains_leading_zero_lineage(
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    representation: Any,
) -> None:
    selected = _row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": representation(code)})
    _, observations = _assemble(monkeypatch, [selected])
    observation = next(row for row in observations if row[2] == "rucc_2023")
    assert observation[3] == "01001"
    assert observation[11] == "OBSERVED"
    assert observation[10] == str(code)
    assert observation[5:10] == (
        "version-context_rucc",
        "run-context_rucc",
        "artifact-context_rucc",
        "source-row",
        "b" * 64,
    )
    assert observation[13:15] == ("COUNTY_FIPS_5", "2023")


@pytest.mark.parametrize("value", [0, 10, -1, -999, 1.5, None, "", True, False, "NaN", "inf"])
def test_invalid_rucc_never_becomes_a_category(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    with pytest.raises(release.SemanticReleaseBlocked, match="invalid 2023 county code"):
        _assemble(monkeypatch, [_row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": value})])


@pytest.mark.parametrize("fips", [1001, "1001", "01001.0", "000000", None])
def test_rucc_does_not_guess_a_lost_county_mapping(
    monkeypatch: pytest.MonkeyPatch, fips: Any
) -> None:
    with pytest.raises(release.SemanticReleaseBlocked, match="invalid 2023 county code"):
        _assemble(monkeypatch, [_row({"FIPS": fips, "Attribute": "RUCC_2023", "Value": 4})])


def test_duplicate_rucc_blocks_even_when_values_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": 4})
    with pytest.raises(release.SemanticReleaseBlocked, match="duplicate county FIPS"):
        _assemble(monkeypatch, [row, row])


def test_other_attributes_cannot_fill_missing_rucc(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(release.SemanticReleaseBlocked, match="does not cover every"):
        _assemble(
            monkeypatch, [_row({"FIPS": "01001", "Attribute": "Population_2020", "Value": 4})]
        )


def test_other_attributes_and_noncanonical_counties_do_not_expand_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": 4}),
        _row({"FIPS": "01001", "Attribute": "Population_2020", "Value": 100}),
        _row({"FIPS": "72001", "Attribute": "RUCC_2023", "Value": 9}),
    ]
    counties, observations = _assemble(monkeypatch, rows)
    assert len(counties) == 1
    assert len(observations) == 14


@pytest.mark.parametrize("vintage", ["2013", "2022", "2023/2013"])
def test_rucc_vintage_cannot_be_silently_substituted(
    monkeypatch: pytest.MonkeyPatch,
    vintage: str,
) -> None:
    with pytest.raises(release.SemanticReleaseBlocked, match="2023 codebook vintage"):
        _assemble(
            monkeypatch, [_row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": 4})], vintage
        )
