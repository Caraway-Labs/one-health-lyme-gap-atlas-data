"""Guard the narrow DEV Dataset Discovery service identity bootstrap."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap_dataset_discovery_runtime_user_dev.sql"
ATTACHMENT = ROOT / "scripts/attach_dataset_discovery_auth_policy_dev.sql"


def test_runtime_identity_bootstrap_is_dev_only_and_has_no_secret_or_extra_role() -> None:
    source = "\n".join(
        line
        for line in BOOTSTRAP.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).upper()
    statements = [statement.strip() for statement in source.split(";") if statement.strip()]
    assert len(statements) == 5
    assert statements[0].startswith("CREATE USER IF NOT EXISTS OH_LYME_DEV_DATASET_DISCOVERY_SVC")
    assert "TYPE = SERVICE_AGENT" in statements[0]
    assert "DEFAULT_ROLE = OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME" in statements[0]
    assert "DEFAULT_NAMESPACE = ONE_HEALTH_LYME_GAP_ATLAS_DEV.DATASET_DISCOVERY" in statements[0]
    assert " ".join(statements[1].split()) == (
        "GRANT ROLE OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME TO USER OH_LYME_DEV_DATASET_DISCOVERY_SVC"
    )
    assert statements[2] == "ALTER USER OH_LYME_DEV_DATASET_DISCOVERY_SVC SET TYPE = SERVICE_AGENT"
    assert statements[3] == "CREATE SCHEMA IF NOT EXISTS ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY"
    assert " ".join(statements[4].split()).startswith(
        "CREATE AUTHENTICATION POLICY IF NOT EXISTS "
        "ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY.DATASET_DISCOVERY_SERVICE_AGENT_AUTH"
    )
    assert "AUTHENTICATION_METHODS = ('PROGRAMMATIC_ACCESS_TOKEN')" in statements[4]
    assert "NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED" in statements[4]
    assert "REQUIRE_ROLE_RESTRICTION_FOR_SERVICE_USERS = TRUE" in statements[4]
    attachment_source = "\n".join(
        line
        for line in ATTACHMENT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).upper()
    attachment_statements = [
        statement.strip() for statement in attachment_source.split(";") if statement.strip()
    ]
    assert len(attachment_statements) == 1
    assert " ".join(attachment_statements[0].split()) == (
        "ALTER USER OH_LYME_DEV_DATASET_DISCOVERY_SVC SET AUTHENTICATION POLICY "
        "ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY.DATASET_DISCOVERY_SERVICE_AGENT_AUTH"
    )
    for forbidden in (
        "OH_LYME_PROD",
        "DATASET_DISCOVERY_REVIEWER",
        "DATASET_DISCOVERY_WRITE_OWNER",
        "SNOWFLAKE_PAT",
        "RSA_PUBLIC_KEY",
        "PASSWORD",
    ):
        assert forbidden not in source
