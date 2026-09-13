"""Simplified ingestion package (Epic #223)."""

from .adapters import HttpXlsxAdapter, SocrataAdapter, get_adapter
from .checkpoints import FileCheckpointStore, InMemoryCheckpointStore
from .failures import explain_run
from .literature_queue import LiteratureStage, LiteratureWorkQueue
from .orchestrator import IngestionOrchestrator
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
    "IngestionOrchestrator",
    "LiteratureStage",
    "LiteratureWorkQueue",
    "RunState",
    "SocrataAdapter",
    "SourceDefinition",
    "Stage",
    "StageStatus",
    "Tier",
    "explain_run",
    "get_adapter",
    "load_source_definition",
    "starter_definition_yaml",
    "validate_source_definition",
]
