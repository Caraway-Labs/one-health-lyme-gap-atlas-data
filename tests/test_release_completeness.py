"""Release omissions and transaction failures must block actual pointer commits."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import release_completeness as gate
from lyme_gap_atlas_data import semantic_release


def test_repository_inventory_is_machine_readable_and_complete() -> None:
    path = (
        Path(__file__).parents[1]
        / "docs/contracts/semantic-release/release-completeness-2026-10-18.json"
    )
    document = json.loads(path.read_text())
    artifacts = gate.validate_manifest(document)
    assert set(artifacts) == gate.REQUIRED
    assert artifacts["context_nlcd_2025"]["expected_rows"] == 14
    assert artifacts["climate"]["expected_rows"] == 389856


def manifest() -> dict:
    return {
        "schema": gate.SCHEMA,
        "views": list(gate.VIEWS),
        "independent_consumers": [
            {
                "view": view,
                "owner": "Data",
                "consumer": "API",
                "contract": "v1",
                "scope": "approved",
                "lineage": "approved",
                "minimum_rows": 0,
                "expected_keys": ["test"],
            }
            for view in gate.INDEPENDENT
        ],
        "artifacts": [
            {
                "id": identity,
                **dict.fromkeys(gate.SOURCE_FIELDS, "pin"),
                "disposition": "carry_forward",
                "owner": "Data",
                "consumer": "API",
                "contract": "v1",
                "scope": "approved scope",
                "lineage": "source-bound",
                "approval_reference": "owner decision",
                "expected_rows": 3144,
                "presentation_measures": sorted(gate.PRESENTATION_MEASURES.get(identity, [])),
                "presentation_counties": 3144,
                "measures": sorted(gate.CLIMATE_MEASURES),
                "batch_id": "batch",
                "batch_version": "v1",
                "model_version": "v1",
                "input_release_id": "new",
                "input_bundle_sha256": "a" * 64,
                "compatibility_decision": "decision",
            }
            for identity in sorted(gate.REQUIRED)
        ],
    }


@pytest.mark.parametrize("identity", sorted(gate.REQUIRED))
def test_every_required_artifact_is_mandatory(identity: str) -> None:
    document = manifest()
    document["artifacts"] = [a for a in document["artifacts"] if a["id"] != identity]
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="omitted"):
        gate.validate_manifest(document)


def test_self_declared_degradation_is_not_an_approval() -> None:
    document = manifest()
    document["artifacts"][0]["disposition"] = "excluded"
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="retained owner decision"):
        gate.validate_manifest(document)


def test_duplicate_artifact_cannot_mask_missing_model() -> None:
    document = manifest()
    document["artifacts"].append(deepcopy(document["artifacts"][0]))
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="Duplicate"):
        gate.validate_manifest(document)


def test_historical_model_needs_real_retained_compatibility() -> None:
    document = manifest()
    next(a for a in document["artifacts"] if a["id"] == "tier1")["input_release_id"] = "old"
    cursor = MagicMock()
    cursor.fetchmany.return_value = [({"release_completeness": document}, "a" * 64)]
    cursor.fetchone.side_effect = lambda: (
        (0,) if "MODEL_RELEASE_COMPATIBILITY" in cursor.execute.call_args.args[0] else (3144,)
    )
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="approved compatibility"):
        gate.verify_candidate(cursor, "new")


def test_missing_manifest_is_not_legacy_bypass() -> None:
    cursor = MagicMock()
    cursor.fetchmany.return_value = [({}, "a" * 64)]
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="manifest missing"):
        gate.verify_candidate(cursor, "new")


def test_exception_requires_matching_retained_owner_record() -> None:
    artifacts = gate.validate_manifest(manifest())
    item = artifacts["tier1"]
    item.update(disposition="excluded", expected_rows=0, exception_decision="owner-exception")
    cursor = MagicMock()
    cursor.fetchone.return_value = (0,)
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="owner exception missing"):
        gate.authorize_artifacts(cursor, "new", "a" * 64, artifacts)
    cursor.fetchone.return_value = (1,)
    assert (
        gate.authorize_artifacts(cursor, "new", "a" * 64, artifacts)["tier1"]["expected_rows"] == 0
    )


def test_regenerated_bundle_token_binds_persisted_digest_without_mutating_manifest() -> None:
    artifacts = gate.validate_manifest(manifest())
    artifacts["tier1"]["input_bundle_sha256"] = "TARGET_BUNDLE"
    resolved = gate.authorize_artifacts(MagicMock(), "new", "a" * 64, artifacts)
    assert resolved["tier1"]["input_bundle_sha256"] == "a" * 64
    assert artifacts["tier1"]["input_bundle_sha256"] == "TARGET_BUNDLE"


@pytest.mark.parametrize("operation", ["publish", "rollback"])
def test_guard_failure_rolls_back_before_commit(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = (
        [("CANDIDATE", "a" * 64), (3144, 3144, 44016), ("DEV",)]
        if operation == "publish"
        else [("RETIRED",)]
    )
    context = MagicMock()
    context.__enter__.return_value = connection
    monkeypatch.setattr(semantic_release, "connect", lambda _: context)
    monkeypatch.setattr(semantic_release, "verify_persisted_extension", lambda *a, **k: None)
    monkeypatch.setattr(
        gate,
        "verify_candidate",
        MagicMock(side_effect=gate.ReleaseCompletenessBlocked("missing ML")),
    )
    settings = SimpleNamespace(snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    with pytest.raises(gate.ReleaseCompletenessBlocked, match="missing ML"):
        if operation == "publish":
            semantic_release.publish_semantic_release(settings, "new", reason="review")
        else:
            semantic_release.rollback_semantic_release(settings, "old", reason="review")
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    assert not any("UPDATE PRESENTATION" in c.args[0] for c in cursor.execute.call_args_list)
