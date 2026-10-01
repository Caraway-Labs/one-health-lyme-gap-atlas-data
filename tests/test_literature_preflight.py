"""Preflight collects safe blockers before claim or provider requests."""

from __future__ import annotations

from lyme_gap_atlas_data.literature_preflight import literature_preflight
from lyme_gap_atlas_data.settings import PipelineSettings


def test_preflight_collects_all_blockers_without_secret_values() -> None:
    settings = PipelineSettings(
        _env_file=None,  # type: ignore[call-arg]
        topx_env="dev",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        groq_api_key="private-groq",
        openai_api_key=None,
        neo4j_uri="bolt://private.example:7687",
        neo4j_runtime_password="private-password",
        spaces_endpoint="https://private.example",
        spaces_access_key_id="private-id",
        spaces_secret_access_key="private-key",
    )

    def contract(_settings: PipelineSettings, _operation: str) -> dict[str, object]:
        return {"missing_capabilities": ["KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS"]}

    def unavailable(_settings: PipelineSettings) -> None:
        raise RuntimeError("private-password and secret response")

    result = literature_preflight(
        settings,
        operation="extract",
        snowflake_probe=contract,
        spaces_probe=unavailable,
        neo4j_probe=unavailable,
    )
    assert result["status"] == "BLOCKED"
    assert len(result["blockers"]) == 4
    assert {item["failure_category"] for item in result["blockers"]} == {
        "preflight_configuration",
        "runtime_contract",
        "artifact_transport",
        "graph_publication",
    }
    assert "private-password" not in str(result)
    assert "private-groq" not in str(result)
    assert "secret response" not in str(result)


def test_ready_preflight_does_not_mutate() -> None:
    settings = PipelineSettings(
        _env_file=None,  # type: ignore[call-arg]
        topx_env="dev",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        ncbi_email="reader@example.test",
        spaces_endpoint="https://spaces.example",
        spaces_access_key_id="id",
        spaces_secret_access_key="secret",
    )
    calls: list[str] = []

    def contract(_settings: PipelineSettings, operation: str) -> dict[str, object]:
        calls.append(operation)
        return {"missing_capabilities": []}

    def spaces(_settings: PipelineSettings) -> None:
        calls.append("spaces")

    result = literature_preflight(
        settings, operation="discover", snowflake_probe=contract, spaces_probe=spaces
    )
    assert result["status"] == "READY"
    assert calls == ["discover", "spaces"]
