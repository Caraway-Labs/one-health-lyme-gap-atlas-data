"""Recovery fixtures exercise archive binding; they are not national source evidence."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from test_nlcd_parallel import basis, seed  # noqa: F401

from lyme_gap_atlas_data import nlcd_parallel as p
from lyme_gap_atlas_data import nlcd_parallel_recovery as recovery


@pytest.fixture
def recovered(
    tmp_path_factory: pytest.TempPathFactory,
    basis: p.Json,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    artifacts = tmp_path_factory.mktemp("r") / "a"
    counties = sorted(
        (Path(p.__file__).parent / "data/canonical-county-fips-2022.txt").read_text().splitlines()
    )
    names = ["national", "proof"]
    national = seed(artifacts / names[0], basis, counties, 223)
    proof = seed(
        artifacts / names[1],
        basis,
        ["02013", "06075", "09110", "15001", "46127", "48081", "51013"],
        7,
    )
    monkeypatch.setattr(p, "REFERENCE", national)
    monkeypatch.setattr(p, "PROOF", proof)
    monkeypatch.setattr(
        p,
        "SEED_INVENTORIES",
        tuple(p.fingerprint(p.audit_run(artifacts / n, basis)) for n in names),
    )
    previous = p.make_plan(artifacts, names, 4)
    root = artifacts / "recovered"
    contents = root / "contents"
    p.save_plan(contents / "recovery/plans/national-4", previous)
    import shutil

    shutil.copytree(artifacts / names[0], contents / "recovery/artifacts" / names[0])
    shutil.copytree(artifacts / names[1], contents / "recovery/artifacts" / names[1])
    for i, selected in enumerate(previous["workers"]):
        seed(contents / f"recovery/state/national-4/worker-{i:02d}/results", basis, selected, 1)
    inventory = [
        {
            "path": f.relative_to(contents).as_posix(),
            "bytes": f.stat().st_size,
            "sha256": p.file_hash(f),
        }
        for f in sorted(contents.rglob("*"))
        if f.is_file()
    ]
    with tarfile.open(root / "archive.tar.gz", "w:gz") as tar:
        for item in inventory:
            tar.add(contents / item["path"], arcname=item["path"], recursive=False)
        raw = p.canonical({"files": inventory})
        info = tarfile.TarInfo("recovery-file-inventory.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    monkeypatch.setattr(recovery, "ARCHIVE_SHA256", p.file_hash(root / "archive.tar.gz"))
    monkeypatch.setattr(recovery, "PREVIOUS_PLAN_ID", previous["plan_id"])
    monkeypatch.setattr(recovery, "RECOVERED_COUNTIES", 4)
    return {
        "artifacts": artifacts,
        "basis": basis,
        "root": root,
        "previous": previous,
        "names": names,
    }


def test_recovery_new_assignment_preserves_old_identity(
    recovered: dict[str, Any], tmp_path: Path
) -> None:
    data = recovered
    before = {f: f.read_bytes() for f in data["root"].rglob("*") if f.is_file()}
    plan = p.make_plan(data["artifacts"], data["names"], 4, recovery_root="recovered")
    assert len(plan["accepted"]) == 202 and len(plan["remaining"]) == 2907
    assert len({f for group in plan["workers"] for f in group}) == 2907
    old = {r["county_fips"] for r in plan["accepted"]}
    assert not old & set(plan["remaining"])
    p.save_plan(tmp_path / "plan", plan)
    p.verify_accepted(p.load_plan(tmp_path / "plan"), data["artifacts"])
    assert before == {f: f.read_bytes() for f in before}
    assert len({r["run_id"] for r in plan["accepted"]}) == 6
    assert not list(data["root"].rglob("*partitions-complete.json"))


@pytest.mark.parametrize(
    "kind", ["archive", "consistent_payload", "lineage", "missing", "prior_assignment"]
)
def test_recovery_rejects_modified_accepted_evidence(recovered: dict[str, Any], kind: str) -> None:
    root = recovered["root"]
    if kind == "archive":
        path = root / "archive.tar.gz"
        path.write_bytes(path.read_bytes() + b"x")
    elif kind == "prior_assignment":
        path = root / "contents/recovery/plans/national-4/assignment.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif kind == "lineage":
        path = next((root / "contents/recovery/state").rglob("*.lineage.json"))
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path = next((root / "contents/recovery/state").rglob("*.part-*.json"))
        if kind == "missing":
            path.unlink()
        else:
            part = json.loads(path.read_bytes())
            part["records"][0]["value"] = 0.25
            part["sha256"] = p.fingerprint(part["records"])
            part["byte_count"] = len(p.canonical(part["records"]))
            path.write_bytes(p.canonical(part))
    with pytest.raises((ValueError, FileNotFoundError)):
        recovery.recovered_refs(recovered["artifacts"], "recovered", recovered["basis"])


def test_recovery_resume_rejects_changed_binding(recovered: dict[str, Any], tmp_path: Path) -> None:
    plan = p.make_plan(recovered["artifacts"], recovered["names"], 4, recovery_root="recovered")
    plan["recovery_archive_sha256"] = "0" * 64
    plan["plan_id"] = p.fingerprint({k: v for k, v in plan.items() if k != "plan_id"})
    p.save_plan(tmp_path / "plan", plan)
    with pytest.raises(ValueError, match="archive pin"):
        p.load_plan(tmp_path / "plan")
