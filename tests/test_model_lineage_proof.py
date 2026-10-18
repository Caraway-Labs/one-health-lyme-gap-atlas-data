"""The bounded verifier must reject changed lineage despite equal row counts."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("projected", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        None,
        "mapping",
        "source",
        "row",
        "dropped",
        "membership",
        "governed_hash",
        "duplicate_id",
        "feature",
        "missing_feature",
        "missing_metadata",
        "missing_row_field",
        "malformed_checksum",
        "manifest_artifact_disagreement",
        "metadata_run_disagreement",
    ],
)
def test_full_lineage_proof_is_multiplicity_sensitive_and_not_an_approval(
    monkeypatch, tmp_path, change, projected
):
    root = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "lineage_proof", root / "scripts/verify_model_source_lineage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    emitted = []

    def query(connection, sql):
        emitted.append(sql)
        for view, base in {
            "LINEAGE_AUDIT.RETAINED_MODEL_RELEASES_V": "PRESENTATION.SEMANTIC_RELEASES",
            "LINEAGE_AUDIT.RETAINED_MODEL_SOURCES_V": "PRESENTATION.SEMANTIC_DATA_SOURCES",
            "LINEAGE_AUDIT.RETAINED_MODEL_MEMBERSHIP_V": "PRESENTATION.SEMANTIC_COUNTY_ATLAS",
            "LINEAGE_AUDIT.RETAINED_MODEL_OBSERVATIONS_V": "PRESENTATION.SEMANTIC_OBSERVATIONS",
        }.items():
            sql = sql.replace(view, base)
        target = module.TARGET in sql
        if "CURRENT_USER" in sql:
            return [{"D": "ONE_HEALTH_LYME_GAP_ATLAS_PROD", "R": "OH_LYME_PROD_READ"}]
        if "FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS" in sql:
            fips = (
                (root / "src/lyme_gap_atlas_data/data/canonical-county-fips-2022.txt")
                .read_text()
                .split()
            )
            if target and change == "membership":
                fips[0] = "99999"
            rows = [
                {**dict.fromkeys(module.FEATURE_FIELDS.split(","), "same"), "FIPS": f} for f in fips
            ]
            if target and change == "feature":
                rows[0]["HUMAN_STATUS"] = "changed"
            # Emulate a real cursor: never return fields absent from the SELECT.
            selected = sql.split(" FROM ", 1)[0].removeprefix("SELECT ").upper().split(",")
            if target and change == "missing_feature":
                selected.remove("HUMAN_STATUS")
            return [{key: row[key] for key in selected} for row in rows]
        if "source_manifest" in sql:
            sources = [
                {
                    "source_key": s,
                    "artifact_sha256": "bad"
                    if change == "malformed_checksum"
                    else "f" * 64
                    if change == "manifest_artifact_disagreement"
                    else "a" * 64,
                    "definition_version": 1,
                    "field_map": {"x": "changed" if target and change == "mapping" else "y"},
                }
                for s in module.SOURCES
            ]
            return [
                {
                    "BUNDLE_SHA256": module.BUNDLE if target else module.ORIGINAL_BUNDLE,
                    "SOURCE_MANIFEST": {"sources": sources},
                }
            ]
        if "SEMANTIC_DATA_SOURCES" in sql:
            return [
                {
                    **dict.fromkeys(module.SOURCE_FIELDS.upper().split(","), "same"),
                    "SOURCE_KEY": s,
                    "ARTIFACT_ID": "changed" if target and change == "source" else "a",
                    "SOURCE_VERSION_ID": None if change == "missing_metadata" else "v",
                    "INGESTION_RUN_ID": "wrong" if change == "metadata_run_disagreement" else "r",
                }
                for s in module.SOURCES
            ]
        if "COUNT(*) AS N" in sql:
            return [{"N": 2 if target and change in {"dropped", "duplicate_id"} else 1}]
        row = {
            **dict.fromkeys(module.ROW_FIELDS.upper().split(","), "same"),
            "OBSERVATION_ID": "observation",
            "RELEASE_BUNDLE_SHA256": module.BUNDLE if target else module.ORIGINAL_BUNDLE,
            "SOURCE_VERSION_ID": "v",
            "SOURCE_KEY": "human",
            "ARTIFACT_ID": "a",
            "INGESTION_RUN_ID": "r",
            "GOVERNED_SOURCE_ROW_HASH": (
                "wrong"
                if target and change == "governed_hash"
                else "b" * 64
                if target and change == "row"
                else "a" * 64
            ),
            "RECORD_MATCH_KIND": "IMMUTABLE_REVISION",
            "GOVERNED_SOURCE_VERSION_ID": "v",
            "GOVERNED_INGESTION_RUN_ID": "r",
            "ARTIFACT_SHA256": "a" * 64,
            "SEMANTIC_SOURCE_ROW_HASH": "b" * 64 if target and change == "row" else "a" * 64,
            "SEMANTIC_SOURCE_RECORD_ID": None if change == "missing_row_field" else "record",
        }
        return [row, dict(row)] if target and change == "duplicate_id" else [row]

    monkeypatch.setattr(module, "query", query)
    receipt = tmp_path / "receipt.json"
    argv = ["proof", "--connection", "fixture", "--receipt", str(receipt)]
    if projected:
        argv.append("--reviewed-projections")
    monkeypatch.setattr("sys.argv", argv)
    if change:
        with pytest.raises(ValueError, match="differ|dropped|governed|duplicated|Incomplete"):
            module.main()
        assert json.loads(receipt.read_text())["status"] != "complete_equal_not_approval"
    else:
        module.main()
        assert json.loads(receipt.read_text())["status"] == "complete_equal_not_approval"

    if projected:
        assert not any("PRESENTATION.SEMANTIC_" in sql for sql in emitted)
    if change:
        assert json.loads(receipt.read_text())["mismatches"]


@pytest.mark.parametrize(
    "role", ["ACCOUNTADMIN", "OH_LYME_PROD_OWNER", "OH_LYME_PROD_MIGRATION_DEPLOYER"]
)
def test_diagnostic_rejects_elevated_context_before_retained_reads(monkeypatch, tmp_path, role):
    root = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "lineage_context", root / "scripts/verify_model_source_lineage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def query(connection, sql):
        calls.append(sql)
        return [{"D": "ONE_HEALTH_LYME_GAP_ATLAS_PROD", "R": role}]

    monkeypatch.setattr(module, "query", query)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr("sys.argv", ["proof", "--connection", "fixture", "--receipt", str(receipt)])
    with pytest.raises(ValueError, match="read context required"):
        module.main()
    assert len(calls) == 1
    assert "CURRENT_USER" in calls[0]
    assert json.loads(receipt.read_text())["status"] == "incomplete"
