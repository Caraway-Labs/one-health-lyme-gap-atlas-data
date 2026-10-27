"""Small governed feed composition on the canonical ingestion state machine.

Source selection is not a registry approval or a native-metadata/retention rights
grant. Reviewed receipts are pinned to a real registry checksum.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from ..intelligence_activations import (
    fetch_activations,
    load_registry_documents,
    source_is_active,
)
from ..intelligence_daily_telemetry import instrumented_execute
from ..intelligence_items import identity_hash
from ..intelligence_metadata import NativeMetadataPolicy
from ..intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from ..intelligence_retention import PROD_METADATA_FEED_IDS
from ..intelligence_topics import (
    VOCABULARY_VERSION_V1,
    TopicRow,
    load_vocabulary,
    merge_topic_rows,
    topic_rows_for_items,
    topics_table_exists,
)
from ..settings import PipelineSettings
from ..sql_sessions import connect
from .adapters import AcquireResult, NormalizeResult
from .intelligence_checkpoints import IntelligenceSnowflakeCheckpoints
from .intelligence_effects import IntelligenceStageEffects
from .intelligence_feed import FeedResponse, IntelligenceFeedAdapter, _request, _resolve
from .orchestrator import IngestionOrchestrator
from .step_deadline import active_step_deadline, note_step_deadline
from .types import AdapterKind, SourceDefinition

logger = logging.getLogger(__name__)
TOPICS_FLAG = "ATLAS_INTELLIGENCE_TOPICS"


def record_topics_after_merge(
    cursor: Any,
    items: list[dict[str, Any]],
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Assign vocabulary topics after the item MERGE.

    The hook does nothing when the topic table is absent and the explicit flag
    is off, so a daily run can promote before the table migration. An oversized
    field, a badly typed field, or a bad vocabulary leaves that item without
    topics and counts a warning. The hook does not raise.
    """
    flag = enabled if enabled is not None else os.environ.get(TOPICS_FLAG, "").lower() == "on"
    if not items:
        return {"status": "inert", "reason": "no_items", "rows": 0, "warnings": 0}
    try:
        table_present = topics_table_exists(cursor)
    except Exception:
        logger.warning("intelligence_topics step=table_probe_failed warnings=1")
        return {"status": "skipped", "reason": "topics_probe_failed", "rows": 0, "warnings": 1}
    if not table_present and not flag:
        return {"status": "inert", "reason": "topics_table_absent", "rows": 0, "warnings": 0}
    try:
        vocabulary = load_vocabulary(VOCABULARY_VERSION_V1)
    except Exception:
        logger.warning("intelligence_topics step=vocabulary_invalid warnings=%s", len(items))
        return {
            "status": "skipped",
            "reason": "topics_vocabulary_invalid",
            "rows": 0,
            "warnings": len(items),
        }
    rows: list[TopicRow] = []
    warnings = 0
    for item in items:
        try:
            rows.extend(topic_rows_for_items([item], vocabulary))
        except Exception:
            warnings += 1
    if warnings:
        logger.warning("intelligence_topics step=item_skipped warnings=%s", warnings)
    if not rows:
        return {
            "status": "skipped",
            "reason": "topics_not_recorded",
            "rows": 0,
            "warnings": warnings,
        }
    try:
        recorded = merge_topic_rows(cursor, rows)
    except Exception:
        logger.warning("intelligence_topics step=merge_failed warnings=%s", warnings + 1)
        return {
            "status": "skipped",
            "reason": "topics_merge_failed",
            "rows": 0,
            "warnings": warnings + 1,
        }
    return {
        "status": "recorded",
        "reason": "topics_recorded",
        "rows": recorded,
        "warnings": warnings,
    }


ENDPOINTS = {
    "cdc-eid-expedited": "https://wwwnc.cdc.gov/eid/rss/expedited.xml",
    "cdc-eid-ahead-of-print": "https://wwwnc.cdc.gov/eid/rss/ahead-of-print.xml",
    "cdc-outbreaks": "https://tools.cdc.gov/api/v2/resources/media/281321.rss",
    "cdc-mmwr": "https://tools.cdc.gov/api/v2/resources/media/342778.rss",
    "cdc-vital-signs": "https://tools.cdc.gov/api/v2/resources/media/275866.rss",
    "nih-news-releases": "https://www.nih.gov/news-releases/feed.xml",
}
# Entrez searches. They are not RSS endpoints and never enter the RSS composer.
PUBMED_SOURCE_IDS = frozenset({"pubmed-lyme-borrelia", "pubmed-tick-borne"})
PUBMED_DRAFT_SOURCE_IDS = PUBMED_SOURCE_IDS
PUBMED_DECISION = "matthew-feed-selection-2026-10-03"
PUBMED_ARTIFACT_POLICY = "PUBMED_METADATA_RAW_30D_V1"
PUBMED_ESEARCH_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
RECEIPTS = Path("config/intelligence/pilot-policy-receipts.json")
DAILY_RECEIPTS = Path("config/intelligence/daily-policy-receipts.json")
DAILY_DECISION = "DATA-132-DAILY-CDC-2026-10-21"
# Pilot feeds use a five-minute process cap; each daily CDC source needs its own budget.
DAILY_SOURCE_BUDGET_SECONDS = 900
# After the budget expires, a fresh short connection records the FAILED terminal state.
DEADLINE_GRACE_SECONDS = 30
# Per-source process watchdog. It must outlive the budget plus the grace window
# used when a budget expiry records FAILED. The daily runner's hard-kill path
# records FAILED on a fresh connection before exiting (intelligence_daily_hard_kill).
DAILY_SOURCE_WATCHDOG_SECONDS = DAILY_SOURCE_BUDGET_SECONDS + 2 * DEADLINE_GRACE_SECONDS
# Parent-side stall limit. A frozen child cannot run its own timer or heartbeat,
# so the parent kills it after this long without a progress pulse. Healthy
# sources pulse about once a second and still have the 900s budget.
DAILY_SOURCE_INACTIVITY_SECONDS = 120
PROD_DAILY_SOURCE_SHA256 = {
    "cdc-eid-expedited": "570a796df7086b520136e5deab5917957561314e2f5fe96659bb3c9534124423",
    "cdc-eid-ahead-of-print": "12e3003da3e8782b379e321eb61fccecb36a9269c3017c10132bb96c848c39c3",
    "cdc-outbreaks": "d8bdcc90b16c98fe2b3661a9316ac78071bd355cbb46ee5d0299c15ca4f53b8f",
    "nih-news-releases": "1542aa4d8f85a650ac216e574907ec19f65e1d17a26dd8c8b607bfdcd17faaa1",
    "cdc-mmwr": "9ee7ceca898a4419241d9706c7cbf0a795287c794cdeb74b0892a4f90ccda0e9",
    # PubMed documents are registry version 1 and daily-only. The same digest is
    # pinned here so the Entrez walk admits them. They are not RSS definitions.
    "pubmed-tick-borne": "fdb52e28ef0f91ed6bd8bf7df449b8137a863f5b249c516e78c161d535201244",
    "pubmed-lyme-borrelia": "24994263e2325becad567953b78d16bab9c023ccd5099d0d785fc87d285551a6",
}
PROD_V3_DECISION = "DATA-816-D3R-2026-10-25"
# Reviewed receipt paths must stay inside this set. Description, category and guid
# are the only additions to the six daily paths. Enclosure, media and copyright stay out.
PROD_NATIVE_PATH_SUPERSET = frozenset(
    {
        "feed/language",
        "feed/link",
        "feed/title",
        "item/category",
        "item/description",
        "item/guid",
        "item/link",
        "item/pubDate",
        "item/title",
    }
)
PROD_V3_SOURCE_SHA256 = {
    "cdc-eid-expedited": "fb2190ab42aa713bb2465d8ff0ca579acacb3728b52a8cc87a846916f5a3cb5c",
    "cdc-eid-ahead-of-print": "25ccc477071e581eede7c0f28cb334209b98fde74d667f16ee738adc35812a8d",
    "cdc-outbreaks": "ed53f0d002393558848d99e5ca5b47f182cdc98d897097b1ffd4d49d40af81fb",
    "nih-news-releases": "840572dc7933ec80b52207deec5b8dedfb9247f41070050ec155146a075f3540",
    "cdc-mmwr": "e171c1b053227b5187ace15a38c5f7d61bfe1a2e012735615191491f77c1cff7",
}
PROD_EID_SHA256 = "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4"
PROD_SOURCE_SHA256 = {
    "cdc-eid-expedited": PROD_EID_SHA256,
    "cdc-eid-ahead-of-print": "b92e97c9e958c270645c9710118b3a3076228c6bcb2390b5c58cff9bacb2a7be",
    "cdc-outbreaks": "54793f2c4856602bf8901d09972a44d2a7479056e71eac75ddc88db060646172",
    "nih-news-releases": "38d7364d5ce7b730d16e07197d0bb1cf88403eae59defc66de05e3a3df825bea",
    "cdc-mmwr": "875b0bc1b33f2c89ff4596532ccd8504dc6ce60086f8bba9146183da2b2d59a6",
    # Same digest as the daily pin. reviewed_package gates membership on this map.
    "pubmed-tick-borne": "fdb52e28ef0f91ed6bd8bf7df449b8137a863f5b249c516e78c161d535201244",
    "pubmed-lyme-borrelia": "24994263e2325becad567953b78d16bab9c023ccd5099d0d785fc87d285551a6",
}
PROD_SOURCE_DECISIONS = {
    "cdc-eid-expedited": "DATA-132-135-EID-ADMISSION-2026-10-09",
    "cdc-eid-ahead-of-print": "matthew-feed-selection-2026-10-03",
    "cdc-outbreaks": "matthew-feed-selection-2026-10-03",
    "nih-news-releases": "matthew-feed-selection-2026-10-03",
    "cdc-mmwr": "matthew-feed-selection-2026-10-03",
    "pubmed-tick-borne": PUBMED_DECISION,
    "pubmed-lyme-borrelia": PUBMED_DECISION,
}
PROD_SOURCE_DEFINITIONS = {
    "cdc-eid-expedited": "config/sources/intelligence_cdc_eid_expedited.yml",
    "cdc-eid-ahead-of-print": "config/sources/intelligence_cdc_eid_ahead_of_print.yml",
    "cdc-outbreaks": "config/sources/intelligence_cdc_outbreaks.yml",
    "nih-news-releases": "config/sources/intelligence_nih_news_releases.yml",
    "cdc-mmwr": "config/sources/intelligence_cdc_mmwr.yml",
}
# cdc-mmwr is the large feed (~250 items). Run it before the smaller feeds so
# their processes do not overlap its peak. The set matches PROD_SOURCE_DEFINITIONS.
DAILY_SOURCE_RUN_ORDER = (
    "cdc-mmwr",
    "cdc-eid-expedited",
    "cdc-eid-ahead-of-print",
    "cdc-outbreaks",
    "nih-news-releases",
)
# Operator stages for one daily source. Checkpoint names stay on the orchestrator;
# these are the boundaries a daily outcome is allowed to name.
DAILY_OPERATOR_STAGES = (
    "CLAIM",
    "FETCH",
    "PARSE",
    "NORMALIZE",
    "WRITE",
    "RETENTION",
    "PUBLISH",
)
DAILY_OPERATOR_STAGE_NAMES = frozenset(DAILY_OPERATOR_STAGES)


def reviewed_prod_source_sha256(source_id: str, registry_version: int) -> str:
    """Pinned registry hash for one reviewed production version."""
    pins = {
        1: PROD_SOURCE_SHA256,
        2: PROD_DAILY_SOURCE_SHA256,
        3: PROD_V3_SOURCE_SHA256,
    }
    try:
        return pins[registry_version][source_id]
    except KeyError as error:
        raise PermissionError("INTELLIGENCE_PROD_REVIEWED_EID_REQUIRED") from error


def reviewed_prod_decision_ref(source_id: str, registry_version: int) -> str:
    """Pinned decision reference for one reviewed production version."""
    if registry_version == 1:
        return PROD_SOURCE_DECISIONS[source_id]
    if registry_version == 2:
        return DAILY_DECISION
    if registry_version == 3:
        return PROD_V3_DECISION
    raise PermissionError("INTELLIGENCE_PROD_REVIEWED_EID_REQUIRED")


def prod_daily_config_sha256_allowed(source_id: str, config_sha256: str) -> bool:
    """True for the v2 daily pin or the v3 registry pin of one live source."""
    return config_sha256 in {
        PROD_DAILY_SOURCE_SHA256.get(source_id),
        PROD_V3_SOURCE_SHA256.get(source_id),
    }


ORCHESTRATOR_STAGE_TO_DAILY = {
    "ACQUIRE": "FETCH",
    "VALIDATE": "PARSE",
    "NORMALIZE": "NORMALIZE",
    "LOAD": "WRITE",
    "QUALITY": "WRITE",
    "PUBLISH_STAGE": "PUBLISH",
}


@contextmanager
def pilot_watchdog(*, seconds: int = 300) -> Iterator[None]:
    """Stop the owned CLI at its deadline, including blocked SDK calls.

    Covers connection setup, implicit transaction SQL and Spaces operations
    which cannot all be intercepted by the cursor wrapper. No other process,
    warehouse or session is cancelled. The feed default is five minutes; the
    exact prerequisite batch uses fifty seconds.
    """
    # os._exit ends the process, so there is no observation context to carry.
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

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        *,
        seconds: int = 300,
        request_limit: int = 1,
    ) -> None:
        if seconds < 1:
            raise ValueError("Pilot budget seconds must be positive")
        if request_limit < 1:
            raise ValueError("Pilot budget request limit must be positive")
        self.clock = clock
        self.seconds = seconds
        self.request_limit = request_limit
        self.deadline = clock() + seconds
        self.requests = 0
        self.queries = 0
        self.stage_timings: list[dict[str, Any]] = []
        self._open_stages: dict[str, tuple[float, int]] = {}

    def observe_stages(self, stages: Iterable[Any]) -> None:
        """Record redacted per-stage seconds and query counts as checkpoints are saved."""
        for checkpoint in stages:
            name, status = checkpoint.stage.value, checkpoint.status.value
            if status == "RUNNING" and name not in self._open_stages:
                self._open_stages[name] = (self.clock(), self.queries)
            elif status in {"COMPLETED", "FAILED"} and name in self._open_stages:
                started, queries = self._open_stages.pop(name)
                self.stage_timings.append(self._timing(name, status, started, queries))

    def _timing(self, stage: str, status: str, started: float, queries: int) -> dict[str, Any]:
        return {
            "stage": stage,
            "status": status,
            "seconds": round(self.clock() - started, 2),
            "queries": self.queries - queries,
        }

    def timing_report(self) -> list[dict[str, Any]]:
        """Closed stages plus any stage still open now (for example at a deadline)."""
        open_rows = [
            self._timing(name, "UNFINISHED", started, queries)
            for name, (started, queries) in self._open_stages.items()
        ]
        return [*self.stage_timings, *open_rows]

    def open_daily_stage(self) -> str | None:
        """Operator stage for the checkpoint that is still running, if it maps."""
        if not self._open_stages:
            return None
        latest = next(reversed(self._open_stages))
        return ORCHESTRATOR_STAGE_TO_DAILY.get(latest)

    def operator_timings_ms(self) -> dict[str, int]:
        """Milliseconds per operator stage that this budget has actually entered.

        Derived from the redacted timing report. Stages that share an operator
        name (LOAD and QUALITY are both WRITE) are summed. No payloads or errors.
        """
        totals: dict[str, int] = {}
        for row in self.timing_report():
            stage = row.get("stage")
            seconds = row.get("seconds")
            operator = ORCHESTRATOR_STAGE_TO_DAILY.get(stage) if isinstance(stage, str) else None
            if (
                operator is None
                or isinstance(seconds, bool)
                or not isinstance(seconds, int | float)
            ):
                continue
            elapsed = float(seconds)
            if elapsed < 0:
                continue
            totals[operator] = totals.get(operator, 0) + int(round(elapsed * 1000))
        return totals

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
        if self.requests >= self.request_limit:
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

    def reserve(self) -> float:
        """Count one owned request without receiving its URL or parameters."""
        remaining = self.remaining()
        if self.requests >= self.request_limit:
            raise PermissionError("INTELLIGENCE_PILOT_REQUEST_LIMIT")
        self.requests += 1
        return remaining


class DailyStageClock:
    """Milliseconds spent between explicit operator-stage boundaries.

    Callers pass a stage name from ``DAILY_OPERATOR_STAGES``. The clock stores
    durations only.
    """

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self.clock = clock
        self.timings_ms: dict[str, int] = {}
        self._open: dict[str, float] = {}

    def begin(self, stage: str) -> None:
        if stage not in DAILY_OPERATOR_STAGE_NAMES or stage in self._open:
            return
        self._open[stage] = self.clock()

    def end(self, stage: str) -> None:
        started = self._open.pop(stage, None)
        if started is None:
            return
        elapsed = self.clock() - started
        milliseconds = 0 if elapsed <= 0 else int(round(elapsed * 1000))
        self.timings_ms[stage] = self.timings_ms.get(stage, 0) + milliseconds

    def snapshot_ms(self) -> dict[str, int]:
        totals = dict(self.timings_ms)
        now = self.clock()
        for stage, started in self._open.items():
            elapsed = now - started
            milliseconds = 0 if elapsed <= 0 else int(round(elapsed * 1000))
            totals[stage] = totals.get(stage, 0) + milliseconds
        return totals


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
        note_step_deadline()
        remaining = self.budget.remaining()
        deadline = active_step_deadline()
        if deadline is not None:
            remaining = min(remaining, deadline.remaining())
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
        try:
            if getattr(self.raw, "daily_observed", False):
                result = self.raw.execute(statement, *args, **kwargs)
            else:
                result = instrumented_execute(self.raw, statement, args, kwargs)
        finally:
            # The connector disarms SIGALRM before returning, including on retry.
            note_step_deadline()
        self.budget.remaining()
        return result


class _Connection:
    def __init__(self, connection: Any, budget: PilotBudget) -> None:
        self.raw, self.budget = connection, budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def cursor(self, *args: Any, **kwargs: Any) -> _Cursor:
        note_step_deadline()
        self.budget.remaining()
        return _Cursor(self.raw.cursor(*args, **kwargs), self.budget)

    def commit(self) -> Any:
        return self._transaction("commit")

    def rollback(self) -> Any:
        return self._transaction("rollback")

    def autocommit(self, value: bool) -> Any:
        return self._transaction("autocommit", value)

    def _transaction(self, operation: str, *args: Any) -> Any:
        note_step_deadline()
        self.budget.remaining()
        if self.budget.queries >= 2500:
            raise PermissionError("INTELLIGENCE_PILOT_QUERY_LIMIT")
        self.budget.queries += 1
        try:
            result = getattr(self.raw, operation)(*args)
        finally:
            note_step_deadline()
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
        source = definition.extra.get("intelligence_registry")
        if not isinstance(source, dict):
            raise PermissionError("INTELLIGENCE_PILOT_DEFINITION_REQUIRED")
        maximum_items = source["limits"]["maximum_items"]
        if len(normalized.records) > maximum_items:
            raise PermissionError("INTELLIGENCE_PILOT_ITEM_LIMIT")
        # Native v2 envelopes scale with reviewed maximum_items, not the legacy 1 MiB pilot cap.
        normalized_limit = max(1_048_576, maximum_items * 8_192)
        if len(json.dumps(normalized.records).encode()) > normalized_limit:
            raise PermissionError("INTELLIGENCE_PILOT_NORMALIZED_LIMIT")
        return normalized


def compose_pilot(
    definition: SourceDefinition,
    *,
    receipts: list[dict[str, Any]],
    connection_factory: Callable[[], Any],
    settings: PipelineSettings,
    budget: PilotBudget | None = None,
    registry_version: int = 1,
) -> tuple[IngestionOrchestrator, SourceDefinition]:
    """Assemble existing runtime components; perform no approval or schema DDL."""
    if settings.topx_env not in {"dev", "prod"}:
        raise PermissionError("INTELLIGENCE_PILOT_ENVIRONMENT_REQUIRED")
    environment: Literal["DEV", "PROD"] = "PROD" if settings.topx_env == "prod" else "DEV"
    if environment == "PROD" or definition.source_id == "cdc-mmwr":
        allowed_versions = {1, 2, 3}
    elif definition.source_id in PROD_DAILY_SOURCE_SHA256:
        allowed_versions = {1, 3}
    else:
        allowed_versions = {1}
    if registry_version not in allowed_versions:
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_SOURCE_REQUIRED")
    if definition.source_id in PUBMED_DRAFT_SOURCE_IDS:
        raise PermissionError("INTELLIGENCE_PUBMED_DRAFT_UNREGISTERED")
    if environment == "PROD":
        endpoint = urlsplit(settings.spaces_endpoint)
        if (
            definition.source_id not in PROD_METADATA_FEED_IDS
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
    selected = [
        receipt
        for receipt in receipts
        if receipt.get("source_id") == definition.source_id
        and (environment != "PROD" or receipt.get("registry_version") == registry_version)
    ]
    if len(selected) != 1:
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_POLICY_REQUIRED")
    receipt = selected[0]
    if not receipt.get("decision_ref") or not receipt.get("raw_policy_ref"):
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_POLICY_REQUIRED")
    if environment == "PROD" and (
        receipt["registry_version"] != registry_version
        or receipt["source_sha256"]
        != reviewed_prod_source_sha256(definition.source_id, registry_version)
        or receipt["decision_ref"]
        != reviewed_prod_decision_ref(definition.source_id, registry_version)
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
        native.policy_ref != definition.source_id + "-native-metadata-v1"
        or not native.permitted_paths <= PROD_NATIVE_PATH_SUPERSET
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
        or source["fetch_location"]
        != (
            definition.endpoint_template + "?max=250"
            if registry_version == 3 and definition.source_id == "cdc-mmwr"
            else definition.endpoint_template
        )
    ):
        raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_SOURCE_REQUIRED")
    if (
        environment == "PROD"
        and registry_version in {2, 3}
        and (source["state"] != "active" or source["cadence"]["poll_seconds"] != 86400)
    ):
        raise PermissionError("INTELLIGENCE_DAILY_ACTIVE_SOURCE_REQUIRED")
    if environment == "PROD":
        with factory() as connection, connection.cursor() as cursor:
            activations = fetch_activations(cursor)
        if not source_is_active(source, load_registry_documents(), activations):
            raise PermissionError("INTELLIGENCE_ACTIVE_SOURCE_REQUIRED")
    native.validate(source)
    definition = replace(
        definition,
        definition_version=source["registry_version"],
        endpoint_template=source["fetch_location"],
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
    effects.store.after_merge = record_topics_after_merge
    adapter = PilotFeedAdapter(
        registry_lookup=effects.store.lookup_source,
        retention_allowed=lambda ref: ref == policy_ref,
        native_policy_lookup=lambda sid, version: native,
        feed_retention=retention,
        request=lambda *args: budget.request(_request, *args),
        resolve=lambda host, timeout: _resolve(host, min(timeout, 30, budget.remaining())),
    )
    checkpoints = IntelligenceSnowflakeCheckpoints(retention, connection_factory=factory)
    checkpoints.stage_observer = budget.observe_stages
    orchestrator = IngestionOrchestrator(store=checkpoints, adapter=adapter, effects=effects)
    orchestrator.pilot_budget = budget
    return orchestrator, definition


def canonical_pilot(
    definition: SourceDefinition, *, budget_seconds: int = 300
) -> tuple[IngestionOrchestrator, SourceDefinition]:
    """Called by existing source run, using existing environment credentials."""
    receipts = json.loads(RECEIPTS.read_text(encoding="utf-8"))["receipts"]
    settings = PipelineSettings()
    budget = PilotBudget(seconds=budget_seconds)
    version = 1
    if settings.topx_env == "prod":
        receipts += json.loads(DAILY_RECEIPTS.read_text(encoding="utf-8"))["receipts"]
        with connect(SnowflakeSettings()) as raw, _Connection(raw, budget).cursor() as cursor:
            cursor.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30")
            cursor.execute(
                "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
            )
            if cursor.fetchall() != [
                (
                    "OH_LYME_PROD_PIPELINE_SVC",
                    "OH_LYME_PROD_RUNTIME",
                    "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                    "OH_LYME_PROD_INGEST_XS_WH",
                )
            ]:
                raise PermissionError("INTELLIGENCE_PILOT_RUNTIME_CONTEXT_REQUIRED")
            cursor.execute(
                "SELECT registry_version FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS "
                "WHERE source_id=%s ORDER BY registry_version DESC LIMIT 1",
                (definition.source_id,),
            )
            rows = cursor.fetchall()
            if len(rows) != 1 or rows[0][0] not in {1, 2, 3}:
                raise PermissionError("INTELLIGENCE_PILOT_REVIEWED_SOURCE_REQUIRED")
            version = rows[0][0]
    return compose_pilot(
        definition,
        receipts=receipts,
        settings=settings,
        connection_factory=lambda: connect(SnowflakeSettings()),
        budget=budget,
        registry_version=version,
    )
