from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data.ingestion.adapters import AcquireResult
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import ValidationResult
from lyme_gap_atlas_data.source_evidence import collect_routine_public_source_evidence

REPO = Path(__file__).resolve().parents[1]


class _Adapter:
    def acquire(self, _definition: object) -> AcquireResult:
        raw = b'{"features":[{"STCNTY":"01001"}]}'
        return AcquireResult(
            payload={"features": [{"STCNTY": "01001"}]},
            artifact_sha256=hashlib.sha256(raw).hexdigest(),
            media_type="application/geo+json",
            row_count=1,
            raw_payload=raw,
        )

    def validate_payload(self, _definition: object, _payload: object) -> ValidationResult:
        return ValidationResult(ok=True)


class _S3:
    def __init__(self) -> None:
        self.objects: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.objects.append(kwargs)


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.calls.append((query, parameters))


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def autocommit(self, _: bool) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        topx_env="prod",
        spaces_bucket="private-prod",
        spaces_prefix="governed",
    )


def test_routine_public_evidence_creates_candidate_not_source_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lyme_gap_atlas_data.source_evidence as evidence

    definition = load_source_definition(REPO / "config/sources/cdc_atsdr_svi_2022_county.yml")
    connection = _Connection()
    spaces = _S3()
    monkeypatch.setattr(evidence, "get_adapter", lambda _kind: _Adapter())

    result = collect_routine_public_source_evidence(
        definition,
        settings=_settings(),
        connection_factory=lambda: connection,
        spaces_client=spaces,
    )

    assert result["status"] == "PENDING_STEWARD_REVIEW"
    assert result["resource_key"] == "cdc_atsdr_svi_2022_county"
    assert len(spaces.objects) == 2
    rendered = "\n".join(query for query, _ in connection.cursor_instance.calls)
    assert "GOVERNANCE.CATALOG_RESOURCES" in rendered
    assert "GOVERNANCE.SOURCE_ACCESS_PROFILES" in rendered
    assert "GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS" in rendered
    assert "GOVERNANCE.SCHEMA_SNAPSHOTS" in rendered
    assert "GOVERNANCE.DATASET_QUALITY_ASSESSMENTS" in rendered
    assert "DATA_SOURCE_VERSIONS" not in rendered
    assert "MANUAL_REVIEW_DECISIONS" not in rendered
    assert "RAW.GOVERNED_SOURCE_RECORDS" not in rendered
    assert connection.committed


def test_routine_public_evidence_rejects_restricted_definition() -> None:
    definition = load_source_definition(REPO / "config/sources/cdc_tick_ixodes_county_status.yml")
    with pytest.raises(ValueError, match="ROUTINE_PUBLIC"):
        collect_routine_public_source_evidence(definition, settings=_settings())


def test_prod_admission_migration_is_narrow_and_production_only() -> None:
    migration = (
        REPO / "migrations/V086__prod_routine_public_semantic_source_admission.sql"
    ).read_text(encoding="utf-8")
    assert "cdc_atsdr_svi_2022_county" in migration
    assert "usda_ers_rucc_2023" in migration
    assert "cdc_tick_ixodes_county_status" not in migration
    assert "cdc_tick_ixodes_pathogen_status" not in migration
    assert "SP_RECORD_SOURCE_REVIEW_DECISION" in migration


def test_protected_evidence_workflow_is_narrow_and_never_ingests_rows() -> None:
    workflow = (REPO / ".github/workflows/capture-prod-routine-public-evidence.yml").read_text(
        encoding="utf-8"
    )
    assert "environment: production" in workflow
    assert 'ENABLE_PRODUCTION_EXECUTION: "true"' in workflow
    assert "cdc_atsdr_svi_2022_county.yml" in workflow
    assert "usda_ers_rucc_2023.yml" in workflow
    assert "capture-routine-public-evidence" in workflow
    assert "source run" not in workflow
