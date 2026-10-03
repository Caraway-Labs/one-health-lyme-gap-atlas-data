"""Read-only frozen January membership via the existing protected runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .climate_publication import NOAA_ARTIFACT_ID, NOAA_SHA, RESOURCE_KEY, RUN_ID
from .climate_source_review import INPUTS

ROW_COUNT = 389856
ARTIFACT_NAME = "source-pilot-inspection-artifact.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")


class MembershipBlocked(ValueError):
    """Closed diagnostics, never SQL/SDK messages or credential values."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise MembershipBlocked(code)


def freeze_membership(cursor: Any, output: Path, code_sha: str) -> dict[str, Any]:
    """At most the fixed January row count; SELECT only and atomic local artifact.

    No source approval, warehouse object, grant, pointer or capture is changed.
    The full IDs remain in the workflow artifact; stdout contains counts/digests.
    """
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
    cursor.execute(
        "SELECT p.current_release_id,r.status,r.source_manifest "
        "FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p "
        "JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id "
        "WHERE p.pointer_key='ATLAS'"
    )
    pointers = cursor.fetchall()
    require(len(pointers) == 1 and pointers[0][1] == "PUBLISHED", "MEMBERSHIP_CURRENT_RELEASE")
    donor_id, _, donor = pointers[0]
    donor = json.loads(donor) if isinstance(donor, str) else donor
    require(
        isinstance(donor, dict) and len(donor.get("sources", [])) == 5, "MEMBERSHIP_ANNUAL_SLOTS"
    )
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
            "SELECT current_release_id FROM PRESENTATION.SEMANTIC_RELEASE_POINTER "
            "WHERE pointer_key='ATLAS'"
        )
        require(cursor.fetchall() == [(donor_id,)], "MEMBERSHIP_POINTER_CHANGED")
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
