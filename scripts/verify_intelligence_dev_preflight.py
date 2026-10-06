"""Fixed read-only DEV intelligence metadata preflight; private evidence only."""

from __future__ import annotations

import base64
import json
import os
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.climate_dev_validation import DEV, ROLE, USER, WAREHOUSE

TARGETS = (
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"),
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_RAW_RETENTION_AUDIT"),
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_SOURCE_VERSIONS"),
    ("VIEW", "PRESENTATION", "INTELLIGENCE_FEED_V"),
    ("VIEW", "PRESENTATION", "INTELLIGENCE_FEED_V2"),
)


def budget(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if value.get("billing_reconciled") is not True:
        raise ValueError("FEED_BILLING_UNRECONCILED")
    amounts = [Decimal(str(value[key])) for key in ("spent_usd", "reserved_usd", "usd_per_credit")]
    if any(not amount.is_finite() or amount < 0 for amount in amounts) or amounts[2] <= 0:
        raise ValueError("FEED_BUDGET_INVALID")
    # One warehouse resume minimum, fixed 50-second entire process ceiling.
    minimum = Decimal("1.35") / 60 * amounts[2]
    forecast = Decimal(str(value["forecast_total_usd"]))
    if not forecast.is_finite() or forecast < minimum:
        raise ValueError("FEED_TOTAL_FORECAST_REQUIRED")
    if sum(amounts[:2]) + forecast > 5:
        raise ValueError("FEED_BUDGET_EXHAUSTED")
    requests = value["feed_http_requests_used"]
    if type(requests) is not int or not 0 <= requests <= 6:
        raise ValueError("FEED_REQUEST_ACCOUNTING_INVALID")
    if not value.get("evidence_ref"):
        raise ValueError("FEED_BUDGET_EVIDENCE_REQUIRED")
    return {**value, "forecast_usd": str(forecast), "new_feed_http_requests": 0}


def rows(cursor: Any) -> list[dict[str, Any]]:
    return [
        dict(zip([column[0] for column in cursor.description], row, strict=True))
        for row in cursor.fetchall()
    ]


def inspect(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=10, STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=2"
    )
    cursor.execute(
        "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()", timeout=10
    )
    if tuple(cursor.fetchone()) != (USER, ROLE, DEV, WAREHOUSE):
        raise ValueError("FEED_PREFLIGHT_IDENTITY")
    objects = []
    for kind, schema, name in TARGETS:
        qualified = f"{DEV}.{schema}.{name}"
        cursor.execute(f"SHOW {kind}S LIKE '{name}' IN SCHEMA {DEV}.{schema}", timeout=10)
        catalog = [row for row in rows(cursor) if str(row.get("name", row.get("NAME"))) == name]
        entry: dict[str, Any] = {
            "target": qualified,
            "kind": kind,
            "catalog": catalog,
            "state": "VISIBLE" if catalog else "NOT_VISIBLE_NOT_PROOF_OF_ABSENCE",
        }
        if catalog:
            cursor.execute(f"DESCRIBE {kind} {qualified}", timeout=10)
            entry["columns"] = rows(cursor)
            cursor.execute(f"SHOW GRANTS ON {kind} {qualified}", timeout=10)
            entry["grants"] = rows(cursor)
            if kind == "VIEW":
                cursor.execute(f"SELECT GET_DDL('VIEW','{qualified}')", timeout=10)
                entry["ddl"] = cursor.fetchone()[0]
        objects.append(entry)
    # No registry payload, rights records, endpoint, or native metadata is exposed.
    registry = next(
        entry for entry in objects if entry["target"].endswith("INTELLIGENCE_SOURCE_VERSIONS")
    )
    if registry["state"] == "VISIBLE":
        cursor.execute(
            f"SELECT source_id,registry_version,registry_sha256 FROM {DEV}.GOVERNANCE."
            "INTELLIGENCE_SOURCE_VERSIONS WHERE source_id IN "
            "('cdc-vital-signs','nih-news-releases') QUALIFY ROW_NUMBER() OVER"
            "(PARTITION BY source_id ORDER BY registry_version DESC)=1 LIMIT 2",
            timeout=10,
        )
        registry["latest_version_receipts"] = rows(cursor)
    return {"objects": objects, "writes": False, "source_registration_authorized": False}


def seal(report: dict[str, Any], public_key: rsa.RSAPublicKey) -> str:
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    payload = json.dumps(report, default=str, sort_keys=True).encode()
    wrapped = public_key.encrypt(
        key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return json.dumps(
        {
            "format": "RSA-OAEP-SHA256/AES-256-GCM",
            "key": base64.b64encode(wrapped).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(
                AESGCM(key).encrypt(nonce, payload, b"feed-dev-preflight-v1")
            ).decode(),
        }
    )


def main() -> None:
    public_key = serialization.load_pem_public_key(os.environ["FEED_EVIDENCE_PUBLIC_KEY"].encode())
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise SystemExit("FEED_EVIDENCE_RSA_PUBLIC_KEY_REQUIRED")
    accounting = budget(os.environ["FEED_PREFLIGHT_BUDGET_JSON"])
    output = Path(os.environ["RUNNER_TEMP"]) / "feed-preflight-private.encrypted.json"
    report: dict[str, Any] = {
        "budget": accounting,
        "code_sha": os.environ.get("GITHUB_SHA"),
        "state": "FAILED",
    }

    def expire() -> None:
        report["state"] = "TIMED_OUT_PARTIAL_EVIDENCE"
        output.write_text(seal(report, public_key), encoding="utf-8")
        output.chmod(0o600)
        os._exit(124)

    watchdog = threading.Timer(50, expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            report.update(inspect(cursor))
        report["state"] = "COMPLETE"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise SystemExit("FEED_PREFLIGHT_FAILED_SEE_PRIVATE_ARTIFACT") from None
    finally:
        output.write_text(seal(report, public_key), encoding="utf-8")
        output.chmod(0o600)
        watchdog.cancel()


if __name__ == "__main__":
    main()
