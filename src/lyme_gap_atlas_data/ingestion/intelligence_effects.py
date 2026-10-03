"""Intelligence effects injected into the existing ingestion orchestrator.

Composition remains disabled until policy/migration/source approvals are real.
Scientific RAW/STAGING/CONFORMED and county observation writes are never used.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ..intelligence_items import identity_hash, validate_acquisition_context, validate_record
from ..intelligence_metadata import NativeMetadataPolicy
from ..intelligence_storage import IntelligenceStore
from ..settings import PipelineSettings
from .adapters import AcquireResult
from .runtime import SnowflakeStageEffects
from .types import AdapterKind, RunState, SourceDefinition


class IntelligenceStageEffects(SnowflakeStageEffects):
    def __init__(
        self,
        settings: PipelineSettings | None = None,
        *,
        connection_factory: Callable[[], Any],
        retention_allowed: Callable[[str], bool],
        artifact_policy_allowed: Callable[[str, str], bool],
        native_policy_lookup: Callable[[str, int], NativeMetadataPolicy] | None = None,
        spaces_client: Any | None = None,
    ) -> None:
        super().__init__(
            settings, connection_factory=connection_factory, spaces_client=spaces_client
        )
        self.store = IntelligenceStore(
            connection_factory=connection_factory,
            retention_allowed=retention_allowed,
            native_policy_lookup=native_policy_lookup,
            settings=self.settings,
        )
        self.artifact_policy_allowed = artifact_policy_allowed

    @staticmethod
    def _definition(definition: SourceDefinition) -> dict[str, Any]:
        source = definition.extra.get("intelligence_registry")
        if (
            definition.adapter_kind is not AdapterKind.RSS_ATOM
            or definition.destination != "PRESENTATION.INTELLIGENCE_FEED_V"
            or definition.quality_rules
            or not isinstance(source, dict)
        ):
            raise PermissionError("INTELLIGENCE_EFFECTS_DEFINITION_REQUIRED")
        validate_record("source", source)
        if (
            definition.resource_key != source["source_id"]
            or definition.source_id != source["source_id"]
        ):
            raise PermissionError("INTELLIGENCE_EFFECTS_DEFINITION_REQUIRED")
        return source

    def register_artifact(
        self, definition: SourceDefinition, state: RunState, acquired: AcquireResult
    ) -> dict[str, Any]:
        source = self._definition(definition)
        context = acquired.payload.get("source_context")
        validate_acquisition_context(
            source, definition.resource_key, definition.endpoint_template, context
        )
        if (
            context["artifact_sha256"] != acquired.artifact_sha256
            or acquired.payload.get("fetched_at") != context["fetched_at"]
        ):
            raise PermissionError("INTELLIGENCE_ARTIFACT_RETENTION_REQUIRED")
        approved = self.store.lookup_source(source["source_id"], source["registry_version"])
        if approved != source or not self.artifact_policy_allowed(
            source["access_use"]["content_retention_policy_ref"], definition.artifact_policy
        ):
            raise PermissionError("INTELLIGENCE_ARTIFACT_RETENTION_REQUIRED")
        receipt = self._register_artifact(
            definition, state, acquired, capture_identity=identity_hash(context)
        )
        self.store.record_acquisition(
            source_id=source["source_id"],
            registry_version=source["registry_version"],
            resource_key=definition.resource_key,
            run_id=state.ingestion_run_id,
            artifact_id=receipt["artifact_id"],
            context=context,
        )
        return receipt

    def materialize_normalized(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._definition(definition)
        for item in records:
            validate_record("item", item)
        return {"record_count": len(records), "wrote": False, "mode": "validated_intelligence"}

    def load(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        source = self._definition(definition)
        receipt = self.store.write(
            source_id=source["source_id"],
            registry_version=source["registry_version"],
            resource_key=definition.resource_key,
            run_id=state.ingestion_run_id,
            items=records,
        )
        return {
            "record_count": len(records),
            "revisions_inserted": receipt.revisions_inserted,
            "captures_inserted": receipt.captures_inserted,
            "captures_replayed": receipt.captures_replayed,
            "wrote": bool(receipt.captures_inserted),
            "mode": "atomic_intelligence",
        }

    def quality(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.materialize_normalized(definition, state, records)
        return {"rules_evaluated": ["intelligence-v1-contract-and-lineage"], "wrote": False}

    def quality_partitioned(
        self, definition: SourceDefinition, state: RunState, records: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        raise PermissionError("INTELLIGENCE_PARTITIONED_EFFECTS_UNSUPPORTED")

    def publish(
        self, definition: SourceDefinition, state: RunState, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._definition(definition)
        return {
            "target_relation": "PRESENTATION.INTELLIGENCE_FEED_V",
            "record_count": len(records),
            "wrote": False,
            "status": "APPROVED_PROJECTION",
            "publication_protected": self.settings.topx_env == "prod",
        }

    def publish_partitioned(
        self, definition: SourceDefinition, state: RunState, record_count: int
    ) -> dict[str, Any]:
        raise PermissionError("INTELLIGENCE_PARTITIONED_EFFECTS_UNSUPPORTED")
