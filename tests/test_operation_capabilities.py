from copy import deepcopy

import pytest

from lyme_gap_atlas_data.operation_capabilities import (
    assess_operation,
    inspect_live_facts,
    load_contract,
    operation_plan,
)


def test_contract_renders_a_complete_dev_operation_plan() -> None:
    plan = operation_plan(load_contract(), operation="governed_source_run", environment="dev")
    assert plan["expected_executor_role"] == "OH_LYME_DEV_RUNTIME"
    assert plan["grant_authority_role"] == "OH_LYME_DEV_OWNER"
    assert plan["database"] == "ONE_HEALTH_LYME_GAP_ATLAS_DEV"


def test_missing_runtime_insert_and_grant_authority_are_not_conflated() -> None:
    report = assess_operation(
        load_contract(),
        operation="semantic_release",
        environment="prod",
        observed={
            "identity": {
                "role": "OH_LYME_PROD_MIGRATION_DEPLOYER",
                "database": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            },
            "applied_migrations": ["V071", "V072", "V073", "V099"],
            "capabilities": {"PRESENTATION.SEMANTIC_RELEASES:INSERT": False},
            "approval": True,
        },
    )
    finding = next(
        item for item in report["findings"] if item["check"].startswith("runtime_capability")
    )
    assert finding["status"] == "BLOCKED"
    assert "cannot self-grant" in finding["next_authorized_action"]


def test_uninspected_facts_are_unknown_and_block_consequential_operation() -> None:
    report = assess_operation(load_contract(), operation="api_read", environment="prod")
    assert report["status"] == "UNKNOWN"
    assert report["mutation_started"] is False


def test_semantic_release_plan_keeps_v099_prod_only() -> None:
    contract = load_contract()
    for environment in ("dev", "prod"):
        plan = operation_plan(contract, operation="semantic_release", environment=environment)
        assert plan["expected_executor_role"] == (
            f"OH_LYME_{environment.upper()}_MIGRATION_DEPLOYER"
        )
        assert plan["object_capabilities"] == ["PRESENTATION.SEMANTIC_RELEASES:INSERT"]
        expected = ["V071", "V072", "V073"] + (["V099"] if environment == "prod" else [])
        assert plan["required_migrations"] == expected
        report = assess_operation(
            contract,
            operation="semantic_release",
            environment=environment,
            observed={"applied_migrations": ["V071", "V072", "V073"]},
        )
        findings = {item["check"]: item["status"] for item in report["findings"]}
        assert findings["migration_dependencies"] == ("PASS" if environment == "dev" else "BLOCKED")
        assert findings["effective_identity"] == "UNKNOWN"
        assert findings["runtime_capability:PRESENTATION.SEMANTIC_RELEASES:INSERT"] == "UNKNOWN"
        assert report["mutation_started"] is False


@pytest.mark.parametrize(
    "scoped",
    [{"staging": ["V099"]}, {"dev": ["V099"]}, {"prod": ["V999"]}, {"prod": "V099"}],
)
def test_contract_rejects_invalid_environment_migration_dependencies(tmp_path, scoped) -> None:
    import yaml

    contract = deepcopy(load_contract())
    contract["operations"]["semantic_release"]["required_migrations_by_environment"] = scoped
    path = tmp_path / "contract.yml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(ValueError):
        load_contract(path)


def test_shared_prod_only_migration_is_rejected(tmp_path) -> None:
    import yaml

    contract = deepcopy(load_contract())
    contract["operations"]["semantic_release"]["required_migrations"].append("V099")
    path = tmp_path / "contract.yml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="outside dev scope"):
        load_contract(path)


def test_read_only_inspector_does_not_claim_to_be_the_runtime_executor() -> None:
    report = assess_operation(
        load_contract(),
        operation="governed_source_run",
        environment="dev",
        observed={
            "identity": {
                "role": "OH_LYME_DEV_READ",
                "database": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            },
            "applied_migrations": ["V069"],
        },
    )
    findings = {item["check"]: item["status"] for item in report["findings"]}
    assert findings["effective_identity"] == "PASS"
    assert findings["execution_identity"] == "UNKNOWN"
    assert findings["grant_authority"] == "UNKNOWN"


def test_contract_rejects_unknown_alias_and_missing_migration() -> None:
    contract = deepcopy(load_contract())
    contract["operations"]["api_read"]["executor"] = "invented"
    with pytest.raises(ValueError, match="unknown role alias"):
        from lyme_gap_atlas_data import operation_capabilities

        original = operation_capabilities.yaml.safe_load
        try:
            operation_capabilities.yaml.safe_load = lambda _value: contract
            load_contract()
        finally:
            operation_capabilities.yaml.safe_load = original


def test_live_inspection_collects_only_identity_and_migration_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def execute(self, _query: str) -> None:
            return None

        def fetchone(self) -> tuple[str, str, str, str]:
            return (
                "service",
                "OH_LYME_DEV_READ",
                "OH_LYME_DEV_INGEST_XS_WH",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            )

        def fetchall(self) -> list[tuple[str]]:
            return [("V069",)]

        def close(self) -> None:
            return None

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(
        "lyme_gap_atlas_data.operation_capabilities.connect", lambda _settings: Connection()
    )
    facts = inspect_live_facts()
    assert facts["identity"]["role"] == "OH_LYME_DEV_READ"
    assert facts["applied_migrations"] == ["V069"]
    assert "capabilities" not in facts


def test_named_connection_live_inspection_uses_only_fixed_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> object:
        calls.append(args)
        payload = (
            '[{"CURRENT_USER":"service","CURRENT_ROLE":"OH_LYME_DEV_READ",'
            '"CURRENT_WAREHOUSE":"OH_LYME_DEV_INGEST_XS_WH",'
            '"CURRENT_DATABASE":"ONE_HEALTH_LYME_GAP_ATLAS_DEV"}]'
            if len(calls) == 1
            else '[{"VERSION":"V069"}]'
        )
        return type("Result", (), {"stdout": payload})()

    monkeypatch.setattr("lyme_gap_atlas_data.operation_capabilities.subprocess.run", fake_run)
    facts = inspect_live_facts("ATLAS_DEV_READ")
    assert facts["applied_migrations"] == ["V069"]
    assert all("SELECT" in call[-1] for call in calls)
    with pytest.raises(ValueError, match="connection name"):
        inspect_live_facts("not-a-connection")


def test_named_connection_inspection_reports_a_missing_runtime_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        [
            '[{"CURRENT_USER":"service","CURRENT_ROLE":"OH_LYME_DEV_READ",'
            '"CURRENT_WAREHOUSE":"OH_LYME_DEV_INGEST_XS_WH",'
            '"CURRENT_DATABASE":"ONE_HEALTH_LYME_GAP_ATLAS_DEV"}]',
            '[{"VERSION":"V069"}]',
            '[{"privilege":"INSERT","name":"ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.SCHEMA_MIGRATIONS"}]',
        ]
    )

    def fake_run(_args: list[str], **_kwargs: object) -> object:
        return type("Result", (), {"stdout": next(payloads)})()

    monkeypatch.setattr("lyme_gap_atlas_data.operation_capabilities.subprocess.run", fake_run)
    plan = operation_plan(load_contract(), operation="governed_source_run", environment="dev")
    facts = inspect_live_facts("ATLAS_DEV_READ", plan=plan)
    assert facts["capabilities"] == {"GOVERNANCE.INGESTION_RUNS:INSERT": False}
