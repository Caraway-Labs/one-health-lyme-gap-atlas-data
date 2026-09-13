"""Simplified ingestion types for Epic #223."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class AdapterKind(StrEnum):
    SOCRATA = "socrata"
    HTTP_XLSX = "http_xlsx"


class AuthMode(StrEnum):
    NONE = "none"
    APP_TOKEN_ENV = "app_token_env"


class Stage(StrEnum):
    DISCOVER = "DISCOVER"
    ACQUIRE = "ACQUIRE"
    VALIDATE = "VALIDATE"
    NORMALIZE = "NORMALIZE"
    LOAD = "LOAD"
    QUALITY = "QUALITY"
    PUBLISH_STAGE = "PUBLISH_STAGE"


class StageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXCEPTION_REVIEW = "EXCEPTION_REVIEW"
    OPERATOR_INTERVENTION = "OPERATOR_INTERVENTION"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    PAUSED = "PAUSED"


class FailureCategory(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    ACQUISITION = "ACQUISITION"
    POLICY_LICENSE = "POLICY_LICENSE"
    SCHEMA = "SCHEMA"
    NORMALIZATION = "NORMALIZATION"
    WAREHOUSE = "WAREHOUSE"
    QUALITY = "QUALITY"
    PROVIDER_MODEL = "PROVIDER_MODEL"
    GRAPH = "GRAPH"
    DEPLOYMENT = "DEPLOYMENT"
    PERMISSION = "PERMISSION"
    PROCESS = "PROCESS"


DEFAULT_SOCRATA_STAGES: tuple[Stage, ...] = (
    Stage.ACQUIRE,
    Stage.VALIDATE,
    Stage.NORMALIZE,
    Stage.LOAD,
    Stage.QUALITY,
    Stage.PUBLISH_STAGE,
)

DEFAULT_HTTP_XLSX_STAGES: tuple[Stage, ...] = (
    Stage.ACQUIRE,
    Stage.VALIDATE,
    Stage.NORMALIZE,
    Stage.LOAD,
    Stage.QUALITY,
    Stage.PUBLISH_STAGE,
)


@dataclass(frozen=True)
class QualityRule:
    rule_id: str
    severity: str


@dataclass(frozen=True)
class SourceDefinition:
    resource_key: str
    definition_version: int
    adapter_kind: AdapterKind
    endpoint_template: str
    deterministic_order_clause: str
    incremental_strategy: str
    geography_semantics: str
    temporal_semantics: str
    source_id: str = ""
    dataset_id: str = ""
    metadata_endpoint_template: str | None = None
    auth_mode: AuthMode = AuthMode.NONE
    restrictions: tuple[str, ...] = ()
    artifact_policy: str = "PUBLIC_SEVEN_YEAR"
    quality_rules: tuple[QualityRule, ...] = ()
    destination: str = ""
    expected_refresh_cadence: str = ""
    stages: tuple[Stage, ...] = DEFAULT_SOCRATA_STAGES
    required_columns: tuple[str, ...] = ()
    workbook_sheet: str | None = None
    header_row: int | None = None
    maximum_workbook_bytes: int | None = None
    maximum_rows: int | None = None
    page_size: int = 5_000
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id:
            object.__setattr__(self, "source_id", self.resource_key)
        if not self.dataset_id:
            object.__setattr__(self, "dataset_id", self.resource_key)


@dataclass
class StageCheckpoint:
    stage: Stage
    status: StageStatus
    attempt_count: int = 0
    artifact_id: str | None = None
    artifact_sha256: str | None = None
    transformation_version: str | None = None
    failure_category: FailureCategory | None = None
    redacted_diagnostic_code: str | None = None
    next_action: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class RunState:
    ingestion_run_id: str
    resource_key: str
    source_definition_version: int
    tier: Tier
    status: RunStatus
    stages: list[StageCheckpoint] = field(default_factory=list)
    next_action: str | None = None
    dry_run: bool = False

    def checkpoint(self, stage: Stage) -> StageCheckpoint | None:
        for item in self.stages:
            if item.stage == stage:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingestion_run_id": self.ingestion_run_id,
            "resource_key": self.resource_key,
            "source_definition_version": self.source_definition_version,
            "tier": self.tier.value,
            "status": self.status.value,
            "next_action": self.next_action,
            "dry_run": self.dry_run,
            "stages": [
                {
                    "stage": checkpoint.stage.value,
                    "status": checkpoint.status.value,
                    "attempt_count": checkpoint.attempt_count,
                    "artifact_id": checkpoint.artifact_id,
                    "artifact_sha256": checkpoint.artifact_sha256,
                    "transformation_version": checkpoint.transformation_version,
                    "failure_category": (
                        checkpoint.failure_category.value if checkpoint.failure_category else None
                    ),
                    "redacted_diagnostic_code": checkpoint.redacted_diagnostic_code,
                    "next_action": checkpoint.next_action,
                    "detail": checkpoint.detail,
                    "started_at": checkpoint.started_at,
                    "completed_at": checkpoint.completed_at,
                }
                for checkpoint in self.stages
            ],
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    category: FailureCategory = FailureCategory.CONFIGURATION


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [
                {"code": issue.code, "message": issue.message, "category": issue.category.value}
                for issue in self.issues
            ],
        }
