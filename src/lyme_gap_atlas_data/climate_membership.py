"""Read-only frozen January membership via the existing protected runtime."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from .climate_publication import NOAA_ARTIFACT_ID, NOAA_SHA, RESOURCE_KEY, RUN_ID
from .climate_source_review import INPUTS
from .surveillance_safe import has_sensitive_path

ROW_COUNT = 389856
ARTIFACT_NAME = "source-pilot-inspection-artifact.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")
DONOR_CONTRACT = "atlas-january-reviewed-donor-v1"
MAX_DONOR_BYTES = 64 * 1024


class MembershipBlocked(ValueError):
    """Closed diagnostics, never SQL/SDK messages or credential values."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise MembershipBlocked(code)


def validate_donor(donor: Any, donor_id: Any) -> None:
    """Closed annual contract before exporting any existing warehouse content."""
    from .semantic_release import REQUIRED_SCORE_DEFAULT_KEYS, REQUIRED_SOURCE_KEYS

    fields = {
        "manifest_schema",
        "release_id",
        "schema_version",
        "methodology_version",
        "generated_at",
        "scope",
        "score_defaults",
        "limitations",
        "sources",
    }
    require(isinstance(donor, dict) and set(donor) == fields, "MEMBERSHIP_DONOR_SHAPE")
    require(
        isinstance(donor_id, str)
        and re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", donor_id) is not None
        and donor["release_id"] == donor_id
        and donor["manifest_schema"] == "atlas-governed-semantic-release/v1",
        "MEMBERSHIP_DONOR_IDENTITY",
    )
    unsafe = re.compile(
        r"(?:[a-z][a-z0-9+.-]*://|(?:token|password|credential|secret)\s*[=:]|"
        r"PRIVATE KEY|[A-Za-z]:\\|(?:^|\s)/(?:home|tmp|private|mnt)/)",
        re.I,
    )

    def text(value: Any) -> None:
        require(
            isinstance(value, str)
            and 0 < len(value) <= 4096
            and not unsafe.search(value)
            and not has_sensitive_path(value)
            and not any(ord(c) < 32 for c in value),
            "MEMBERSHIP_DONOR_TEXT",
        )

    for key in fields - {"sources", "score_defaults"}:
        text(donor[key])
    require(
        all(
            re.fullmatch(r"(?:semantic-)?[0-9]+\.[0-9]+\.[0-9]+", donor[key]) is not None
            for key in ("schema_version", "methodology_version")
        ),
        "MEMBERSHIP_DONOR_VERSION",
    )
    scores = donor["score_defaults"]
    require(
        isinstance(scores, dict) and set(scores) == REQUIRED_SCORE_DEFAULT_KEYS,
        "MEMBERSHIP_DONOR_SCORES",
    )
    mixes = {
        "ecological_mix": {"tick_status", "b_burgdorferi_in_ticks"},
        "community_mix": {"svi", "uninsured_percentile", "rurality"},
    }
    for key, value in scores.items():
        if key in mixes:
            require(isinstance(value, dict) and set(value) == mixes[key], "MEMBERSHIP_DONOR_SCORES")
            numbers = value.values()
        else:
            numbers = [value]
        require(
            all(type(n) in (int, float) and math.isfinite(n) for n in numbers),
            "MEMBERSHIP_DONOR_SCORES",
        )
    sources = donor["sources"]
    require(
        isinstance(sources, list)
        and len(sources) == 5
        and all(isinstance(s, dict) for s in sources),
        "MEMBERSHIP_ANNUAL_SLOTS",
    )
    require(
        {s.get("source_key") for s in sources} == REQUIRED_SOURCE_KEYS, "MEMBERSHIP_ANNUAL_SLOTS"
    )
    source_fields = {
        "source_key",
        "resource_key",
        "source_id",
        "dataset_id",
        "label",
        "vintage",
        "source_url",
        "note",
        "data_source_version_id",
        "ingestion_run_id",
        "artifact_id",
        "artifact_sha256",
        "definition_version",
    }
    for source in sources:
        require(
            set(source) in (source_fields, source_fields | {"field_map"}),
            "MEMBERSHIP_DONOR_SOURCE_SHAPE",
        )
        for key in source_fields - {"source_url", "definition_version"}:
            text(source[key])
        require(
            type(source["definition_version"]) is int
            and source["definition_version"] > 0
            and HEX.fullmatch(source["artifact_sha256"]) is not None,
            "MEMBERSHIP_DONOR_SOURCE_SHAPE",
        )
        require(
            isinstance(source["source_url"], str) and len(source["source_url"]) <= 2048,
            "MEMBERSHIP_DONOR_URL",
        )
        url = urlsplit(source["source_url"])
        require(
            url.scheme == "https"
            and url.netloc
            in {
                "data.cdc.gov",
                "www.cdc.gov",
                "www.atsdr.cdc.gov",
                "www.ers.usda.gov",
            }
            and not url.query
            and not url.fragment
            and not url.username
            and not url.password
            and not any(ord(c) < 33 for c in source["source_url"]),
            "MEMBERSHIP_DONOR_URL",
        )
        field_map = source.get("field_map", {})
        require(isinstance(field_map, dict) and len(field_map) <= 20, "MEMBERSHIP_DONOR_FIELD_MAP")
        for key, names in field_map.items():
            text(key)
            require(
                re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) is not None
                and not re.search(r"secret|token|password|credential|private", key, re.I),
                "MEMBERSHIP_DONOR_FIELD_MAP",
            )
            require(isinstance(names, (str, list)), "MEMBERSHIP_DONOR_FIELD_MAP")
            names = [names] if isinstance(names, str) else names
            require(0 < len(names) <= 20, "MEMBERSHIP_DONOR_FIELD_MAP")
            for name in names:
                text(name)


def export_donor_handoff(cursor: Any, output: Path, code_sha: str) -> dict[str, Any]:
    """Called only within an independently bounded protected DEV operator read.

    No connection, grant, migration or publication is performed here. The caller
    must enforce timeout/no-retry/cost limits and retain the operator-run receipt.
    """
    require(re.fullmatch(r"[0-9a-f]{40}", code_sha) is not None, "MEMBERSHIP_CODE_SHA")
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()")
    context = cursor.fetchone()
    require(
        isinstance(context, tuple)
        and len(context) == 4
        and context[:3]
        == (
            "OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
            "OH_LYME_DEV_MIGRATION_DEPLOYER",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        )
        and isinstance(context[3], str)
        and bool(context[3]),
        "MEMBERSHIP_DONOR_OPERATOR_IDENTITY",
    )
    cursor.execute(
        "SELECT p.current_release_id,r.status,r.bundle_sha256,r.source_manifest "
        "FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p "
        "JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id "
        "WHERE p.pointer_key='ATLAS' LIMIT 2"
    )
    rows = cursor.fetchall()
    require(len(rows) == 1 and rows[0][1] == "PUBLISHED", "MEMBERSHIP_CURRENT_RELEASE")
    release_id, _, bundle_sha, manifest = rows[0]
    manifest = json.loads(manifest) if isinstance(manifest, str) else manifest
    validate_donor(manifest, release_id)
    require(
        isinstance(bundle_sha, str) and HEX.fullmatch(bundle_sha) is not None,
        "MEMBERSHIP_DONOR_BUNDLE",
    )
    cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V LIMIT 2")
    require(cursor.fetchall() == [(release_id, bundle_sha)], "MEMBERSHIP_POINTER_CHANGED")
    document = {
        "contract_version": DONOR_CONTRACT,
        "producer_code_sha": code_sha,
        "produced_at": datetime.now(UTC).isoformat(),
        "operator_role": context[1],
        "release_id": release_id,
        "bundle_sha256": bundle_sha,
        "annual_manifest": manifest,
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    require(len(payload) <= MAX_DONOR_BYTES, "MEMBERSHIP_DONOR_SIZE")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_count": len(payload),
        "writes_performed": False,
    }


def read_donor_handoff(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Expected digest comes from independent review of the operator artifact."""
    require(HEX.fullmatch(expected_sha256) is not None, "MEMBERSHIP_DONOR_DIGEST_REQUIRED")
    require(path.is_file() and path.stat().st_size <= MAX_DONOR_BYTES, "MEMBERSHIP_DONOR_SIZE")
    payload = path.read_bytes()
    require(len(payload) <= MAX_DONOR_BYTES, "MEMBERSHIP_DONOR_SIZE")
    require(hashlib.sha256(payload).hexdigest() == expected_sha256, "MEMBERSHIP_DONOR_DIGEST")
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeError):
        raise MembershipBlocked("MEMBERSHIP_DONOR_SHAPE") from None
    validate_donor_handoff(document)
    return cast(dict[str, Any], document)


def validate_donor_handoff(document: Any) -> None:
    require(
        isinstance(document, dict)
        and set(document)
        == {
            "contract_version",
            "producer_code_sha",
            "produced_at",
            "operator_role",
            "release_id",
            "bundle_sha256",
            "annual_manifest",
        },
        "MEMBERSHIP_DONOR_HANDOFF_SHAPE",
    )
    require(
        document["contract_version"] == DONOR_CONTRACT
        and document["operator_role"] == "OH_LYME_DEV_MIGRATION_DEPLOYER"
        and re.fullmatch(r"[0-9a-f]{40}", str(document["producer_code_sha"])) is not None
        and HEX.fullmatch(str(document["bundle_sha256"])) is not None,
        "MEMBERSHIP_DONOR_HANDOFF_IDENTITY",
    )
    try:
        produced = datetime.fromisoformat(document["produced_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise MembershipBlocked("MEMBERSHIP_DONOR_HANDOFF_TIME") from None
    require(
        produced.tzinfo is not None and produced <= datetime.now(UTC),
        "MEMBERSHIP_DONOR_HANDOFF_TIME",
    )
    validate_donor(document["annual_manifest"], document["release_id"])


def freeze_membership(
    cursor: Any, output: Path, code_sha: str, donor_handoff: dict[str, Any] | None = None
) -> dict[str, Any]:
    """At most the fixed January row count; SELECT only and atomic local artifact.

    No source approval, warehouse object, grant, pointer or capture is changed.
    The full IDs remain in the workflow artifact; stdout contains counts/digests.
    """
    if donor_handoff is None:
        raise MembershipBlocked("MEMBERSHIP_DONOR_HANDOFF_REQUIRED")
    validate_donor_handoff(donor_handoff)
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()")
    require(
        cursor.fetchone()
        == (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        ),
        "MEMBERSHIP_IDENTITY",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", code_sha) is not None, "MEMBERSHIP_CODE_SHA")
    cursor.execute(
        "SELECT resource_key,status FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    require(cursor.fetchall() == [(RESOURCE_KEY, "COMPLETED")], "MEMBERSHIP_RUN")
    for source in INPUTS:
        cursor.execute(
            "SELECT sha256,byte_count FROM GOVERNANCE.RAW_ARTIFACTS "
            "WHERE artifact_id=%s AND ingestion_run_id=%s",
            (source["artifact_id"], RUN_ID),
        )
        require(
            cursor.fetchall() == [(source["sha256"], source["byte_count"])], "MEMBERSHIP_ARTIFACT"
        )
    cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V LIMIT 2")
    pointers = cursor.fetchall()
    donor_id, donor = donor_handoff["release_id"], donor_handoff["annual_manifest"]
    require(pointers == [(donor_id, donor_handoff["bundle_sha256"])], "MEMBERSHIP_CURRENT_RELEASE")
    cursor.execute(
        "SELECT capture_record_id,record_revision,record_id,source_row_hash,normalized_sha256 "
        "FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS WHERE ingestion_run_id=%s "
        "AND resource_key=%s AND source_definition_version=2 AND artifact_id=%s "
        "AND artifact_sha256=%s ORDER BY capture_record_id " + f"LIMIT {ROW_COUNT + 1}",
        (RUN_ID, RESOURCE_KEY, NOAA_ARTIFACT_ID, NOAA_SHA),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    count = 0
    previous = None
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            header = {
                "contract_version": "atlas-january-frozen-membership-v1",
                "code_sha": code_sha,
                "status": "READ_ONLY_CANDIDATE_NOT_PUBLICATION",
                "ingestion_run_id": RUN_ID,
                "donor_release_id": donor_id,
                "annual_manifest": donor,
            }
            handle.write(json.dumps(header, separators=(",", ":"))[:-1] + ',"capture_ids":[')
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    require(
                        len(row) == 5 and all(isinstance(value, str) and value for value in row),
                        "MEMBERSHIP_ROW",
                    )
                    require(
                        count < ROW_COUNT
                        and HEX.fullmatch(row[0]) is not None
                        and all(HEX.fullmatch(value) is not None for value in row[3:]),
                        "MEMBERSHIP_HASH_SCOPE",
                    )
                    require(previous is None or row[0] > previous, "MEMBERSHIP_ORDER")
                    handle.write(("," if count else "") + json.dumps(row[0]))
                    digest.update((json.dumps(list(row), separators=(",", ":")) + "\n").encode())
                    previous = row[0]
                    count += 1
            require(count == ROW_COUNT, "MEMBERSHIP_COUNT")
            handle.write(
                '],"row_count":'
                + str(count)
                + ',"capture_membership_sha256":'
                + json.dumps(digest.hexdigest())
                + "}"
            )
        cursor.execute(
            "SELECT COUNT(*) FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS "
            "WHERE ingestion_run_id=%s",
            (RUN_ID,),
        )
        require(cursor.fetchone() == (ROW_COUNT,), "MEMBERSHIP_UNSELECTED_REVISIONS")
        cursor.execute(
            "SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V LIMIT 2"
        )
        require(
            cursor.fetchall() == [(donor_id, donor_handoff["bundle_sha256"])],
            "MEMBERSHIP_POINTER_CHANGED",
        )
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    artifact_digest = hashlib.sha256()
    with output.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            artifact_digest.update(chunk)
    return {
        "row_count": count,
        "capture_membership_sha256": digest.hexdigest(),
        "artifact_sha256": artifact_digest.hexdigest(),
        "artifact_name": ARTIFACT_NAME,
        "annual_source_slots": 5,
        "writes_performed": False,
        "publication": False,
    }
