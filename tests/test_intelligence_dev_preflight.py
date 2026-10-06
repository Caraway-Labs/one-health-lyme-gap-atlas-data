import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "feed_preflight", Path(__file__).parents[1] / "scripts/verify_intelligence_dev_preflight.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_budget_requires_reconciled_actual_cost():
    with pytest.raises(ValueError, match="UNRECONCILED"):
        module.budget('{"billing_reconciled":false}')
    with pytest.raises(ValueError, match="EXHAUSTED"):
        module.budget(
            json.dumps(
                {
                    "billing_reconciled": True,
                    "spent_usd": 5,
                    "reserved_usd": 0,
                    "usd_per_credit": 3,
                    "forecast_total_usd": "0.1",
                    "feed_http_requests_used": 2,
                    "evidence_ref": "private-receipt",
                }
            )
        )


def test_budget_counts_prior_requests_without_consuming_another():
    result = module.budget(
        json.dumps(
            {
                "billing_reconciled": True,
                "spent_usd": 0.1,
                "reserved_usd": 0,
                "usd_per_credit": 3,
                "forecast_total_usd": "0.1",
                "feed_http_requests_used": 6,
                "evidence_ref": "private-receipt",
            }
        )
    )
    assert result["new_feed_http_requests"] == 0
    assert result["forecast_usd"] == "0.1"


class Cursor:
    def __init__(self, identity):
        self.identity = identity
        self.sql = []
        self.description = [("name",)]

    def execute(self, sql, **kwargs):
        self.sql.append(sql)

    def fetchone(self):
        return self.identity

    def fetchall(self):
        return []


def test_wrong_identity_stops_before_object_inspection():
    cursor = Cursor((module.USER, "ACCOUNTADMIN", module.DEV, module.WAREHOUSE))
    with pytest.raises(ValueError, match="IDENTITY"):
        module.inspect(cursor)
    assert len(cursor.sql) == 2


def test_hidden_objects_are_unknown_and_no_registration_read_or_mutation():
    cursor = Cursor((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    result = module.inspect(cursor)
    assert len(result["objects"]) == 5
    assert all(item["state"] == "NOT_VISIBLE_NOT_PROOF_OF_ABSENCE" for item in result["objects"])
    assert len(cursor.sql) == 7
    assert not any("GET_DDL" in sql or "registry_sha256" in sql for sql in cursor.sql)
    assert result["writes"] is False


def test_evidence_is_encrypted_for_reviewer_only():
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sealed = module.seal({"private_inventory": "sensitive"}, private.public_key())
    assert "sensitive" not in sealed
    envelope = json.loads(sealed)
    key = private.decrypt(
        base64.b64decode(envelope["key"]),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    payload = AESGCM(key).decrypt(
        base64.b64decode(envelope["nonce"]),
        base64.b64decode(envelope["ciphertext"]),
        b"feed-dev-preflight-v1",
    )
    assert json.loads(payload) == {"private_inventory": "sensitive"}


def test_workflow_exits_private_mode_before_identity_stdout_and_migrations():
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    branch = workflow.index('if [ "$DIAGNOSE_INTELLIGENCE_DEV" = "true" ]')
    execute = workflow.index("uv run python scripts/verify_intelligence_dev_preflight.py", branch)
    exit_position = workflow.index("exit 0", execute)
    assert branch < execute < exit_position < workflow.index("SELECT CURRENT_ACCOUNT()")
    assert "feed-preflight-private.encrypted.json" in workflow
    assert "retention-days: 1" in workflow
