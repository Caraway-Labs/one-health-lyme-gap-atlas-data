"""Read-only admission of the one owner-verified interrupted national archive.

This is a frozen prefix inventory, never a completion receipt or container adoption.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

from . import nlcd_parallel as p

ARCHIVE_SHA256 = "ef1defeaa9ba1f211d5f99b85abcec73a0edeec9bd187b801ced37e8b226409f"
PREVIOUS_PLAN_ID = "6e10f38c4cad1e92002132c5512b488b375e036f2a339c3b9ae94f1007f95f90"
RECOVERED_COUNTIES = 905


def recovered_refs(artifacts: Path, relative: str, basis: p.Json) -> list[p.Json]:
    """Revalidate both the owner-pinned archive and every extracted original byte."""
    root = p.contained(artifacts, relative)
    archive = root / "archive.tar.gz"
    p.require(p.file_hash(archive) == ARCHIVE_SHA256, "Recovery archive differs from owner pin")
    extracted = root / "contents"
    with tarfile.open(archive, "r:gz") as handle:
        names = [member.name for member in handle.getmembers()]
        stream = handle.extractfile("recovery-file-inventory.json")
        p.require(stream is not None, "Recovery file inventory missing")
        assert stream is not None
        inventory = json.load(stream)["files"]
        p.require(
            len(names) == len(set(names)) == len(inventory) + 1
            and set(names)
            == {item["path"] for item in inventory} | {"recovery-file-inventory.json"},
            "Recovery archive members differ",
        )
        for item in inventory:
            p.require(handle.getmember(item["path"]).isfile(), "Regular recovery member required")
            path = p.contained(extracted, item["path"])
            p.require(
                path.stat().st_size == item["bytes"] and p.file_hash(path) == item["sha256"],
                "Recovered original file changed",
            )
    previous = p.load_plan(extracted / "recovery/plans/national-4")
    p.require(
        previous["plan_id"] == PREVIOUS_PLAN_ID and previous["basis"] == basis,
        "Recovery assignment/scientific identity differs",
    )
    p.verify_accepted(previous, extracted / "recovery/artifacts")
    refs: list[p.Json] = []
    for index, selected in enumerate(previous["workers"]):
        origin = f"{relative}/contents/recovery/state/national-4/worker-{index:02d}/results"
        results = p.contained(artifacts, origin)
        saved = p.audit_run(results, basis, selected)
        # Audit original county bytes once, then validate every frozen terminal
        # prefix against those same references. Do not reread the whole growing
        # county prefix for each of the historical batch receipts.
        for result_path in sorted(results.parent.glob("attempt-*.result.json")):
            result = p.read_json(result_path)
            p.require(result["kind"] == "SUCCESS", "Unexpected recovered terminal failure")
            inventory_path = results.parent / f"attempt-{result['attempt']:05d}.inventory.json"
            p.require(
                p.file_hash(inventory_path) == result["inventory_sha256"],
                "Recovered terminal inventory changed",
            )
            frozen = p.read_json(inventory_path)
            count = frozen["partition_count"]
            p.require(type(count) is int and 0 <= count <= len(saved), "Invalid prefix count")
            p.require(
                frozen == p.output_inventory(previous, results, index, saved[:count]),
                "Recovered terminal prefix differs",
            )
        p.require(
            not (results.parent / "completed.inventory.json").exists(),
            "Interrupted recovery must not claim worker completion",
        )
        refs.extend({**ref, "origin": origin} for ref in saved)
    counties = [ref["county_fips"] for ref in refs]
    p.require(
        len(counties) == len(set(counties)) == RECOVERED_COUNTIES
        and set(counties) <= set(previous["remaining"]),
        "Recovered prefix has overlapping/foreign/missing counties",
    )
    return sorted(refs, key=lambda ref: ref["county_fips"])
