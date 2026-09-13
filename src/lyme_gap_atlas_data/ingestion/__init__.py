"""Simplified ingestion package (Epic #223)."""

from .adapters import HttpXlsxAdapter, SocrataAdapter, get_adapter
from .checkpoints import FileCheckpointStore, InMemoryCheckpointStore, SnowflakeCheckpointStore
from .failures import explain_run
from .literature_queue import LiteratureStage, LiteratureWorkQueue
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
    "FailureCategory",
    "FileCheckpointStore",
    "HttpXlsxAdapter",
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
    "get_adapter",
    "load_source_definition",
    "starter_definition_yaml",
    "validate_source_definition",
]
