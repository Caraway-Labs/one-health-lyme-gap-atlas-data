"""Recorded-fixture coverage for PubMed backfill slices."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from runpy import run_path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import SecretStr

from lyme_gap_atlas_data.ingestion import intelligence_entrez as entrez
from lyme_gap_atlas_data.ingestion import intelligence_pubmed_backfill as backfill
from lyme_gap_atlas_data.ingestion.checkpoints import InMemoryCheckpointStore
from lyme_gap_atlas_data.ingestion.intelligence_daily_run_ids import daily_run_id
from lyme_gap_atlas_data.ingestion.intelligence_entrez import (
    ENTREZ_DAILY_RESOURCE,
    ENTREZ_TOOL,
    ESEARCH_URL,
    SOURCE_ORDER,
    EntrezResponse,
    RevisionLedger,
    entry_dates_from_ledger,
    entry_window,
)
from lyme_gap_atlas_data.ingestion.intelligence_runtime import PilotBudget
from lyme_gap_atlas_data.ingestion.types import (
    RunState,
    RunStatus,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_raw_runtime import FeedRawRetention, SQLiteRawLedger
from lyme_gap_atlas_data.intelligence_retention import _time
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_GATE = run_path(str(ROOT / "scripts" / "prod_intelligence_pubmed_backfill.py"))

WATERMARK = date(2026, 10, 25)
TODAY = date(2026, 10, 27)
FETCHED_AT = "2026-10-27T15:04:05Z"
EMAIL = "fixture@example.test"
DAILY_WORKFLOW = ROOT / ".github" / "workflows" / "run-prod-intelligence-daily-once.yml"
DAILY_WORKFLOW_SHA256 = "f674ca5bf4b5757caa342248279af084f3b30477505a4546c0b231c66e5c6351"
DENVER = ZoneInfo("America/Denver")


def _settings() -> PipelineSettings:
    # Explicit database keeps the fixture independent of the shell's SNOWFLAKE_DATABASE.
    return PipelineSettings(
        topx_env="dev",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        ncbi_email=EMAIL,
        ncbi_api_key=SecretStr("fixture-key"),
    )


def _queries() -> dict[str, str]:
    document = json.loads((ROOT / "config/intelligence/feed-selection-v1.json").read_text())
    return {
        entry["source_id"]: entry["query"]
        for entry in document["sources"]
        if entry["source_id"] in SOURCE_ORDER
    }


def _prepared_sources() -> dict[str, Any]:
    sources: dict[str, Any] = {}
    document = json.loads((ROOT / "config/intelligence/pubmed-policy-receipts.json").read_text())
    for source_id in SOURCE_ORDER:
        source = json.loads(
            (ROOT / f"config/intelligence/{source_id}-source-v1.json").read_text(encoding="utf-8")
        )
        source["state"] = "active"
        sources[source_id] = source
    for receipt in document["receipts"]:
        digest = identity_hash(sources[receipt["source_id"]])
        receipt["source_sha256"] = digest
        receipt["native_policy"]["source_sha256"] = digest
    return {"sources": sources, "receipts": document}


def _article(pmid: str, entered: date) -> str:
    return (
        "<PubmedArticle><MedlineCitation>"
        f"<PMID>{pmid}</PMID><Article>"
        "<Journal><Title>Journal of Fixture Studies</Title><JournalIssue><PubDate>"
        f"<Year>{entered.year}</Year><Month>{entered.month}</Month><Day>{entered.day}</Day>"
        "</PubDate></JournalIssue></Journal>"
        f"<ArticleTitle>Recorded fixture {pmid}</ArticleTitle>"
        "<Abstract><AbstractText>Fixture abstract.</AbstractText></Abstract>"
        "<Language>eng</Language></Article></MedlineCitation><PubmedData><History>"
        '<PubMedPubDate PubStatus="entrez">'
        f"<Year>{entered.year}</Year><Month>{entered.month}</Month><Day>{entered.day}</Day>"
        "</PubMedPubDate></History></PubmedData></PubmedArticle>"
    )


class FixtureTransport:
    def __init__(self, searches: dict[str, dict[str, Any]]) -> None:
        self.searches = searches
        self.calls: list[dict[str, str]] = []
        self.timeouts: list[float] = []

    def __call__(self, url: str, params: Mapping[str, str], timeout: float) -> EntrezResponse:
        self.timeouts.append(timeout)
        assert "api_key" not in params
        assert params.get("tool") == ENTREZ_TOOL
        assert params.get("email") == EMAIL
        hidden = {"tool", "email", "api_key"}
        visible = {key: value for key, value in params.items() if key not in hidden}
        self.calls.append({"url": url, **visible})
        if url == ESEARCH_URL:
            found = self.searches[params["term"]]
            body = json.dumps(
                {"esearchresult": {"count": str(found["count"]), "idlist": found["idlist"]}}
            ).encode()
            return EntrezResponse(200, body)
        parts = ["<PubmedArticleSet>"]
        for index, pmid in enumerate(params["id"].split(",")):
            parts.append(_article(pmid, date(2024, 3, 1) + timedelta(days=index)))
        parts.append("</PubmedArticleSet>")
        return EntrezResponse(200, "".join(parts).encode())


def _clock() -> tuple[list[float], Any, Any]:
    now = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    return sleeps, clock, sleep


def _plan(
    *,
    plan_id: str = "dev-proof",
    slice_id: str = "week",
    mindate: str = "2026-09-01",
    maxdate: str = "2026-09-07",
    slices: list[dict[str, str]] | None = None,
    approved_by: str = "",
    approved_at: str = "",
    approved_request_limit: int | None = None,
    request_limit: int = 5,
    item_limit: int = 200,
) -> backfill.BackfillPlan:
    document: dict[str, Any] = {
        "plan_id": plan_id,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "request_limit": request_limit,
        "item_limit": item_limit,
        "sources": list(SOURCE_ORDER),
        "slices": slices or [{"slice_id": slice_id, "mindate": mindate, "maxdate": maxdate}],
    }
    if approved_request_limit is not None:
        document["approved_request_limit"] = approved_request_limit
    return backfill.plan_from_document(document)


def _seed(
    day: date = WATERMARK,
    *,
    running: bool = False,
    store: InMemoryCheckpointStore | None = None,
) -> InMemoryCheckpointStore:
    store = store or InMemoryCheckpointStore()
    status = RunStatus.RUNNING if running else RunStatus.SUCCEEDED
    store.save(
        RunState(
            ingestion_run_id=daily_run_id("pubmed-tick-borne", date(2026, 10, 24)),
            resource_key=ENTREZ_DAILY_RESOURCE,
            source_definition_version=1,
            tier=Tier.C,
            status=status,
            stages=[
                StageCheckpoint(
                    stage=Stage.LOAD,
                    status=StageStatus.COMPLETED,
                    detail={
                        "last_entry_date": {
                            source_id: day.isoformat() for source_id in SOURCE_ORDER
                        },
                        "sequence": 4,
                    },
                )
            ],
        )
    )
    return store


def _run(
    transport: FixtureTransport,
    plan: backfill.BackfillPlan,
    checkpoints: InMemoryCheckpointStore,
    *,
    slice_id: str = "week",
    environment: str = "dev",
    now: datetime | None = None,
    dry_run: bool = False,
    revisions: RevisionLedger | None = None,
    prior: tuple[tuple[str, str, str], ...] = (),
    store: Any | None = None,
    request_limit: int = 5,
) -> tuple[dict[str, Any], list[float]]:
    prepared = _prepared_sources()
    sleeps, clock, sleep = _clock()
    budget = PilotBudget(clock, seconds=180, request_limit=request_limit)
    outcome = backfill.execute_pubmed_backfill(
        plan=plan,
        slice_id=slice_id,
        sender=transport,
        settings=_settings(),
        budget=budget,
        checkpoints=checkpoints,
        today=TODAY,
        fetched_at=FETCHED_AT,
        clock=clock,
        sleep=sleep,
        environment=environment,
        now=now or datetime(2026, 10, 27, 16, 0, tzinfo=DENVER),
        dry_run=dry_run,
        revisions=revisions,
        prior=prior,
        store=store,
        sources=prepared["sources"],
        receipt_document=prepared["receipts"],
    )
    return outcome, sleeps


def _searches(groups: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    queries = _queries()
    return {
        queries[source_id]: {"count": len(pmids), "idlist": pmids}
        for source_id, pmids in groups.items()
    }


def _pmids(start: int, count: int) -> list[str]:
    return [str(start + offset) for offset in range(count)]


def test_daily_workflow_file_is_unchanged_and_backfill_is_dispatch_only() -> None:
    digest = hashlib.sha256(DAILY_WORKFLOW.read_bytes()).hexdigest()
    assert digest == DAILY_WORKFLOW_SHA256
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/run-prod-intelligence-pubmed-backfill.yml").read_text()
    )
    assert set(workflow) >= {"name", True, "permissions", "concurrency", "jobs"}
    assert workflow["concurrency"] == {
        "group": "prod-app-topology",
        "cancel-in-progress": False,
    }
    assert "schedule" not in workflow[True]
    assert "schedule" not in workflow
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "image_digest",
        "reviewed_commit",
        "backfill_plan_id",
        "slice_id",
        "reason",
    }
    assert workflow["jobs"]["gate"]["environment"] == "production"
    assert workflow["jobs"]["run"]["environment"] == "production"
    gate_runs = "\n".join(step.get("run", "") for step in workflow["jobs"]["gate"]["steps"])
    assert "doctl" not in gate_runs
    assert "--now" not in gate_runs
    run_steps = "\n".join(step.get("run", "") for step in workflow["jobs"]["run"]["steps"])
    assert 'exit "$operation_status"' in run_steps
    assert entrez.MAX_REQUESTS == 5
    assert entrez.MAX_ITEMS == 200
    assert entrez.BATCH_SIZE == 67
    assert entrez.FIRST_WINDOW_DAYS == 30
    assert entry_window(WATERMARK, TODAY) == (date(2026, 10, 23), TODAY)


def test_window_slice_length_and_prod_approval_are_refused() -> None:
    transport = FixtureTransport(_searches({source_id: ["12345678"] for source_id in SOURCE_ORDER}))
    checkpoints = _seed()
    plan = _plan(maxdate="2026-09-25")
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_WINDOW_NOT_OLDER"):
        _run(transport, plan, checkpoints)
    assert transport.calls == []
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_SLICE_TOO_LONG"):
        _plan(mindate="2026-08-01", maxdate="2026-08-31")
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_SLICE_OVERLAP"):
        _plan(
            slices=[
                {"slice_id": "a", "mindate": "2026-08-01", "maxdate": "2026-08-10"},
                {"slice_id": "b", "mindate": "2026-08-10", "maxdate": "2026-08-20"},
            ]
        )
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_PLAN_UNAPPROVED"):
        _run(transport, _plan(), _seed(), environment="prod")
    assert transport.calls == []
    bare = _seed()
    bare.save(
        RunState(
            ingestion_run_id="watermark-without-dates",
            resource_key=ENTREZ_DAILY_RESOURCE,
            source_definition_version=1,
            tier=Tier.C,
            status=RunStatus.SUCCEEDED,
            stages=[StageCheckpoint(stage=Stage.LOAD, status=StageStatus.COMPLETED, detail={})],
        )
    )
    # Replace the seeded watermark with a run that has no dates.
    empty = InMemoryCheckpointStore()
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_WATERMARK_REQUIRED"):
        _run(transport, _plan(), empty)
    assert transport.calls == []


def test_dry_run_prints_the_slice_and_makes_no_request() -> None:
    def explode(url: str, params: Mapping[str, str], timeout: float) -> EntrezResponse:
        raise AssertionError("dry run called the provider")

    checkpoints = _seed()
    outcome, _sleeps = _run(explode, _plan(), checkpoints, dry_run=True)  # type: ignore[arg-type]
    assert outcome["dry_run"] is True
    assert outcome["mindate"] == "2026-09-01"
    assert outcome["maxdate"] == "2026-09-07"
    assert outcome["planned_request_count"] == 5
    assert outcome["requests"] == 0
    assert outcome["writes"] == 0
    assert outcome["cursor"] == {
        "retstart": 0,
        "last_pmid": None,
        "slice_complete": False,
        "remaining": None,
    }
    assert entry_dates_from_ledger(checkpoints).get("pubmed-tick-borne") == WATERMARK
    assert backfill.public_outcome(outcome)["requests"] == 0
    assert "fixture-key" not in json.dumps(backfill.public_outcome(outcome))
    assert EMAIL not in json.dumps(backfill.public_outcome(outcome))


def test_overflow_resumes_without_skipping_or_moving_the_daily_watermark() -> None:
    tick = _pmids(10000001, 200)
    lyme = _pmids(10000159, 100)
    unique = list(dict.fromkeys([*tick, *lyme]))
    assert len(unique) == 258
    transport = FixtureTransport(
        _searches({"pubmed-tick-borne": tick, "pubmed-lyme-borrelia": lyme})
    )
    checkpoints = _seed()
    revisions = RevisionLedger()
    plan = _plan(slice_id="days-31-60", mindate="2026-08-26", maxdate="2026-09-24")
    before = len(transport.calls)
    first, sleeps = _run(transport, plan, checkpoints, slice_id="days-31-60", revisions=revisions)
    first_calls = transport.calls[before:]
    assert len(first_calls) == 5
    assert all(call["url"] == ESEARCH_URL for call in first_calls[:2])
    batches = [len(call["id"].split(",")) for call in first_calls[2:]]
    assert batches == [67, 67, 66]
    assert first["items_captured"] == 200
    assert first["revisions_inserted"] == 200
    assert first["remaining"] == 58
    assert first["slice_complete"] is False
    assert first["cursor"]["retstart"] == 200
    assert sleeps == [0.4, 0.4, 0.4, 0.4]
    assert transport.timeouts[:5] == [30.0, 30.0, 30.0, 30.0, 30.0]
    assert first_calls[0]["retmax"] == "10000"
    assert first_calls[0]["mindate"] == "2026/08/26"
    assert first_calls[0]["maxdate"] == "2026/09/24"
    before = len(transport.calls)
    second, _sleeps = _run(transport, plan, checkpoints, slice_id="days-31-60", revisions=revisions)
    second_calls = transport.calls[before:]
    assert len(second_calls) == 3
    fetched = [call for call in second_calls if call["url"] != ESEARCH_URL]
    assert [len(call["id"].split(",")) for call in fetched] == [58]
    assert second["items_captured"] == 58
    assert second["revisions_inserted"] == 58
    assert second["remaining"] == 0
    assert second["slice_complete"] is True
    captured = [
        item["publisher_metadata"]["source_item_id"] for item in [*first["items"], *second["items"]]
    ]
    assert set(captured) == set(unique)
    overlap = next(
        item
        for item in first["items"]
        if item["publisher_metadata"]["source_item_id"] == "10000159"
    )
    assert overlap["publisher_metadata"]["matched_queries"] == list(SOURCE_ORDER)
    assert entry_dates_from_ledger(checkpoints).dates == {
        source_id: WATERMARK for source_id in SOURCE_ORDER
    }
    run_ids = {state.ingestion_run_id for state in checkpoints.list_runs()}
    for source_id in SOURCE_ORDER:
        assert daily_run_id(source_id, TODAY) not in run_ids
        for attempt in (2, 3):
            assert daily_run_id(source_id, TODAY, reopen_attempt=attempt) not in run_ids
    cursor_runs = [
        state
        for state in checkpoints.list_runs()
        if state.resource_key == backfill.BACKFILL_RESOURCE
    ]
    assert cursor_runs
    assert all(
        "last_entry_date" not in (state.checkpoint(Stage.LOAD).detail or {})
        for state in checkpoints.list_runs()
        if state.resource_key in SOURCE_ORDER
    )
    before = len(transport.calls)
    third, _sleeps = _run(transport, plan, checkpoints, slice_id="days-31-60", revisions=revisions)
    assert len(transport.calls) - before == 2
    assert third["revisions_inserted"] == 0
    assert third["items_captured"] == 0
    assert third["slice_complete"] is True
    assert len(transport.calls) <= before + 5


def test_request_limit_is_five_for_both_queries_together() -> None:
    tick = _pmids(20000001, 200)
    lyme = _pmids(20000159, 100)
    transport = FixtureTransport(
        _searches({"pubmed-tick-borne": tick, "pubmed-lyme-borrelia": lyme})
    )
    outcome, _sleeps = _run(transport, _plan(maxdate="2026-09-24"), _seed())
    assert outcome["requests"] == 5
    assert len(transport.calls) == 5
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_REQUEST_LIMIT"):
        _plan(
            request_limit=6,
            approved_request_limit=6,
            approved_by="Matthew",
            approved_at=FETCHED_AT,
        )


def test_already_stored_pmid_adds_no_revision_and_a_finished_slice_is_cheap() -> None:
    groups = {source_id: ["12345678"] for source_id in SOURCE_ORDER}
    transport = FixtureTransport(_searches(groups))
    plan = _plan()
    first_ledger = RevisionLedger()
    first, _sleeps = _run(transport, plan, _seed(), revisions=first_ledger)
    assert first["items_captured"] == 1
    assert first["revisions_inserted"] == 1
    stored = next(iter(first_ledger.keys))
    seeded = RevisionLedger()
    seeded.keys.add(stored)
    second, _sleeps = _run(transport, plan, _seed(), revisions=seeded)
    assert second["revisions_inserted"] == 0
    assert stored in seeded.keys
    assert any(
        item["publisher_metadata"]["source_item_id"] == "12345678" for item in second["items"]
    )
    checkpoints = _seed()
    _run(transport, plan, checkpoints, revisions=RevisionLedger())
    before = len(transport.calls)
    again, _sleeps = _run(transport, plan, checkpoints, revisions=RevisionLedger())
    assert again["revisions_inserted"] == 0
    assert again["items_captured"] == 0
    assert len(transport.calls) - before <= 2


def test_backfill_raw_copy_uses_the_run_capture_time(tmp_path: Path) -> None:
    prepared = _prepared_sources()
    source = prepared["sources"]["pubmed-tick-borne"]
    retention = FeedRawRetention(
        SQLiteRawLedger(tmp_path / "ledger.sqlite"),
        environment="DEV",
        source_lookup=lambda source_id, version: prepared["sources"][source_id],
        policy_lookup=lambda selected: selected["access_use"]["content_retention_policy_ref"],
        clock=lambda: FETCHED_AT,
    )

    class Ledger(InMemoryCheckpointStore):
        feed_retention = retention

    class Cursor:
        def execute(self, statement: str, params: tuple[Any, ...] = ()) -> None:
            return None

    class Store:
        def __init__(self) -> None:
            self.contexts: list[dict[str, Any]] = []

        @contextmanager
        def capture_session(self) -> Iterator[Cursor]:
            yield Cursor()

        def record_acquisition(self, **kwargs: Any) -> None:
            self.contexts.append(kwargs["context"])

        def existing_entrez_captures(self, item_ids: tuple[str, ...]) -> list[tuple[str, str, str]]:
            return []

        def write(self, **kwargs: Any) -> int:
            return len(kwargs["items"])

    store = Store()
    ledger = _seed(store=Ledger())
    transport = FixtureTransport(_searches({source_id: ["12345678"] for source_id in SOURCE_ORDER}))
    outcome, _sleeps = _run(transport, _plan(), ledger, store=store)
    leases = retention.ledger.documents("lease")
    assert len(leases) == 1
    assert leases[0]["captured_at"] == FETCHED_AT
    assert _time(leases[0]["expires_at"]) == _time(FETCHED_AT) + timedelta(days=30)
    published = outcome["items"][0]["published_at"]
    assert published != FETCHED_AT
    assert leases[0]["captured_at"] != published
    assert store.contexts[0]["fetched_at"] == FETCHED_AT
    assert source["source_id"] == "pubmed-tick-borne"


def test_blackout_and_a_running_daily_row_make_no_request() -> None:
    transport = FixtureTransport(_searches({source_id: ["12345678"] for source_id in SOURCE_ORDER}))
    inside = datetime(2026, 10, 27, 17, 45, tzinfo=DENVER)
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_BLACKOUT"):
        _run(transport, _plan(), _seed(), now=inside)
    late = datetime(2026, 10, 27, 18, 45, tzinfo=DENVER)
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_BLACKOUT"):
        _run(transport, _plan(), _seed(), now=late)
    outside = datetime(2026, 10, 27, 18, 46, tzinfo=DENVER)
    _run(transport, _plan(), _seed(), now=outside, dry_run=True)
    running = _seed(running=True)
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_DAILY_RUNNING"):
        _run(transport, _plan(), running, now=outside)
    assert transport.calls == []


def test_gate_and_spec_leave_the_scheduled_daily_job_alone() -> None:
    moment = datetime(2026, 10, 27, 17, 45, tzinfo=DENVER)
    assert backfill.in_backfill_blackout(moment) is _GATE["in_backfill_blackout"](moment)
    assert backfill.in_backfill_blackout(datetime(2026, 10, 27, 18, 46, tzinfo=DENVER)) is False
    code = _GATE["evaluate_gate"](
        now=datetime(2026, 10, 27, 16, 0, tzinfo=DENVER),
        plan_id="dev-proof",
        slice_id="week",
        reason="DEV proof of one slice",
        daily_running_count=1,
        daily_status_known=True,
    )
    assert code == "INTELLIGENCE_PUBMED_BACKFILL_DAILY_RUNNING"
    code = _GATE["evaluate_gate"](
        now=moment,
        plan_id="dev-proof",
        slice_id="week",
        reason="DEV proof of one slice",
        daily_running_count=0,
        daily_status_known=True,
    )
    assert code == "INTELLIGENCE_PUBMED_BACKFILL_BLACKOUT"
    unknown = _GATE["evaluate_gate"](
        now=datetime(2026, 10, 27, 16, 0, tzinfo=DENVER),
        plan_id="dev-proof",
        slice_id="week",
        reason="DEV proof of one slice",
        daily_running_count=0,
        daily_status_known=False,
    )
    assert unknown == "INTELLIGENCE_PUBMED_BACKFILL_DAILY_STATUS_UNKNOWN"
    digest = "sha256:" + "ab" * 32
    command = _GATE["daily"].COMMAND
    jobs = [
        {"name": name, "kind": "SCHEDULED", "image": {"digest": digest}, "run_command": "other"}
        for name in sorted(_GATE["daily"].BASE)
    ]
    scheduled = {
        "name": "intelligence-feed-daily",
        "kind": "SCHEDULED",
        "image": {"digest": digest},
        "run_command": command,
        "schedule": {"cron": "15 18 * * *", "time_zone": "America/Denver"},
    }
    baseline = {"jobs": [*jobs, scheduled]}
    spec = _GATE["build_backfill_spec"](baseline, plan_id="dev-proof", slice_id="week")
    kept = next(job for job in spec["jobs"] if job["name"] == "intelligence-feed-daily")
    assert kept == scheduled
    manual = next(job for job in spec["jobs"] if job["name"] == _GATE["JOB_NAME"])
    assert manual["kind"] == "PRE_DEPLOY"
    assert "schedule" not in manual
    assert "--backfill-plan-id dev-proof" in manual["run_command"]
    assert "--slice-id week" in manual["run_command"]
    rendered = _GATE["redact_outcome"](
        "noise api_key=secret email=person@example.test\n"
        + _GATE["OUTCOME_LOG_PREFIX"]
        + '{"requests":2,"slice_complete":true,"cursor":{"retstart":1,"last_pmid":"12345678",'
        + '"slice_complete":true,"remaining":0},"email":"person@example.test"}'
    )
    assert rendered is not None
    assert "email" not in rendered
    assert rendered["requests"] == 2


def test_backfill_run_ids_do_not_reuse_daily_ids() -> None:
    for source_id in SOURCE_ORDER:
        for attempt in (1, 2, 3):
            daily = daily_run_id(source_id, TODAY, reopen_attempt=attempt)
            for backfill_attempt in (1, 2, 3):
                assert backfill.backfill_run_id("dev-proof", "week", backfill_attempt) != daily
                assert (
                    backfill.backfill_source_run_id(
                        "dev-proof", "week", backfill_attempt, source_id
                    )
                    != daily
                )


def test_plan_file_is_a_token_not_a_free_text_window(tmp_path: Path) -> None:
    path = tmp_path / "dev-proof.json"
    path.write_text(
        json.dumps(
            {
                "plan_id": "dev-proof",
                "approved_by": "",
                "approved_at": "",
                "request_limit": 5,
                "item_limit": 200,
                "sources": list(SOURCE_ORDER),
                "slices": [{"slice_id": "week", "mindate": "2026-09-01", "maxdate": "2026-09-07"}],
            }
        ),
        encoding="utf-8",
    )
    loaded = backfill.load_backfill_plan("dev-proof", root=tmp_path)
    assert loaded.find("week").day_count() == 7
    with pytest.raises(PermissionError, match="INTELLIGENCE_PUBMED_BACKFILL_PLAN_INVALID"):
        backfill.load_backfill_plan("../dev-proof", root=tmp_path)


W1_PLAN_ID = "pubmed-w1-31-365d"
# R is the PROD watermark (last_entry_date 2026-10-26 for both sources) when
# Matthew approved the plan, 2026-10-27 8:18 AM MT.
W1_ANCHOR = date(2026, 10, 26)


def test_w1_plan_tiles_days_31_to_365_and_passes_the_prod_loader() -> None:
    path = backfill.BACKFILL_DIR / f"{W1_PLAN_ID}.json"
    assert path == ROOT / "config" / "intelligence" / "backfill" / f"{W1_PLAN_ID}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    plan = backfill.load_backfill_plan(W1_PLAN_ID)
    backfill.validate_backfill_approval(plan, "prod")
    assert plan.approved_by == "Matthew Caraway"
    assert plan.approved_at == "2026-10-27T08:18:00-06:00"
    assert plan.approved_request_limit == 5
    assert plan.request_limit == 5
    assert plan.item_limit == 200
    assert document["sources"] == ["pubmed-tick-borne", "pubmed-lyme-borrelia"]

    slices = plan.slices
    assert len(slices) == 12
    assert [item.slice_id for item in slices] == [f"w1-{n:02d}" for n in range(1, 13)]
    # Newest first, each slice ends the day before the next newer one starts.
    assert slices[0].maxdate == W1_ANCHOR - timedelta(days=31)
    assert slices[-1].mindate == W1_ANCHOR - timedelta(days=365)
    for newer, older in zip(slices, slices[1:], strict=False):
        assert older.maxdate == newer.mindate - timedelta(days=1)
    assert all(1 <= item.day_count() <= backfill.MAX_SLICE_DAYS for item in slices)
    assert sum(item.day_count() for item in slices) == 365 - 31 + 1

    # The newest slice sits just outside the daily run's first 30-day window.
    assert slices[0].maxdate == backfill.daily_first_window_start(W1_ANCHOR) - timedelta(days=1)

    def explode(url: str, params: Mapping[str, str], timeout: float) -> EntrezResponse:
        raise AssertionError("dry run called the provider")

    for item in slices:
        outcome, _sleeps = _run(
            explode,  # type: ignore[arg-type]
            plan,
            _seed(W1_ANCHOR),
            slice_id=item.slice_id,
            environment="prod",
            dry_run=True,
        )
        assert outcome["requests"] == 0
        assert outcome["writes"] == 0
        assert outcome["planned_request_count"] == 5
        assert outcome["mindate"] == item.mindate.isoformat()
        assert outcome["maxdate"] == item.maxdate.isoformat()


PROOF_PLAN_ID = "pubmed-proof-7d"


def test_proof_plan_is_one_7_day_slice_inside_w1_01_and_passes_the_prod_loader() -> None:
    path = backfill.BACKFILL_DIR / f"{PROOF_PLAN_ID}.json"
    assert path == ROOT / "config" / "intelligence" / "backfill" / f"{PROOF_PLAN_ID}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    plan = backfill.load_backfill_plan(PROOF_PLAN_ID)
    backfill.validate_backfill_approval(plan, "prod")
    assert plan.approved_by == "Matthew Caraway"
    assert plan.approved_at == "2026-10-27T10:41:00-06:00"
    assert plan.approved_request_limit == 5
    assert plan.request_limit == 5
    assert plan.item_limit == 200
    assert document["sources"] == ["pubmed-tick-borne", "pubmed-lyme-borrelia"]

    assert len(plan.slices) == 1
    proof = plan.find("proof-7d")
    assert proof.mindate == date(2026, 9, 19)
    assert proof.maxdate == date(2026, 9, 25)
    assert proof.day_count() == 7
    # The latest maxdate the runner allows with the 2026-10-26 watermark.
    assert proof.maxdate == backfill.daily_first_window_start(W1_ANCHOR) - timedelta(days=1)
    # The proof window lies inside w1-01 of the 31-365 day plan.
    w1_01 = backfill.load_backfill_plan(W1_PLAN_ID).find("w1-01")
    assert w1_01.mindate <= proof.mindate and proof.maxdate == w1_01.maxdate

    def explode(url: str, params: Mapping[str, str], timeout: float) -> EntrezResponse:
        raise AssertionError("dry run called the provider")

    outcome, _sleeps = _run(
        explode,  # type: ignore[arg-type]
        plan,
        _seed(W1_ANCHOR),
        slice_id="proof-7d",
        environment="prod",
        dry_run=True,
    )
    assert outcome["requests"] == 0
    assert outcome["writes"] == 0
    assert outcome["planned_request_count"] == 5
    assert outcome["mindate"] == "2026-09-19"
    assert outcome["maxdate"] == "2026-09-25"
