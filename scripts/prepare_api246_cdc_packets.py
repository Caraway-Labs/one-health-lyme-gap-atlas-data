"""Offline reconciliation only. Produces unsigned, unregistered proposed packets."""

import copy
import json
import subprocess
import sys
from pathlib import Path

from lyme_gap_atlas_data.cdc_consumer_admission import (
    RELEASE_BUNDLES,
    RELEASE_ID,
    SLICES,
    TARGET_RELEASE_ID,
)
from lyme_gap_atlas_data.cdc_consumer_runtime import _inputs, _metadata, _resources
from lyme_gap_atlas_data.semantic_source_mappings import load_mapping_registry, map_record

if len(sys.argv) != 2:
    raise SystemExit("usage: prepare_api246_cdc_packets.py <gitignored-private-evidence-directory>")
out = Path(sys.argv[1]).resolve()
if not out.is_dir():
    raise SystemExit("private evidence directory required")
if subprocess.run(
    ["git", "check-ignore", "--quiet", str(out / "proposed-packet-private.json")], check=False
).returncode:
    raise SystemExit("output must be gitignored")
root = _resources()
registry = load_mapping_registry(
    Path("docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json")
)
stats = {}
for measure in SLICES:
    sample = {
        k.lower(): v
        for k, v in json.loads((out / f"donor-{measure}-private.json").read_text()).items()
    }
    template = sample["cdc_runtime_authority"]
    template = json.loads(template) if isinstance(template, str) else template
    rows = [
        {k.lower(): v for k, v in r.items()}
        for f in out.glob(f"reconcile-{measure}-*-private.json")
        for r in json.loads(f.read_text())
    ]
    ignored = {"observation_id", "release_id", "release_bundle_sha256"}
    scopes = {}
    for release in (RELEASE_ID, TARGET_RELEASE_ID):
        selected = [r for r in rows if r["release_id"] == release]
        scopes[release] = {r["county_fips"]: r for r in selected}
        if len(selected) != 3144 or len(scopes[release]) != 3144:
            raise SystemExit("complete unique county reconciliation required")
    if scopes[RELEASE_ID].keys() != scopes[TARGET_RELEASE_ID].keys():
        raise SystemExit("county membership mismatch")
    for county, row in scopes[RELEASE_ID].items():
        if {k: v for k, v in row.items() if k not in ignored} != {
            k: v for k, v in scopes[TARGET_RELEASE_ID][county].items() if k not in ignored
        }:
            raise SystemExit("lineage reconciliation mismatch")
    old = {
        r["county_fips"]: r
        for r in rows
        if r["release_id"] == RELEASE_ID and r["record_match_kind"] == "RESTRICTED_CDC_CONFORMED"
    }
    new = {
        r["county_fips"]: r
        for r in rows
        if r["release_id"] == TARGET_RELEASE_ID
        and r["record_match_kind"] == "RESTRICTED_CDC_CONFORMED"
    }
    assert old.keys() == new.keys() and len(old) == 3109
    prior = _metadata(root, measure, RELEASE_ID)
    current = _metadata(root, measure, TARGET_RELEASE_ID)
    assert (
        current["meaning_signature"] == prior["meaning_signature"]
        and current["definition"] == prior["definition"]
    )
    packet = {
        "release_id": TARGET_RELEASE_ID,
        "bundle_sha256": RELEASE_BUNDLES[TARGET_RELEASE_ID],
        "reviewed_at": "2026-10-17",
        "scope": SLICES[measure],
        "metadata_revision_id": current["revision_id"],
        "decision_reference": (
            "API #246 owner A-C approval in Codex, 2026-10-17; registration pending"
        ),
        "restricted_copy_reuse": {
            "donor_release_id": RELEASE_ID,
            "donor_bundle_sha256": RELEASE_BUNDLES[RELEASE_ID],
            "attestation_ids": [x["attestation_id"] for x in template["attestations"]],
        },
        "observation_bindings": {},
    }
    verified = 0
    for county, row in sorted(old.items()):
        facts = dict(template)
        for field in ["value", "value_state", "publisher_value", "coverage_state", "retrieved_at"]:
            facts[field] = row[field]
        facts["record_county"] = county
        facts["release_status"] = "RETIRED"  # actual donor lifecycle from donor read
        row = copy.deepcopy(row)
        row["cdc_runtime_authority"] = facts
        record, authority = _inputs(row, prior, expected_status="RETIRED")
        mapped = map_record(record, prior, authority, registry)
        expected = authority["releases"][RELEASE_ID]["semantic_revision_ids"]
        assert mapped["observation"]["revision_id"] in expected
        # Recompute target scientific revision without any release/exposure claim.
        record.pop("release")
        authority["releases"] = {}
        target = map_record(record, current, authority, registry)
        assert target["lineage"]["visibility"] == "INTERNAL"
        target_row = new[county]
        assert target_row["conformed_record_id"] == row["conformed_record_id"]
        packet["observation_bindings"][target_row["observation_id"]] = {
            "record_id": target_row["conformed_record_id"],
            "semantic_revision_id": target["observation"]["revision_id"],
            "donor_observation_id": row["observation_id"],
        }
        verified += 1
        if verified % 500 == 0:
            print(measure, verified, flush=True)
    (out / f"proposed-{measure}-packet-private.json").write_text(
        json.dumps(packet, separators=(",", ":")), encoding="utf-8"
    )
    stats[measure] = {
        "verified_donor_semantic_revisions": verified,
        "prepared_target_bindings": len(packet["observation_bindings"]),
        "meaning_signature_unchanged": True,
        "registered": False,
    }
    print(json.dumps(stats[measure]), flush=True)
(out / "semantic-reconciliation-summary.json").write_text(
    json.dumps(stats, indent=2), encoding="utf-8"
)
