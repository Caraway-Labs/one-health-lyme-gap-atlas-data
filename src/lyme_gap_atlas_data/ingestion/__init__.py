"""Simplified ingestion package (Epic #223)."""

from .adapters import AcquisitionArtifact, HttpXlsxAdapter, SocrataAdapter, get_adapter
from .checkpoints import FileCheckpointStore, InMemoryCheckpointStore, SnowflakeCheckpointStore
from .failures import explain_run
from .identity import (
    IdentityAssessment,
    assess_identity,
    canonical_source_row,
    deterministic_record_id,
    identity_strategy,
    publisher_record_id,
    source_row_hash,
)
from .literature_queue import LiteratureStage, LiteratureWorkQueue
from .neon_release_package import NeonReleasePackageAdapter
from .orchestrator import IngestionOrchestrator
from .runtime import NoopStageEffects, QualityFailure, SnowflakeStageEffects, evaluate_quality_rules
from .source_definition import (
    load_source_definition,
    starter_definition_yaml,
    validate_source_definition,
)
from .types import (
    AdapterKind,
    FailureCategory,
    RunState,
    SourceDefinition,
    Stage,
    StageStatus,
    Tier,
)

__all__ = [
    "AdapterKind",
    "AcquisitionArtifact",
    "FailureCategory",
    "FileCheckpointStore",
    "HttpXlsxAdapter",
    "NeonReleasePackageAdapter",
    "InMemoryCheckpointStore",
    "SnowflakeCheckpointStore",
    "IngestionOrchestrator",
    "LiteratureStage",
    "LiteratureWorkQueue",
    "NoopStageEffects",
    "QualityFailure",
    "RunState",
    "SocrataAdapter",
    "SourceDefinition",
    "Stage",
    "StageStatus",
    "Tier",
    "SnowflakeStageEffects",
    "evaluate_quality_rules",
    "explain_run",
    "IdentityAssessment",
    "assess_identity",
    "canonical_source_row",
    "deterministic_record_id",
    "get_adapter",
    "identity_strategy",
    "load_source_definition",
    "starter_definition_yaml",
    "publisher_record_id",
    "source_row_hash",
    "validate_source_definition",
]
