"""Adapter protocol and registry for simplified ingestion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .types import AdapterKind, SourceDefinition, ValidationIssue, ValidationResult


@dataclass
class AcquireResult:
    payload: Any
    artifact_sha256: str
    media_type: str
    row_count: int | None = None
    detail: dict[str, Any] | None = None


@dataclass
class NormalizeResult:
    records: list[dict[str, Any]]
    transformation_version: str
    detail: dict[str, Any] | None = None


class SourceAdapter(Protocol):
    kind: AdapterKind

    def acquire(
        self,
        definition: SourceDefinition,
        *,
        fixture_dir: Path | None = None,
    ) -> AcquireResult: ...

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult: ...

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult: ...


class SocrataAdapter:
    """Socrata SODA2 adapter for the x5j9 golden path."""

    kind = AdapterKind.SOCRATA

    def acquire(
        self,
        definition: SourceDefinition,
        *,
        fixture_dir: Path | None = None,
    ) -> AcquireResult:
        if fixture_dir is not None:
            sample_path = fixture_dir / "sample.json"
            metadata_path = fixture_dir / "metadata.json"
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            metadata = (
                json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata_path.exists()
                else {}
            )
            payload = {"metadata": metadata, "sample": sample}
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return AcquireResult(
                payload=payload,
                artifact_sha256=hashlib.sha256(body).hexdigest(),
                media_type="application/json",
                row_count=len(sample) if isinstance(sample, list) else None,
                detail={"source": "fixture"},
            )
        raise NotImplementedError(
            "Live Socrata acquisition runs through Tier B with network access; "
            "use fixture_dir for Tier A or call the legacy CDC client bridge."
        )

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        issues: list[ValidationIssue] = []
        sample = payload.get("sample") if isinstance(payload, dict) else payload
        if not isinstance(sample, list) or not sample:
            issues.append(
                ValidationIssue(
                    code="EMPTY_SAMPLE", message="Socrata sample must be a non-empty list"
                )
            )
            return ValidationResult(ok=False, issues=issues)
        first = sample[0]
        if not isinstance(first, dict):
            issues.append(ValidationIssue(code="ROW_SHAPE", message="Socrata rows must be objects"))
        return ValidationResult(ok=not issues, issues=issues)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        sample = payload.get("sample") if isinstance(payload, dict) else payload
        assert isinstance(sample, list)
        records = [
            {
                "source_id": definition.source_id,
                "dataset_id": definition.dataset_id,
                "source_definition_version": definition.definition_version,
                "geography_semantics": definition.geography_semantics,
                "temporal_semantics": definition.temporal_semantics,
                "record": row,
            }
            for row in sample
            if isinstance(row, dict)
        ]
        return NormalizeResult(
            records=records,
            transformation_version="socrata_normalize_v1",
            detail={"record_count": len(records)},
        )


class HttpXlsxAdapter:
    """HTTP XLSX adapter for tick surveillance and similar file sources."""

    kind = AdapterKind.HTTP_XLSX

    def acquire(
        self,
        definition: SourceDefinition,
        *,
        fixture_dir: Path | None = None,
    ) -> AcquireResult:
        if fixture_dir is not None:
            sample_path = fixture_dir / "sample.json"
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            body = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return AcquireResult(
                payload={"sample": sample},
                artifact_sha256=hashlib.sha256(body).hexdigest(),
                media_type="application/json",
                row_count=len(sample) if isinstance(sample, list) else None,
                detail={"source": "fixture", "workbook_sheet": definition.workbook_sheet},
            )
        raise NotImplementedError(
            "Live HTTP XLSX acquisition uses fixture_dir for Tier A; "
            "Tier B bridges to the tick surveillance collector."
        )

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        from .types import FailureCategory

        issues: list[ValidationIssue] = []
        sample = payload.get("sample") if isinstance(payload, dict) else payload
        if not isinstance(sample, list) or not sample:
            issues.append(
                ValidationIssue(
                    code="EMPTY_SAMPLE",
                    message="XLSX sample must be a non-empty list",
                    category=FailureCategory.SCHEMA,
                )
            )
            return ValidationResult(ok=False, issues=issues)
        first = sample[0]
        if not isinstance(first, dict):
            issues.append(
                ValidationIssue(
                    code="ROW_SHAPE",
                    message="XLSX rows must be objects",
                    category=FailureCategory.SCHEMA,
                )
            )
            return ValidationResult(ok=False, issues=issues)
        missing = [column for column in definition.required_columns if column not in first]
        if missing:
            issues.append(
                ValidationIssue(
                    code="MISSING_COLUMNS",
                    message=f"Missing required columns: {', '.join(missing)}",
                    category=FailureCategory.SCHEMA,
                )
            )
        return ValidationResult(ok=not issues, issues=issues)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        sample = payload.get("sample") if isinstance(payload, dict) else payload
        assert isinstance(sample, list)
        records = [
            {
                "source_id": definition.source_id,
                "dataset_id": definition.dataset_id,
                "source_definition_version": definition.definition_version,
                "geography_semantics": definition.geography_semantics,
                "temporal_semantics": definition.temporal_semantics,
                "record": row,
            }
            for row in sample
            if isinstance(row, dict)
        ]
        return NormalizeResult(
            records=records,
            transformation_version="http_xlsx_normalize_v1",
            detail={"record_count": len(records)},
        )


_REGISTRY: dict[AdapterKind, SourceAdapter] = {
    AdapterKind.SOCRATA: SocrataAdapter(),
    AdapterKind.HTTP_XLSX: HttpXlsxAdapter(),
}


def get_adapter(kind: AdapterKind) -> SourceAdapter:
    try:
        return _REGISTRY[kind]
    except KeyError as error:
        raise ValueError(
            f"Unsupported adapter_kind={kind!s}. Extend the registry with an explicit "
            "adapter module rather than encoding source logic in workflow YAML."
        ) from error
