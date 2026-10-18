"""Verify ML138 frozen handoff; optional bounded named-PAT publication.

No inference, refresh, source reconstruction or credential loading. The caller
supplies the ML repository root at c186e0b; county bytes remain outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

PINS = {
    "config/models/138-surveillance-situation-batch-v1.json": (
        "853c2ad3db1de297f73138cb688bb9a7372e30d0af55720fac2429b8955b4b99"
    ),
    "config/models/138-surveillance-situation-batch-v1-approval.json": (
        "8fa1f3292a0943c5a8512b7d59a93bb18bc87d47bd2483ff4d8ee71bfbb62b86"
    ),
    "config/models/138-surveillance-situation-class-dictionary-v1.json": (
        "c0fecc0766c7e485b670624793cd2b02a1c8bafd49c740bcc8db9c62e9d2494b"
    ),
    "outputs/138-surveillance-situation-batch-v1/county-assignments.json": (
        "02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b"
    ),
}

COUNTS = {
    "surveillance-situation-four-state": [801, 35, 112, 2196],
    "surveillance-situation-tick-pathogen": [1325, 1687, 97, 35],
}


def verify(root: Path) -> dict[str, str]:
    documents = {}
    for name, digest in PINS.items():
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Frozen ML handoff checksum mismatch: " + name)
        documents[name] = data.decode("utf-8")
    models = json.loads(documents[next(reversed(PINS))])["models"]
    if len(models) != 2 or {m["model_id"] for m in models} != set(COUNTS):
        raise ValueError("Exactly two approved model variants required")
    for model in models:
        identity = model["model_id"]
        seen = set()
        counts: Counter[int] = Counter()
        for row in model["rows"]:
            fips = row["county_fips"]
            if len(fips) != 5 or not fips.isascii() or not fips.isdigit() or fips in seen:
                raise ValueError("Invalid or duplicate FIPS")
            seen.add(fips)
            expected = [f"{identity}.v1.class-{i}" for i in range(4)]
            probabilities = row["probabilities"]
            if [p["class_id"] for p in probabilities] != expected:
                raise ValueError("Probability class order changed")
            values = [p["probability"] for p in probabilities]
            if (
                any(
                    type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                    for p in values
                )
                or abs(sum(values) - 1) > 1e-6
            ):
                raise ValueError("Invalid probability vector")
            index = expected.index(row["class_id"])
            counts[index] += 1
            unknown = 1 if identity.endswith("four-state") else 3
            if (index == unknown) != fips.startswith(("02", "15")):
                raise ValueError("Unknown class differs from approved AK/HI scope")
        if len(seen) != 3144 or [counts[i] for i in range(4)] != COUNTS[identity]:
            raise ValueError("Pinned county/class coverage changed")
    return documents


def query(connection: str, sql: str) -> Any:
    # County payloads never appear in command arguments or console output.
    with tempfile.TemporaryDirectory(prefix="atlas-ml138-") as directory:
        path = Path(directory) / "operation.sql"
        path.write_bytes(sql.encode("utf-8"))
        result = subprocess.run(
            ["snow", "sql", "-c", connection, "--format", "JSON", "-f", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("Snowflake operation failed; inspect redacted CLI diagnostics locally")
    return json.loads(result.stdout)


def literal(value: str) -> str:
    # CLI/file newline normalization must not alter approved artifact bytes,
    # including the upstream approval document's CRLF line endings.
    return "HEX_DECODE_STRING('" + value.encode("utf-8").hex() + "')"


def publish(
    connection: str,
    documents: dict[str, str],
    environment: str,
    attempt: str = "ml138-v1-02b62d7a4cb8970b",
    authorization: str | None = None,
) -> None:
    env = environment.upper()
    context = query(
        connection,
        "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,"
        "CURRENT_DATABASE() AS D,CURRENT_WAREHOUSE() AS W",
    )
    expected = (
        f"OH_LYME_{env}_TIER1_ML_PUBLISHER_SVC",
        f"OH_LYME_{env}_ML_PUBLISHER",
        f"ONE_HEALTH_LYME_GAP_ATLAS_{env}",
        f"OH_LYME_{env}_INGEST_XS_WH",
    )
    if len(context) != 1 or tuple(context[0][k] for k in ("U", "R", "D", "W")) != expected:
        raise ValueError("Publisher identity, role, database or warehouse differs")
    if not authorization:
        raise ValueError("A separate Data owner publication authorization is required")
    prefix = f"ONE_HEALTH_LYME_GAP_ATLAS_{env}.FEATURE_STORE."
    county = documents[next(reversed(PINS))]
    for number, start in enumerate(range(0, len(county), 200000)):
        query(
            connection,
            f"CALL {prefix}SP_STAGE_SURVEILLANCE_SITUATION_PART("
            f"{literal(authorization)},{literal(attempt)},{number},"
            f"{literal(county[start : start + 200000])})",
        )
    names = list(PINS)
    args = ",".join(literal(documents[names[i]]) for i in (0, 2, 1))
    result = query(
        connection,
        f"CALL {prefix}SP_PUBLISH_SURVEILLANCE_SITUATIONS("
        f"{literal(authorization)},{literal(attempt)},{args})",
    )
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ml_root", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--environment", choices=("dev", "prod"), default="dev")
    parser.add_argument("--connection")
    parser.add_argument("--staging-attempt", default="ml138-v1-02b62d7a4cb8970b")
    parser.add_argument("--authorization-id")
    args = parser.parse_args()
    documents = verify(args.ml_root)
    print(
        json.dumps(
            {"verified": True, "rows_per_fit": 3144, "county_sha256": list(PINS.values())[-1]}
        )
    )
    if args.publish:
        if not args.connection or not args.authorization_id:
            parser.error("--publish requires a named PAT --connection and Data --authorization-id")
        publish(
            args.connection,
            documents,
            args.environment,
            args.staging_attempt,
            args.authorization_id,
        )


if __name__ == "__main__":
    main()
