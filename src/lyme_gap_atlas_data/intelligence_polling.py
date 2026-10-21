"""Prepare a frozen daily source selection for the existing ingestion runner.

No scheduler deployment, source approval, policy creation or warehouse writes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from .ingestion.types import AdapterKind, SourceDefinition
from .intelligence_items import canonical_url, identity_hash, validate_record

DAILY_POLL_SECONDS = 86_400


def run_production_daily(*, preflight_only: bool = False) -> dict[str, Any]:
    """Run each exact accepted active source once per UTC day, without retries.

    This is a bounded entry point for the existing DigitalOcean job platform,
    not a scheduler. Disabled execution performs no warehouse/provider I/O.
    """
    from .ingestion.intelligence_checkpoints import IntelligenceSnowflakeCheckpoints
    from .ingestion.intelligence_runtime import (
        PROD_DAILY_SOURCE_SHA256,
        PROD_SOURCE_DEFINITIONS,
        canonical_pilot,
        pilot_watchdog,
    )
    from .ingestion.source_definition import load_source_definition
    from .ingestion.types import RunStatus, Tier
    from .settings import PipelineSettings

    settings = PipelineSettings()
    if not settings.intelligence_daily_enabled:
        return {"status": "DISABLED", "sources": [], "provider_requests": 0}
    if settings.topx_env != "prod":
        raise PermissionError("INTELLIGENCE_DAILY_PROD_REQUIRED")
    day = datetime.now(UTC).date().isoformat()
    results = []
    for source_id, path in PROD_SOURCE_DEFINITIONS.items():
        try:
            with pilot_watchdog():
                orchestrator, definition = canonical_pilot(load_source_definition(Path(path)))
                source = definition.extra["intelligence_registry"]
                if source["state"] != "active":
                    results.append({"source_id": source_id, "outcome": "SCHEDULE_SUPPRESSED"})
                    continue
                if (
                    source["registry_version"] != 2
                    or source["cadence"]["poll_seconds"] != DAILY_POLL_SECONDS
                    or identity_hash(source) != PROD_DAILY_SOURCE_SHA256[source_id]
                ):
                    raise PermissionError("INTELLIGENCE_DAILY_ACTIVE_SOURCE_REQUIRED")
                if preflight_only:
                    results.append({"source_id": source_id, "outcome": "READY"})
                    continue
                run_id = str(uuid5(NAMESPACE_URL, f"atlas:intelligence:daily:{source_id}:{day}"))
                if not cast(IntelligenceSnowflakeCheckpoints, orchestrator.store).claim_daily_run(
                    run_id, source_id, PROD_DAILY_SOURCE_SHA256[source_id]
                ):
                    results.append({"source_id": source_id, "outcome": "ALREADY_CLAIMED"})
                    continue
                state = orchestrator.run(definition, tier=Tier.C, run_id=run_id)
                results.append(
                    {
                        "source_id": source_id,
                        "run_id": run_id,
                        "outcome": "SUCCEEDED" if state.status is RunStatus.SUCCEEDED else "FAILED",
                    }
                )
        except Exception:
            # Actual stage codes remain in the existing canonical checkpoint.
            # Never emit raw SDK/credential/provider exceptions in job output.
            results.append({"source_id": source_id, "outcome": "PREFLIGHT_OR_RUNTIME_FAILED"})
    failed = any(row["outcome"] in {"FAILED", "PREFLIGHT_OR_RUNTIME_FAILED"} for row in results)
    if preflight_only and any(row["outcome"] != "READY" for row in results):
        failed = True
    return {
        "status": "FAILED" if failed else "SUCCEEDED",
        "day": day,
        "preflight_only": preflight_only,
        "sources": results,
    }


@dataclass(frozen=True)
class PollPreparation:
    source_id: str
    outcome: str
    definition: SourceDefinition | None = None


def prepare_daily_sources(
    selection: dict[str, Any],
    *,
    expected_selection_sha256: str,
    registry_versions: dict[str, int],
    registry_lookup: Callable[[str, int], dict[str, Any]],
    retention_allowed: Callable[[str], bool],
    artifact_policy: str,
) -> list[PollPreparation]:
    """Prepare each eligible source independently, preserving explicit deferrals.

    The trusted caller supplies the reviewed selection digest, authoritative
    registry lookup and actual retention policy. Selection is not activation.
    Policy failures on one source do not prevent preparation of another source.
    """
    if (
        identity_hash(selection) != expected_selection_sha256
        or selection.get("contract_version") != "intelligence-selection-v1"
        or selection.get("poll_seconds") != DAILY_POLL_SECONDS
        or not artifact_policy
    ):
        raise ValueError("INTELLIGENCE_SELECTION_INVALID")
    entries = selection.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("INTELLIGENCE_SELECTION_INVALID")
    ids = [entry.get("source_id") for entry in entries if isinstance(entry, dict)]
    if (
        len(ids) != len(entries)
        or any(not isinstance(source_id, str) or not source_id for source_id in ids)
        or len(set(ids)) != len(ids)
        or any(entry.get("decision") not in {"approved", "deferred"} for entry in entries)
    ):
        raise ValueError("INTELLIGENCE_SELECTION_INVALID")
    prepared = []
    for entry in entries:
        source_id = entry["source_id"]
        if entry["decision"] == "deferred":
            prepared.append(PollPreparation(source_id, "DEFERRED"))
            continue
        endpoint = entry.get("fetch_location")
        if not endpoint:
            prepared.append(PollPreparation(source_id, "ENDPOINT_UNRESOLVED"))
            continue
        version = registry_versions.get(source_id)
        if type(version) is not int or version < 1:
            prepared.append(PollPreparation(source_id, "REGISTRY_UNRESOLVED"))
            continue
        try:
            source = json.loads(json.dumps(registry_lookup(source_id, version)))
            validate_record("source", source)
            if (
                source["source_id"] != source_id
                or source["registry_version"] != version
                or source["state"] != "active"
                or source["transport"] not in {"rss", "atom"}
                or canonical_url(source["fetch_location"]) != canonical_url(endpoint)
                or source["cadence"]["poll_seconds"] != DAILY_POLL_SECONDS
                or source["approval"]["status"] != "approved"
                or source["trust_review"]["status"] != "approved"
            ):
                prepared.append(PollPreparation(source_id, "REGISTRY_POLICY_MISMATCH"))
                continue
            policy_ref = source["access_use"]["content_retention_policy_ref"]
            if not policy_ref or not retention_allowed(policy_ref):
                prepared.append(PollPreparation(source_id, "RETENTION_UNRESOLVED"))
                continue
        except Exception:
            # External lookup failures must not expose provider or warehouse text.
            prepared.append(PollPreparation(source_id, "REGISTRY_LOOKUP_FAILED"))
            continue
        definition = SourceDefinition(
            resource_key=source_id,
            source_id=source_id,
            dataset_id=source_id,
            definition_version=version,
            adapter_kind=AdapterKind.RSS_ATOM,
            endpoint_template=endpoint,
            deterministic_order_clause="publisher_document_order",
            incremental_strategy="CONTENT_REVISION",
            geography_semantics="Publication; no inferred geography",
            temporal_semantics="Publisher chronology; missing remains unknown",
            artifact_policy=artifact_policy,
            destination="PRESENTATION.INTELLIGENCE_FEED_V",
            expected_refresh_cadence="P1D",
            extra={"intelligence_registry": source},
        )
        prepared.append(PollPreparation(source_id, "READY", definition))
    return prepared
