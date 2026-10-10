"""Small governed feed composition on the canonical ingestion state machine.

Source selection is not a registry approval or a native-metadata/retention rights
grant. Reviewed receipts are pinned to a real registry checksum.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from ..intelligence_items import identity_hash
from ..intelligence_metadata import NativeMetadataPolicy
from ..intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from ..settings import PipelineSettings
from ..sql_sessions import connect
from .adapters import AcquireResult, NormalizeResult
from .intelligence_checkpoints import IntelligenceSnowflakeCheckpoints
from .intelligence_effects import IntelligenceStageEffects
from .intelligence_feed import FeedResponse, IntelligenceFeedAdapter, _request, _resolve
from .orchestrator import IngestionOrchestrator
from .types import AdapterKind, SourceDefinition

ENDPOINTS = {
    "cdc-eid-expedited": "https://wwwnc.cdc.gov/eid/rss/expedited.xml",
    "cdc-vital-signs": "https://tools.cdc.gov/api/v2/resources/media/275866.rss",
    "nih-news-releases": "https://www.nih.gov/news-releases/feed.xml",
}
RECEIPTS = Path("config/intelligence/pilot-policy-receipts.json")
PROD_EID_SHA256 = "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4"


@contextmanager
def pilot_watchdog(*, seconds: int = 300) -> Iterator[None]:
    """Stop the owned CLI at its deadline, including blocked SDK calls.

    Covers connection setup, implicit transaction SQL and Spaces operations
    which cannot all be intercepted by the cursor wrapper. No other process,
    warehouse or session is cancelled. The feed default is five minutes; the
    exact prerequisite batch uses fifty seconds.
    """
    timer = threading.Timer(seconds, os._exit, args=(124,))
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


@contextmanager
def prerequisite_batch_deadline() -> Iterator[None]:
    """Bound the exact reviewed DEV feed batch, including all connections/cleanup.

    Reuse the SQL-session limit surface; no new identity or warehouse changes.
    The process exits independently of evidence I/O. Server statements may have
    a bounded tail after process exit; DDL is not transactional or rolled back.
    """
    with pilot_watchdog(seconds=50):
        previous = os.environ.get("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS")
        existing_timeout = int(previous) if previous is not None else 10
        if not 1 <= existing_timeout <= 60:
            raise ValueError("Invalid existing SQL statement timeout")
        os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] = str(min(existing_timeout, 10))
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", None)
            else:
                os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] = previous


def verify_prerequisite_identity(settings: SnowflakeSettings) -> None:
    """Verify the protected service inside the prerequisite process/session caps."""
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        if tuple(cursor.fetchone()) != (
            "OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
            "OH_LYME_DEV_MIGRATION_DEPLOYER",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        ):
            raise PermissionError("INTELLIGENCE_PREREQUISITE_IDENTITY")


class PilotBudget:
    """One invocation, one complete feed request, five minutes of owned work.

    This bounds work; it is not an invoice or an account-wide spending limiter.
    Operators track the approved six-request/$5 aggregate across invocations.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.deadline = clock() + 300
        self.requests = 0
        self.queries = 0

    def remaining(self) -> float:
        seconds = self.deadline - self.clock()
        if seconds <= 0:
            raise PermissionError("INTELLIGENCE_PILOT_DEADLINE")
        return seconds

    def request(
        self,
        sender: Callable[..., FeedResponse],
        url: str,
        address: str,
        headers: dict[str, str],
        maximum_bytes: int,
        timeout: float,
    ) -> FeedResponse:
        remaining = self.remaining()
        if self.requests >= 1:
            raise PermissionError("INTELLIGENCE_PILOT_REQUEST_LIMIT")
        self.requests += 1
        response = sender(
            url,
            address,
            headers,
            min(maximum_bytes, 2 * 1024 * 1024),
            min(timeout, 30, remaining),
        )
        self.remaining()
        if response.status != 200 or len(response.body) > 2 * 1024 * 1024:
            # No redirects, retries, conditional bodies, or partial acceptance.
            raise PermissionError("INTELLIGENCE_PILOT_RESPONSE_REQUIRED")
        return response


class _Cursor:
    def __init__(self, cursor: Any, budget: PilotBudget) -> None:
        self.raw, self.budget = cursor, budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def __enter__(self) -> _Cursor:
        self.raw.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self.raw.__exit__(*args)

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        remaining = self.budget.remaining()
        if self.budget.queries >= 2500:
            raise PermissionError("INTELLIGENCE_PILOT_QUERY_LIMIT")
        self.budget.queries += 1
        # Existing stores set a 120-second session limit. Preserve their other
        # settings, but keep implicit connector transaction SQL bounded too.
        statement = re.sub(
            r"STATEMENT_TIMEOUT_IN_SECONDS\s*=\s*\d+",
            f"STATEMENT_TIMEOUT_IN_SECONDS={min(30, math.ceil(remaining))}",
            statement,
            flags=re.IGNORECASE,
        )
        # Connector cancellation is for this owned query, never the warehouse.
        kwargs["timeout"] = min(kwargs.get("timeout", 30), 30, math.ceil(remaining))
        result = self.raw.execute(statement, *args, **kwargs)
        self.budget.remaining()
        return result


class _Connection:
    def __init__(self, connection: Any, budget: PilotBudget) -> None:
        self.raw, self.budget = connection, budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def cursor(self, *args: Any, **kwargs: Any) -> _Cursor:
        self.budget.remaining()
        return _Cursor(self.raw.cursor(*args, **kwargs), self.budget)

    def commit(self) -> Any:
        return self._transaction("commit")

    def rollback(self) -> Any:
        return self._transaction("rollback")

    def autocommit(self, value: bool) -> Any:
        return self._transaction("autocommit", value)

    def _transaction(self, operation: str, *args: Any) -> Any:
        self.budget.remaining()
        if self.budget.queries >= 2500:
            raise PermissionError("INTELLIGENCE_PILOT_QUERY_LIMIT")
        self.budget.queries += 1
        result = getattr(self.raw, operation)(*args)
        self.budget.remaining()
        return result


class PilotFeedAdapter(IntelligenceFeedAdapter):
    """Reject the complete source if it exceeds the small-pass bounds."""

    def _retained_entries(self, definition: SourceDefinition, payload: Any) -> list[dict[str, Any]]:
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("xml_base64"), str)
            and len(payload["xml_base64"]) > 4 * math.ceil(2 * 1024 * 1024 / 3)
        ):
            raise PermissionError("INTELLIGENCE_PILOT_REPLAY_LIMIT")
        entries = super()._retained_entries(definition, payload)
        if len(entries) > 250:
            raise PermissionError("INTELLIGENCE_PILOT_ITEM_LIMIT")
        return entries

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        acquired = super().acquire(definition, fixture_dir=fixture_dir)
        if acquired.row_count is None or acquired.row_count > 250:
            raise PermissionError("INTELLIGENCE_PILOT_ITEM_LIMIT")
        return acquired

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        normalized = super().normalize(definition, payload)
        if len(normalized.records) > 250:
            raise PermissionError("INTELLIGENCE_PILOT_ITEM_LIMIT")
        if len(json.dumps(normalized.records).encode()) > 1024 * 1024:
            raise PermissionError("INTELLIGENCE_PILOT_NORMALIZED_LIMIT")
        return normalized


def compose_pilot(
    definition: SourceDefinition,
    *,
    receipts: list[dict[str, Any]],
    connection_factory: Callable[[], Any],
    settings: PipelineSettings,
    budget: PilotBudget | None = None,
) -> tuple[IngestionOrchestrator, SourceDefinition]:
    """Assemble existing runtime components; perform no approval or schema DDL."""
    if settings.topx_env not in {"dev", "prod"}:
        raise PermissionError("INTELLIGENCE_PILOT_ENVIRONMENT_REQUIRED")
    environment: Literal["DEV", "PROD"] = "PROD" if settings.topx_env == "prod" else "DEV"
    if environment == "PROD":
        endpoint = urlsplit(settings.spaces_endpoint)
        if (
            definition.source_id != "cdc-eid-expedited"
            or settings.spaces_bucket != "one-health-lyme-gap-atlas-data-prod"
            or settings.spaces_prefix != "prod"
            or settings.spaces_region != "sfo3"
            or endpoint.scheme != "https"
            or endpoint.hostname != "sfo3.digitaloceanspaces.com"
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
        ):
            raise PermissionError("INTELLIGENCE_PROD_STORAGE_SCOPE_REQUIRED")
    if (
        definition.adapter_kind is not AdapterKind.RSS_ATOM
        or definition.source_id != definition.resource_key
        or ENDPOINTS.get(definition.source_id) != definition.endpoint_template
        or definition.destination != "PRESENTATION.INTELLIGENCE_FEED_V2"
        or definition.quality_rules
    ):
        raise PermissionError("INTELLIGENCE_PILOT_DEFINITION_REQUIRED")
    selected = [receipt for receipt in receipts if receipt.get("source_id") == definition.source_id]
    if len(selected) != 1:
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_POLICY_REQUIRED")
    receipt = selected[0]
    if not receipt.get("decision_ref") or not receipt.get("raw_policy_ref"):
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_POLICY_REQUIRED")
    if environment == "PROD" and (
        receipt["registry_version"] != 1
        or receipt["source_sha256"] != PROD_EID_SHA256
        or receipt["decision_ref"] != "DATA-132-135-EID-ADMISSION-2026-10-09"
        or receipt["raw_policy_ref"] != "intelligence-raw-30d-v1"
        or receipt["artifact_policy"] != "CDC_EID_RESTRICTED_RAW_30D_V1"
    ):
        raise PermissionError("INTELLIGENCE_PROD_REVIEWED_EID_REQUIRED")
    native = NativeMetadataPolicy(
        **{
            **receipt["native_policy"],
            **{
                key: frozenset(receipt["native_policy"][key])
                for key in ("inventory", "permitted_paths", "required_paths")
            },
        }
    )
    if environment == "PROD" and (
        native.policy_ref != "cdc-eid-expedited-native-metadata-v1"
        or native.permitted_paths
        != frozenset(
            {
                "feed/language",
                "feed/link",
                "feed/title",
                "item/link",
                "item/pubDate",
                "item/title",
            }
        )
        or native.updated_path is not None
        or native.published_path != "item/pubDate"
        or native.published_format != "rfc822"
    ):
        raise PermissionError("INTELLIGENCE_PROD_NATIVE_POLICY_REQUIRED")
    budget = budget or PilotBudget()

    @contextmanager
    def factory() -> Iterator[Any]:
        budget.remaining()
        with connection_factory() as raw:
            connection = _Connection(raw, budget)
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30, "
                    "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=5, ABORT_DETACHED_QUERY=TRUE"
                )
                cursor.execute(
                    "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
                )
                if cursor.fetchall() != [
                    (
                        f"OH_LYME_{environment}_PIPELINE_SVC",
                        f"OH_LYME_{environment}_RUNTIME",
                        f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}",
                        f"OH_LYME_{environment}_INGEST_XS_WH",
                    )
                ]:
                    raise PermissionError("INTELLIGENCE_PILOT_RUNTIME_CONTEXT_REQUIRED")
            yield connection

    policy_ref = receipt["retention_policy_ref"]
    effects = IntelligenceStageEffects(
        settings,
        connection_factory=factory,
        retention_allowed=lambda ref: ref == policy_ref,
        artifact_policy_allowed=lambda ref, artifact: (
            ref == policy_ref and artifact == receipt["artifact_policy"]
        ),
        native_policy_lookup=lambda sid, version: native,
    )
    source = effects.store.lookup_latest_source(definition.source_id)
    if environment == "PROD" and (
        source["access_use"]["public_excerpt_permitted"]
        or source["access_use"]["excerpt_max_chars"] != 0
    ):
        raise PermissionError("INTELLIGENCE_PROD_METADATA_ONLY_REQUIRED")
    if (
        source["registry_version"] != receipt["registry_version"]
        or identity_hash(source) != receipt["source_sha256"]
        or source["fetch_location"] != definition.endpoint_template
    ):
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_SOURCE_REQUIRED")
    native.validate(source)
    definition = replace(
        definition,
        definition_version=source["registry_version"],
        artifact_policy=receipt["artifact_policy"],
        extra={"intelligence_registry": source},
    )
    retention = FeedRawRetention(
        SnowflakeRawLedger(factory, environment),
        environment=environment,
        source_lookup=effects.store.lookup_source,
        policy_lookup=lambda selected_source: receipt["raw_policy_ref"],
    )
    effects.feed_retention = retention
    adapter = PilotFeedAdapter(
        registry_lookup=effects.store.lookup_source,
        retention_allowed=lambda ref: ref == policy_ref,
        native_policy_lookup=lambda sid, version: native,
        feed_retention=retention,
        request=lambda *args: budget.request(_request, *args),
        resolve=lambda host, timeout: _resolve(host, min(timeout, 30, budget.remaining())),
    )
    checkpoints = IntelligenceSnowflakeCheckpoints(retention, connection_factory=factory)
    return IngestionOrchestrator(store=checkpoints, adapter=adapter, effects=effects), definition


def canonical_pilot(definition: SourceDefinition) -> tuple[IngestionOrchestrator, SourceDefinition]:
    """Called by existing source run, using existing environment credentials."""
    receipts = json.loads(RECEIPTS.read_text(encoding="utf-8"))["receipts"]
    settings = PipelineSettings()
    return compose_pilot(
        definition,
        receipts=receipts,
        settings=settings,
        connection_factory=lambda: connect(SnowflakeSettings()),
    )
