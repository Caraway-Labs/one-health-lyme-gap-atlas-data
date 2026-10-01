from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from lyme_gap_atlas_data import catalog_registration as registration


@pytest.mark.parametrize("limits", [(12, 1500), (37, 4321)])
@pytest.mark.parametrize("failed", [False, True])
def test_export_omits_option_limits_and_preserves_registration_evidence(
    monkeypatch: pytest.MonkeyPatch, limits: tuple[int, int], failed: bool
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(registration, "_TRACER", provider.get_tracer("registration-test"))
    received: list[tuple[str, int, int, str]] = []
    result: dict[str, int | str] = {
        "status": "COMPLETED",
        "processed_datasets": 3,
        "registered_resources": 7,
    }

    def register(
        config_sha256: str,
        maximum_artifacts: int,
        maximum_datasets: int,
        progress: registration.RegistrationProgress,
    ) -> dict[str, int | str]:
        received.append(
            (config_sha256, maximum_artifacts, maximum_datasets, progress.registration_run_id)
        )
        if failed:
            raise RuntimeError("registration failed")
        return result

    monkeypatch.setattr(registration, "_register_completed_discovery", register)
    try:
        if failed:
            with pytest.raises(RuntimeError, match="registration failed"):
                registration.register_completed_discovery("a" * 64, *limits)
        else:
            assert registration.register_completed_discovery("a" * 64, *limits) is result
        assert provider.force_flush()
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "catalog_registration.run"
        # Inspect the real SDK's exported, serialized attributes, not a fake span.
        attributes: dict[str, Any] = json.loads(span.to_json())["attributes"]
        assert "atlas.registration.maximum_artifacts" not in attributes
        assert "atlas.registration.maximum_datasets" not in attributes
        run_id = attributes["atlas.registration.run_id"]
        assert UUID(run_id)
        assert received == [("a" * 64, *limits, run_id)]
        if failed:
            assert attributes == {
                "atlas.registration.run_id": run_id,
                "error.type": "RuntimeError",
            }
            assert span.status.status_code is StatusCode.ERROR
        else:
            assert attributes == {
                "atlas.registration.run_id": run_id,
                "atlas.registration.status": "COMPLETED",
                "atlas.registration.processed_datasets": 3,
                "atlas.registration.registered_resources": 7,
            }
    finally:
        provider.shutdown()
