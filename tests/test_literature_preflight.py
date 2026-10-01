"""Preflight collects safe blockers before claim or provider requests."""

from __future__ import annotations

import pytest

from lyme_gap_atlas_data.literature_preflight import (
    _WRITE_COLUMNS,
    _classification_contract_supported,
    _effective_grants,
    _snowflake_contract,
    literature_preflight,
)
from lyme_gap_atlas_data.settings import PipelineSettings

# Exact CHECK_CLAUSE serialization read under OH_LYME_PROD_RUNTIME on 2026-10-01.
_LIVE_CLASSIFICATION_CLAUSE = (
    "classification IN (\n"
    "      'provider_rejected_pre_inference',\n"
    "      'contract_remediation_reopen'\n"
    "    )"
)


def test_preflight_collects_all_blockers_without_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_COMMIT", "private-deployment-token")
    monkeypatch.setenv("IMAGE_DIGEST", "private-image-token")
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
    assert result["code_sha"] == "unknown"
    assert result["image_sha"] == "unknown"


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


def test_all_operation_reports_stage_owned_blockers_once() -> None:
    settings = PipelineSettings(
        _env_file=None,  # type: ignore[call-arg]
        topx_env="dev",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
    )
    calls: list[str] = []

    def contract(_settings: PipelineSettings, operation: str) -> dict[str, object]:
        calls.append(operation)
        return {"missing_capabilities": []}

    result = literature_preflight(settings, operation="all", snowflake_probe=contract)
    assert result["status"] == "BLOCKED"
    assert calls == ["discover", "extract", "build-corpus"]
    assert {item["stage"] for item in result["blockers"]} >= {"discover", "extract"}
    assert len(result["run_id"]) == 36


def test_effective_grants_include_inherited_role() -> None:
    class Cursor:
        current = ""

        def execute(self, sql: str) -> None:
            self.current = sql

        def fetchall(self) -> list[tuple[str, str, str, str]]:
            if self.current.endswith("RUNTIME"):
                return [("", "USAGE", "ROLE", "PARENT")]
            return [("", "INSERT", "TABLE", "DB.KNOWLEDGE_GRAPH.PAPERS")]

    assert _effective_grants(Cursor(), "RUNTIME") == [
        ("INSERT", "TABLE", "DB.KNOWLEDGE_GRAPH.PAPERS")
    ]


@pytest.mark.parametrize("operation", ["discover", "extract", "build-corpus"])
@pytest.mark.parametrize("valid_contract", [False, True])
@pytest.mark.parametrize(
    "classification_table", ["EXTRACTION_ATTEMPT_CLASSIFICATIONS", "OLD_TABLE"]
)
@pytest.mark.parametrize("classification_form", ["positive", "negative", "uppercase"])
def test_preflight_detects_missing_column_and_write_privilege(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    valid_contract: bool,
    classification_table: str,
    classification_form: str,
) -> None:
    statements: list[str] = []

    class Cursor:
        sql = ""
        metadata_table = ""

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, _args: object = None) -> None:
            self.sql = sql
            statements.append(sql)
            if "INFORMATION_SCHEMA.COLUMNS" in sql and isinstance(_args, tuple):
                self.metadata_table = str(_args[1])
            if "FROM KNOWLEDGE_GRAPH.PAPERS LIMIT 0" in sql:
                raise RuntimeError("unknown column")

        def fetchone(self) -> tuple[str, str]:
            return ("RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS_DEV")

        def fetchall(self) -> list[tuple[str, ...]]:
            if self.sql.startswith("SHOW GRANTS"):
                prefix = "ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE."
                if valid_contract:
                    return [
                        ("", "USAGE", "PROCEDURE", prefix + name + "(VARCHAR, NUMBER)")
                        for name in ("SP_RESERVE_KG_LLM_BUDGET", "SP_FINALIZE_KG_LLM_BUDGET")
                    ]
                return [
                    (
                        "",
                        "USAGE",
                        "PROCEDURE",
                        "OTHER_DB.GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(VARCHAR)",
                    ),
                    ("", "USAGE", "PROCEDURE", prefix + "SP_FINALIZE_KG_LLM_BUDGET_COPY(VARCHAR)"),
                ]
            if "CK_PMC_ATTEMPT_CLASSIFICATION" in self.sql:
                if (
                    "CONSTRAINT_TABLE = 'EXTRACTION_ATTEMPT_CLASSIFICATIONS'" in self.sql
                    and classification_table != "EXTRACTION_ATTEMPT_CLASSIFICATIONS"
                ):
                    return []
                clause = (
                    _LIVE_CLASSIFICATION_CLAUSE
                    if valid_contract
                    else "CLASSIFICATION IN ('provider_rejected_pre_inference')"
                )
                if classification_form == "negative":
                    clause = clause.replace(" IN ", " NOT IN ")
                elif classification_form == "uppercase":
                    clause = clause.upper()
                return [(clause,)]
            if (
                "INFORMATION_SCHEMA.COLUMNS" in self.sql
                and self.metadata_table == "PUBMED_DISCOVERY_RUNS"
            ):
                return [
                    (column,)
                    for column in _WRITE_COLUMNS["KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS"].split(
                        ", "
                    )
                    if column != "RAW_ARTIFACT_ID"
                ]
            return [("PMID",)]

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(
        "lyme_gap_atlas_data.literature_preflight.connect", lambda _settings: Connection()
    )
    settings = PipelineSettings(
        _env_file=None,  # type: ignore[call-arg]
        snowflake_role="RUNTIME",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_DEV",
    )
    missing = _snowflake_contract(settings, operation)["missing_capabilities"]
    assert "KNOWLEDGE_GRAPH.PAPERS" in missing
    assert any("FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS LIMIT 0" in sql for sql in statements)
    if operation == "discover":
        assert "KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS:UPDATE" in missing
        assert "KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS:COLUMNS" in missing
        assert "RAW_ARTIFACT_ID" in _WRITE_COLUMNS["KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS"]
    if operation == "extract":
        assert "KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS:COLUMNS" in missing
        assert ("PMC_ATTEMPT_CLASSIFICATION_CONTRACT" in missing) is not (
            valid_contract
            and classification_table == "EXTRACTION_ATTEMPT_CLASSIFICATIONS"
            and classification_form == "positive"
        )
        for capability in (
            "GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET:USAGE",
            "GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET:USAGE",
        ):
            assert (capability in missing) is not valid_contract
    if operation != "build-corpus":
        assert "GOVERNANCE.RAW_ARTIFACTS:COLUMNS" in missing


@pytest.mark.parametrize(
    ("clause", "supported"),
    [
        (_LIVE_CLASSIFICATION_CLAUSE, True),
        (
            "CLASSIFICATION IN ('provider_rejected_pre_inference', 'contract_remediation_reopen')",
            True,
        ),
        (
            "(\"CLASSIFICATION\" IN ('contract_remediation_reopen', "
            "'provider_rejected_pre_inference'))",
            True,
        ),
        (
            "((classification in ('provider_rejected_pre_inference', "
            "'contract_remediation_reopen')))",
            True,
        ),
        (
            "CLASSIFICATION NOT IN ('provider_rejected_pre_inference', "
            "'contract_remediation_reopen')",
            False,
        ),
        (
            "CLASSIFICATION IN ('PROVIDER_REJECTED_PRE_INFERENCE', 'CONTRACT_REMEDIATION_REOPEN')",
            False,
        ),
        (
            "OTHER_COLUMN IN ('provider_rejected_pre_inference', 'contract_remediation_reopen')",
            False,
        ),
        (
            "CLASSIFICATION IN ('provider_rejected_pre_inference', 'contract_remediation_reopen') "
            "AND FALSE",
            False,
        ),
        (
            "CLASSIFICATION = 'provider_rejected_pre_inference' "
            "OR CLASSIFICATION = 'contract_remediation_reopen'",
            False,
        ),
        ("CLASSIFICATION IN ('provider_rejected_pre_inference')", False),
        ("", False),
    ],
)
def test_classification_constraint_requires_supported_positive_membership(
    clause: str, supported: bool
) -> None:
    assert _classification_contract_supported(clause) is supported
