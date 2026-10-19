"""Missing custom maps require exact, retained fixed-parser mapping evidence."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "fixed_mapping", Path(__file__).parents[1] / "scripts/retained_fixed_source_mapping.py"
)
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


@pytest.mark.parametrize("source", sorted(proof.FIXED))
def test_exact_retained_default_mappings_have_equal_code_evidence(source):
    version, checksum = proof.FIXED[source]
    evidence = proof.fixed_mapping_evidence(
        dict(
            source_key=source, definition_version=version, artifact_sha256=checksum, field_map=None
        )
    )
    assert set(evidence["publication_source_sha256"]) == set(proof.REFS)
    assert len(evidence["mapping_sha256"]) == 64


@pytest.mark.parametrize(
    "change", ["source_key", "definition_version", "artifact_sha256", "field_map"]
)
def test_incomplete_mapping_cannot_be_admitted_by_default(change):
    version, checksum = proof.FIXED["human"]
    row = dict(
        source_key="human", definition_version=version, artifact_sha256=checksum, field_map=None
    )
    row[change] = {} if change == "field_map" else "wrong"
    with pytest.raises(ValueError, match="exact retained"):
        proof.fixed_mapping_evidence(row)


def test_same_input_columns_with_swapped_output_mapping_are_different():
    original = """
def _assemble_counties(source_rows):
    for row in source_rows['context_svi']:
        identity[fips] = {'population': record.get('E_TOTPOP'), 'svi': record.get('RPL_THEMES')}
"""
    changed = (
        original.replace("'E_TOTPOP'", "'swap'")
        .replace("'RPL_THEMES'", "'E_TOTPOP'")
        .replace("'swap'", "'RPL_THEMES'")
    )
    assert proof.mapping_descriptor(original, "context_svi") != proof.mapping_descriptor(
        changed, "context_svi"
    )
