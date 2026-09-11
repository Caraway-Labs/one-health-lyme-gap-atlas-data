"""Validate and publish one operator-captured CDC tick evidence envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from lyme_gap_atlas_data.tick_surveillance import (
    IMAGE_DIGEST_PATTERN,
    OPERATOR_EVIDENCE_ROUTE,
    PDF_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    FetchResult,
    _parse_workbook,
    _validate_landing_page_pdf,
    load_tick_profile,
)

REGISTRY_IMAGE = "registry.digitalocean.com/oh-lyme-data/pipeline"
WORKFLOW = "capture-dev-cdc-tick-surveillance-operator.yml"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _run(arguments: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else ""


def build_manifest(
    landing_pdf: Path,
    workbook: Path,
    base_image_digest: str,
    retrieval_id: str,
) -> tuple[dict[str, object], bytes, bytes]:
    profile = load_tick_profile()
    landing_payload = landing_pdf.read_bytes()
    workbook_payload = workbook.read_bytes()
    if not landing_payload or len(landing_payload) > 2_000_000:
        raise ValueError("CDC landing-page print is outside the two-megabyte bound")
    if not workbook_payload or len(workbook_payload) > int(profile["maximum_workbook_bytes"]):
        raise ValueError("CDC tick county workbook is outside the configured byte bound")
    _validate_landing_page_pdf(FetchResult(landing_payload, PDF_MEDIA_TYPE, None, None))
    evidence = _parse_workbook(workbook_payload, profile, 25)
    if evidence.row_count != 3111:
        raise ValueError("CDC tick county workbook row count changed; steward review is required")
    retrieved_at = max(_utc_mtime(landing_pdf), _utc_mtime(workbook))
    manifest = {
        "manifest_version": 2,
        "acquisition_route": OPERATOR_EVIDENCE_ROUTE,
        "retrieved_at": retrieved_at,
        "operator": {
            "retrieval_id": retrieval_id,
            "acquisition_method": "BROWSER_DOWNLOAD_AND_PRINT",
            "attestation": "FILES_SAVED_FROM_PINNED_FIRST_PARTY_CDC_PAGE",
        },
        "base_image_digest": base_image_digest,
        "resources": [
            {
                "purpose": "SOURCE_LANDING_PAGE_PRINT",
                "filename": "landing.pdf",
                "requested_url": str(profile["landing_page_url"]),
                "final_url": str(profile["landing_page_url"]),
                "status_code": None,
                "http_status_observed": False,
                "media_type": PDF_MEDIA_TYPE,
                "byte_count": len(landing_payload),
                "sha256": _sha256(landing_payload),
                "etag": None,
                "last_modified": None,
                "transport": "BROWSER_PRINT_TO_PDF",
                "source_file_modified_at": _utc_mtime(landing_pdf),
            },
            {
                "purpose": "SOURCE_WORKBOOK_EVIDENCE",
                "filename": "workbook.xlsx",
                "requested_url": str(profile["endpoint_template"]),
                "final_url": str(profile["endpoint_template"]),
                "status_code": None,
                "http_status_observed": False,
                "media_type": XLSX_MEDIA_TYPE,
                "byte_count": len(workbook_payload),
                "sha256": _sha256(workbook_payload),
                "etag": None,
                "last_modified": None,
                "transport": "BROWSER_DOWNLOAD",
                "source_file_modified_at": _utc_mtime(workbook),
            },
        ],
    }
    return manifest, landing_payload, workbook_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--landing-pdf", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--base-image-digest", required=True)
    parser.add_argument("--publish-and-dispatch", action="store_true")
    args = parser.parse_args()
    if IMAGE_DIGEST_PATTERN.fullmatch(args.base_image_digest) is None:
        raise ValueError("base image digest must be an immutable sha256 digest")
    retrieval_id = str(uuid.uuid4())
    manifest, landing_payload, workbook_payload = build_manifest(
        args.landing_pdf,
        args.workbook,
        args.base_image_digest,
        retrieval_id,
    )
    resources = manifest["resources"]
    if not isinstance(resources, list):
        raise AssertionError("manifest resources must be a list")
    landing_resource = resources[0]
    workbook_resource = resources[1]
    if not isinstance(landing_resource, dict) or not isinstance(workbook_resource, dict):
        raise AssertionError("manifest resources must be objects")
    summary: dict[str, object] = {
        "retrieval_id": retrieval_id,
        "landing_sha256": landing_resource["sha256"],
        "workbook_sha256": workbook_resource["sha256"],
        "publish_requested": args.publish_and_dispatch,
    }
    if not args.publish_and_dispatch:
        print(json.dumps(summary, sort_keys=True))
        return

    tag = f"tick-operator-evidence-{retrieval_id}"
    with tempfile.TemporaryDirectory(prefix="atlas-tick-evidence-") as directory:
        bundle = Path(directory)
        (bundle / "landing.pdf").write_bytes(landing_payload)
        (bundle / "workbook.xlsx").write_bytes(workbook_payload)
        (bundle / "acquisition-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        (bundle / "Dockerfile").write_text(
            "ARG BASE_IMAGE\n"
            "FROM ${BASE_IMAGE}\n"
            "COPY --chmod=0444 landing.pdf workbook.xlsx acquisition-manifest.json "
            "/run/atlas-tick-evidence/\n",
            encoding="utf-8",
        )
        _run(["doctl", "registry", "login", "--expiry-seconds", "1200"])
        _run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--build-arg",
                f"BASE_IMAGE={REGISTRY_IMAGE}@{args.base_image_digest}",
                "--tag",
                f"{REGISTRY_IMAGE}:{tag}",
                str(bundle),
            ]
        )
        _run(["docker", "push", f"{REGISTRY_IMAGE}:{tag}"])

    envelope_digest = ""
    for _attempt in range(12):
        manifests = json.loads(
            _run(
                [
                    "doctl",
                    "registry",
                    "repository",
                    "list-manifests",
                    "pipeline",
                    "--output",
                    "json",
                ],
                capture=True,
            )
        )
        for item in manifests:
            if tag in item.get("tags", []):
                envelope_digest = str(item["digest"])
                break
        if envelope_digest:
            break
        time.sleep(5)
    if not envelope_digest.startswith("sha256:"):
        raise RuntimeError("published evidence envelope digest was not found")

    try:
        _run(
            [
                "gh",
                "workflow",
                "run",
                WORKFLOW,
                "--ref",
                "main",
                "-f",
                f"image_digest={args.base_image_digest}",
                "-f",
                f"envelope_digest={envelope_digest}",
                "-f",
                f"envelope_tag={tag}",
                "-f",
                f"retrieval_id={retrieval_id}",
            ]
        )
    except subprocess.CalledProcessError:
        _run(["doctl", "registry", "repository", "delete-tag", "pipeline", tag, "--force"])
        raise
    summary["envelope_digest"] = envelope_digest
    summary["envelope_tag"] = tag
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
