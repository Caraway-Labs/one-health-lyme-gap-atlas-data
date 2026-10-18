"""The bounded verifier must reject changed lineage despite equal row counts."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("change", [None, "mapping", "source", "row", "dropped"])
def test_full_lineage_proof_is_multiplicity_sensitive_and_not_an_approval(
    monkeypatch, tmp_path, change
):
    root = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "lineage_proof", root / "scripts/verify_model_source_lineage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def query(connection, sql):
        target = module.TARGET in sql
        if "CURRENT_USER" in sql:
            return [{"D": "ONE_HEALTH_LYME_GAP_ATLAS_PROD", "R": "OH_LYME_PROD_READ"}]
        if "source_manifest" in sql:
            sources = [
                {
                    "source_key": s,
                    "artifact_sha256": "a",
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
                    "SOURCE_KEY": s,
                    "ARTIFACT_ID": "changed" if target and change == "source" else "a",
                }
                for s in module.SOURCES
            ]
        if "COUNT(*) AS N" in sql:
            return [{"N": 2 if target and change == "dropped" else 1}]
        return [
            {
                "RECORD_MATCH_KIND": "IMMUTABLE_REVISION",
                "GOVERNED_SOURCE_VERSION_ID": "v",
                "GOVERNED_INGESTION_RUN_ID": "r",
                "ARTIFACT_SHA256": "a",
                "SEMANTIC_SOURCE_ROW_HASH": "changed" if target and change == "row" else "original",
            }
        ]

    monkeypatch.setattr(module, "query", query)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr("sys.argv", ["proof", "--connection", "fixture", "--receipt", str(receipt)])
    if change:
        with pytest.raises(ValueError, match="differs|dropped"):
            module.main()
        assert json.loads(receipt.read_text())["status"] != "complete_equal_not_approval"
    else:
        module.main()
        assert json.loads(receipt.read_text())["status"] == "complete_equal_not_approval"
