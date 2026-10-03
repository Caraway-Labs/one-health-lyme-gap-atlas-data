"""Prepare a frozen daily source selection for the existing ingestion runner.

No scheduler deployment, source approval, policy creation or warehouse writes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .ingestion.types import AdapterKind, SourceDefinition
from .intelligence_items import canonical_url, identity_hash, validate_record

DAILY_POLL_SECONDS = 86_400


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
