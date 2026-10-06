"""Canonical composition with synthetic policy/provider seams, never live approval."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_intelligence_feed import approved, definition
from test_intelligence_native_metadata import RAW, policy
from test_intelligence_recovery import (
    AcquisitionConnection,
    AcquisitionCursor,
    AcquisitionLedger,
    Objects,
)

from lyme_gap_atlas_data.ingestion import Tier
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import IntelligenceFileCheckpoints
from lyme_gap_atlas_data.ingestion.intelligence_effects import IntelligenceStageEffects
from lyme_gap_atlas_data.ingestion.intelligence_feed import FeedResponse
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.ingestion.types import RunState
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_raw_runtime import SQLiteRawLedger
from lyme_gap_atlas_data.intelligence_storage import IntelligenceStorageError
from lyme_gap_atlas_data.settings import PipelineSettings


def selected() -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    source = approved()
    source.update(source_id="cdc-vital-signs", registry_version=7)
    source["fetch_location"] = runtime.ENDPOINTS["cdc-vital-signs"]
    source["approved_hosts"] = ["tools.cdc.gov", "example.org"]
    receipt = {
        "source_id": source["source_id"],
        "registry_version": 7,
        "source_sha256": identity_hash(source),
        "decision_ref": "SYNTHETIC_FIXTURE_ONLY",
        "raw_policy_ref": "SYNTHETIC_RAW_30D_ONLY",
        "retention_policy_ref": source["access_use"]["content_retention_policy_ref"],
        "artifact_policy": "SYNTHETIC_RAW_30D_ONLY",
        "native_policy": policy(RAW, source).document(),
    }
    configured = replace(
        definition(source),
        endpoint_template=source["fetch_location"],
        definition_version=1,
        extra={},
        artifact_policy="REVIEW_REQUIRED",
    )
    return configured, source, [receipt]


class PilotCursor(AcquisitionCursor):
    def execute(self, statement: str, params: tuple[Any, ...] = (), **kwargs: Any) -> None:
        assert 0 < kwargs["timeout"] <= 30
        sql = " ".join(statement.split()).upper()
        if sql.startswith("SELECT CURRENT_USER()"):
            self.rows = [
                (
                    "OH_LYME_DEV_PIPELINE_SVC",
                    self.connection.ledger.role,
                    self.connection.ledger.database,
                    "OH_LYME_DEV_INGEST_XS_WH",
                )
            ]
        elif sql.startswith("SELECT REGISTRY_VERSION"):
            versions = [
                s["registry_version"]
                for s in self.connection.ledger.sources
                if s["source_id"] == params[0]
            ]
            self.rows = [(max(versions),)] if versions else []
        else:
            super().execute(statement, params)


class PilotConnection(AcquisitionConnection):
    def cursor(self) -> PilotCursor:
        return PilotCursor(self)


def test_missing_policy_stops_before_credentials_or_dns() -> None:
    configured, _, _ = selected()

    def forbidden() -> Any:
        pytest.fail("Missing policy must not access the provider")

    with pytest.raises(PermissionError, match="REVIEWED_POLICY_REQUIRED"):
        runtime.compose_pilot(
            configured, receipts=[], connection_factory=forbidden, settings=PipelineSettings()
        )


@pytest.mark.parametrize("failure", ["unapproved", "version", "hash", "context"])
def test_registry_and_policy_drift_stop_before_dns(failure: str) -> None:
    configured, source, receipts = selected()
    ledger = AcquisitionLedger()
    ledger.sources = [source]
    if failure == "unapproved":
        source["approval"]["status"] = "pending"
    elif failure == "version":
        receipts[0]["registry_version"] = 1
    elif failure == "hash":
        receipts[0]["source_sha256"] = "0" * 64
    else:
        ledger.role = "OH_LYME_DEV_READ"
    with pytest.raises((PermissionError, ValueError, IntelligenceStorageError)):
        runtime.compose_pilot(
            configured,
            receipts=receipts,
            connection_factory=lambda: PilotConnection(ledger),
            settings=PipelineSettings(),
        )
    assert not ledger.requests and not ledger.captures


def test_latest_registry_version_is_discovered_without_yaml_self_approval() -> None:
    configured, source, receipts = selected()
    ledger = AcquisitionLedger()
    ledger.sources = [source]
    orchestrator, loaded = runtime.compose_pilot(
        configured,
        receipts=receipts,
        connection_factory=lambda: PilotConnection(ledger),
        settings=PipelineSettings(),
    )
    assert loaded.definition_version == 7 and configured.definition_version == 1
    assert loaded.extra["intelligence_registry"] == source
    assert orchestrator.store.feed_retention is orchestrator._adapter_override.feed_retention
    assert orchestrator._effects_override.feed_retention is orchestrator.store.feed_retention
    assert not ledger.requests and not ledger.captures


def test_pilot_request_and_deadline_bound_without_retry_or_redirect() -> None:
    now = [0.0]
    budget = runtime.PilotBudget(lambda: now[0])
    calls = []

    def sender(*args: Any) -> FeedResponse:
        calls.append(args)
        return FeedResponse(200, {}, b"ok")

    budget.request(sender, "https://example.org/feed", "8.8.8.8", {}, 10_000_000, 120)
    assert calls[0][3:] == (2 * 1024 * 1024, 30)
    with pytest.raises(PermissionError, match="REQUEST_LIMIT"):
        budget.request(sender, "https://example.org/feed", "8.8.8.8", {}, 1, 1)
    now[0] = 300
    with pytest.raises(PermissionError, match="DEADLINE"):
        budget.remaining()
    budget = runtime.PilotBudget()
    with pytest.raises(PermissionError, match="RESPONSE_REQUIRED"):
        budget.request(lambda *args: FeedResponse(302, {}, b""), "url", "ip", {}, 1, 1)
    assert budget.requests == 1


def test_replay_size_and_owned_query_deadline_precede_io() -> None:
    adapter = runtime.PilotFeedAdapter()
    configured, _, _ = selected()
    with pytest.raises(PermissionError, match="REPLAY_LIMIT"):
        adapter._retained_entries(configured, {"xml_base64": "a" * (3 * 1024 * 1024)})
    now = [0.0]
    budget = runtime.PilotBudget(lambda: now[0])

    class Cursor:
        def execute(self, *args: Any, **kwargs: Any) -> None:
            pytest.fail("An expired pass must not issue SQL")

    cursor = runtime._Cursor(Cursor(), budget)
    now[0] = 300
    with pytest.raises(PermissionError, match="DEADLINE"):
        cursor.execute("SELECT 1")
    assert budget.queries == 0


def test_checked_in_definitions_and_policy_receipts_are_not_registry_approvals() -> None:
    assert json.loads(runtime.RECEIPTS.read_text())["receipts"] == []
    for name in ("cdc_vital_signs", "nih_news_releases"):
        configured = load_source_definition(Path(f"config/sources/intelligence_{name}.yml"))
        assert configured.endpoint_template == runtime.ENDPOINTS[configured.source_id]
        assert "intelligence_registry" not in configured.extra
        assert configured.artifact_policy == "REVIEW_REQUIRED"


def test_composed_run_repoll_and_fresh_resume_preserve_native_capture_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, source, receipts = selected()
    ledger = AcquisitionLedger()
    ledger.sources = [source]
    objects = Objects()
    calls = []

    class Checkpoints(IntelligenceFileCheckpoints):
        def save(self, state: RunState) -> None:
            ledger.runs[state.ingestion_run_id] = state.resource_key
            super().save(state)

    def checkpoints(retention: Any, **kwargs: Any) -> Checkpoints:
        retention.clock = lambda: "2026-10-06T00:00:00Z"
        return Checkpoints(tmp_path / "checkpoints", retention)

    def sender(*args: Any) -> FeedResponse:
        calls.append(args)
        return FeedResponse(200, {}, RAW)

    monkeypatch.setattr(
        runtime, "SnowflakeRawLedger", lambda *args: SQLiteRawLedger(tmp_path / "raw.sqlite")
    )
    monkeypatch.setattr(runtime, "IntelligenceSnowflakeCheckpoints", checkpoints)
    monkeypatch.setattr(
        runtime,
        "IntelligenceStageEffects",
        lambda *args, **kwargs: IntelligenceStageEffects(*args, spaces_client=objects, **kwargs),
    )
    monkeypatch.setattr(runtime, "_resolve", lambda *args: ("8.8.8.8",))
    monkeypatch.setattr(runtime, "_request", sender)

    def compose() -> tuple[Any, Any]:
        return runtime.compose_pilot(
            configured,
            receipts=receipts,
            connection_factory=lambda: PilotConnection(ledger),
            settings=PipelineSettings(),
        )

    first, loaded = compose()
    state = first.run(loaded, tier=Tier.B)
    assert state.status.value == "SUCCEEDED"
    assert len(calls) == len(ledger.captures) == len(ledger.revisions) == 1
    second, loaded = compose()
    assert second.run(loaded, tier=Tier.B).status.value == "SUCCEEDED"
    assert len(calls) == len(ledger.captures) == 2 and len(ledger.revisions) == 1
    resumed, loaded = compose()
    assert resumed.resume(state.ingestion_run_id, definition=loaded).status.value == "SUCCEEDED"
    assert len(calls) == len(ledger.captures) == 2
    captures = [json.loads(row[1]) for row in ledger.captures.values()]
    assert all(item["registry_version"] == 7 for item in captures)
    assert all(item["publisher_metadata"]["authors"] == ["Test Author"] for item in captures)
    assert all(item["provenance"]["artifact_id"] for item in captures)
    assert all(item["native_metadata"] and item["derived_metadata"] == {} for item in captures)
    assert len(ledger.contexts) == 2 and objects.content
