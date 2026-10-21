"""Offline fixtures prove orchestration behavior, not national scientific results."""

from __future__ import annotations

import argparse
import copy
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lyme_gap_atlas_data import nlcd_parallel as p
from lyme_gap_atlas_data import nlcd_parallel_runtime as rt


@pytest.fixture(autouse=True)
def offline_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "operator_identity", lambda: (1001, 1001))


@pytest.fixture
def basis() -> p.Json:
    return {
        "input_manifest_sha256": "a" * 64,
        "source": {"packages": {}},
        "tiger_sha256": "b" * 64,
        "software": {"python": "fixture"},
        "calculation_code_sha256": "c" * 64,
        "weight_code_sha256": "d" * 64,
        "geometry_code_sha256": "e" * 64,
        "transform": "atlas-annual-nlcd-mrlc-local-county/1",
        "code_revision": p.REVISION,
        "grid": {"sha256": "f" * 64},
        "scope": "LOCAL_CALCULATION_ONLY_NOT_GOVERNED_SOURCE_ADMISSION",
    }


def rows(fips: str, lineage: str, basis: p.Json) -> list[p.Json]:
    excluded = fips.startswith(("02", "15"))
    return [
        {
            "county_fips": fips,
            "lineage_id": lineage,
            "measure": measure,
            "mapping_year": 2025,
            "collection_version": "C1V2",
            "unit": "fraction",
            "denominator": "valid_source_supported_area_m2",
            "transformation_version": basis["transform"],
            "geometry_version": "atlas-county-analysis-geometry/1",
            "weight_version": "atlas-grid-county-area-weight/1",
            "geometry_digest": "1" * 64,
            "coverage_status": "OUT_OF_SOURCE_COVERAGE" if excluded else "COMPLETE",
            "value": None if excluded else 0.0,
            "expected_area_m2": None if excluded else 100.0,
            "intersected_area_m2": None if excluded else 100.0,
            "source_supported_area_m2": None if excluded else 100.0,
            "valid_area_m2": None if excluded else 100.0,
            "source_coverage_fraction": None if excluded else 1.0,
            "valid_fraction_of_supported_area": None if excluded else 1.0,
            "native_class_area_m2": {} if excluded else {"11": 100.0},
        }
        for measure in sorted(p.MEASURES)
    ]


def seed(root: Path, basis: p.Json, selected: list[str], count: int) -> str:
    lineage = {**basis, "selected_counties": selected}
    digest = p.fingerprint(lineage)
    run = "mrlc2025_" + digest
    p.immutable(root / (run + ".lineage.json"), lineage)
    for i, fips in enumerate(selected[:count]):
        rr = rows(fips, digest, basis)
        p.immutable(
            root / "partitions" / f"{run}.part-{i:08d}.json",
            {
                "ordinal": i,
                "records": rr,
                "sha256": p.fingerprint(rr),
                "byte_count": len(p.canonical(rr)),
            },
        )
    return digest


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_assignment_exact_disjoint_deterministic(workers: int) -> None:
    counties = [f"{i:05d}" for i in range(10001, 12912)]
    bins = p.assign(counties, workers)
    assert bins == p.assign(counties, workers)
    assert sorted(f for group in bins for f in group) == counties
    assert max(map(len, bins)) - min(map(len, bins)) <= 1


def test_measured_balancing_is_frozen_and_deterministic() -> None:
    counties = ["01001", "01003", "01005", "01007"]
    timing = {"01001": 100.0, "01003": 90.0, "01005": 10.0, "01007": 20.0}
    assert p.assign(counties, 2, timing) == [["01001", "01005"], ["01003", "01007"]]
    with pytest.raises(ValueError):
        p.assign(counties, 2, {"01001": float("nan")})


@pytest.mark.parametrize("counties", [["1001"], ["01001", "01001"], ["01003", "01001"]])
def test_bad_counties_rejected(counties: list[str]) -> None:
    with pytest.raises(ValueError):
        p.assign(counties, 2)


def test_integrity_preserves_completed_bytes(tmp_path: Path, basis: p.Json) -> None:
    seed(tmp_path, basis, ["01001", "01003"], 1)
    before = {str(f): f.read_bytes() for f in tmp_path.rglob("*.json")}
    refs = p.audit_run(tmp_path, basis, ["01001", "01003"])
    assert [r["county_fips"] for r in refs] == ["01001"]
    assert before == {str(f): f.read_bytes() for f in tmp_path.rglob("*.json")}
    with pytest.raises(ValueError, match="assignment"):
        p.audit_run(tmp_path, basis, ["01001", "01005"])
    with pytest.raises(ValueError, match="identity"):
        p.audit_run(tmp_path, {**basis, "weight_code_sha256": "0" * 64})


def test_corruption_rejected(tmp_path: Path, basis: p.Json) -> None:
    seed(tmp_path, basis, ["01001"], 1)
    path = next((tmp_path / "partitions").glob("*.json"))
    d = p.read_json(path)
    d["records"][0]["value"] = 0.25
    path.write_bytes(p.canonical(d))
    with pytest.raises(ValueError, match="checksum"):
        p.audit_run(tmp_path, basis)


def test_seven_measures_and_exclusions(basis: p.Json) -> None:
    rr = rows("01001", "x", basis)
    p.validate_rows(rr, "01001", "x", basis)
    rr[0]["measure"] = rr[1]["measure"]
    with pytest.raises(ValueError, match="seven"):
        p.validate_rows(rr, "01001", "x", basis)
    rr = rows("15001", "x", basis)
    p.validate_rows(rr, "15001", "x", basis)
    rr[0]["value"] = 0
    with pytest.raises(ValueError, match="exclusion"):
        p.validate_rows(rr, "15001", "x", basis)


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", float("nan")),
        ("value", True),
        ("intersected_area_m2", 200),
        ("valid_area_m2", 101),
        ("source_coverage_fraction", 0.5),
    ],
)
def test_numeric_area_rules(basis: p.Json, field: str, value: Any) -> None:
    rr = rows("01001", "x", basis)
    rr[0][field] = value
    with pytest.raises(ValueError):
        p.validate_rows(rr, "01001", "x", basis)


def test_partial_and_missing_are_null(basis: p.Json) -> None:
    rr = rows("01001", "x", basis)
    for r in rr:
        r.update(
            valid_area_m2=50,
            valid_fraction_of_supported_area=0.5,
            coverage_status="PARTIAL_COVERAGE",
            value=None,
            native_class_area_m2={"11": 50},
        )
    p.validate_rows(rr, "01001", "x", basis)
    rr[0]["value"] = 0
    with pytest.raises(ValueError):
        p.validate_rows(rr, "01001", "x", basis)
    for r in rr:
        r.update(
            valid_area_m2=0,
            source_supported_area_m2=0,
            source_coverage_fraction=0,
            valid_fraction_of_supported_area=None,
            coverage_status="SOURCE_MISSING",
            value=None,
            native_class_area_m2={},
        )
    p.validate_rows(rr, "01001", "x", basis)


def test_foreign_partition_and_fake_completion_rejected(tmp_path: Path, basis: p.Json) -> None:
    digest = seed(tmp_path, basis, ["01001", "01003"], 1)
    marker = tmp_path / "partitions" / f"mrlc2025_{digest}.partitions-complete.json"
    p.immutable(marker, {"count": 2})
    with pytest.raises(ValueError, match="completion"):
        p.audit_run(tmp_path, basis)


def test_mixed_run_references_preserve_lineage(tmp_path: Path, basis: p.Json) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    first = seed(one, basis, ["01001"], 1)
    second = seed(two, basis, ["01003"], 1)
    refs = p.audit_run(one, basis) + p.audit_run(two, basis)
    assert {r["run_id"] for r in refs} == {"mrlc2025_" + first, "mrlc2025_" + second}
    assert all(r["file_sha256"] for r in refs)


def test_national_union_rejects_duplicate_missing_and_wrong_rows() -> None:
    universe = [f"{i:05d}" for i in range(10001, 13110)]
    refs = [{"county_fips": f, "rows": 7} for f in universe]
    p.validate_union(refs, universe)
    with pytest.raises(ValueError):
        p.validate_union(refs[:-1], universe)
    with pytest.raises(ValueError):
        p.validate_union(refs[:-1] + [refs[0]], universe)
    refs[0]["rows"] = 6
    with pytest.raises(ValueError):
        p.validate_union(refs, universe)


def fixture_plan(basis: p.Json) -> p.Json:
    universe = [f"{i:05d}" for i in range(10001, 13110)]
    accepted = [{"county_fips": f} for f in universe[:198]]
    remaining = universe[198:]
    body = {
        "schema": "atlas-nlcd-assignment/1",
        "scope": "national",
        "basis": basis,
        "universe": universe,
        "accepted": accepted,
        "origins": ["national", "proof"],
        "workers": p.assign(remaining, 8),
        "remaining": remaining,
        "timings": None,
        "timings_sha256": p.fingerprint(None),
    }
    return {**body, "plan_id": p.fingerprint(body)}


def test_plan_conflict_and_worker_tamper(tmp_path: Path, basis: p.Json) -> None:
    plan = fixture_plan(basis)
    p.save_plan(tmp_path, plan)
    assert p.load_plan(tmp_path) == plan
    altered = copy.deepcopy(plan)
    altered["workers"][0][0] = "99999"
    with pytest.raises(ValueError, match="Immutable"):
        p.save_plan(tmp_path, altered)
    worker = tmp_path / "worker-00.json"
    d = p.read_json(worker)
    d["counties"].pop()
    worker.write_bytes(p.canonical(d))
    with pytest.raises(ValueError, match="worker manifest"):
        p.load_plan(tmp_path)


def runtime_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        state=tmp_path / "state",
        code=tmp_path / "code",
        inputs=tmp_path / "inputs",
        image="sha256:" + "a" * 64,
        cpus=1,
        memory_gib=2,
        seconds=1800,
        batch_counties=8,
        retry_timeouts=False,
    )


class FakeDocker(rt.Docker):
    def __init__(self) -> None:
        self.containers: dict[str, p.Json] = {}
        self.calls: list[tuple[str, ...]] = []
        self.logs = ""

    def inspect(self, name: str) -> p.Json | None:
        return self.containers.get(name)

    def action(self, *arguments: str) -> str:
        self.calls.append(arguments)
        if arguments[0] == "create":
            name = arguments[arguments.index("--name") + 1]
            labels = dict(
                arguments[i + 1].split("=", 1) for i, a in enumerate(arguments) if a == "--label"
            )
            self.containers[name] = {
                "Config": {"Labels": labels, "User": "1001:1001"},
                "Mounts": [
                    {
                        "Source": fields["src"],
                        "Destination": fields["dst"],
                        "RW": "readonly" not in spec.split(","),
                    }
                    for i, arg in enumerate(arguments)
                    if arg == "--mount"
                    for spec in [arguments[i + 1]]
                    for fields in [dict(v.split("=", 1) for v in spec.split(",") if "=" in v)]
                ],
                "State": {
                    "Running": False,
                    "Status": "created",
                    "ExitCode": 0,
                    "StartedAt": datetime.now(UTC).isoformat(),
                },
            }
        if arguments[0] == "start":
            self.containers[arguments[1]]["State"].update(Running=True, Status="running")
        return self.logs if arguments[0] == "logs" else ""


def test_worker_isolation_and_restart_adopts_running(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"], ["01003"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    assert rt.tick(plan, args, 0, docker) is False
    assert rt.tick(plan, args, 1, docker) is False
    creates = [c for c in docker.calls if c[0] == "create"]
    assert len(creates) == 2
    assert "01001" in creates[0] and "01003" in creates[1]
    assert any("worker-00/results" in a.replace("\\", "/") for a in creates[0])
    assert any("worker-01/results" in a.replace("\\", "/") for a in creates[1])
    for cmd in creates:
        assert "--network=none" in cmd and "--read-only" in cmd
        assert "--privileged" not in cmd and "--pull=never" in cmd
    # Simulates a new supervisor process encountering the retained owned container.
    assert rt.tick(plan, args, 0, docker) is False
    assert len([c for c in docker.calls if c[0] == "create"]) == 2
    name = next(iter(docker.containers))
    docker.containers[name]["Config"]["Labels"][rt.LABEL] = "foreign"
    with pytest.raises(ValueError, match="ownership"):
        rt.tick(plan, args, 0, docker)


def test_interrupted_completed_partition_is_preserved(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001", "01003"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    name = next(iter(docker.containers))
    root = args.state / "worker-00"
    seed(root / "results", basis, plan["workers"][0], 1)
    before = next((root / "results/partitions").glob("*.json")).read_bytes()
    (root / "results/calculation.lock").touch()
    docker.containers[name]["State"].update(Running=False, Status="exited", ExitCode=143)
    p.immutable(root / "attempt-00001.stop.json", {"reason": "SUPERVISOR_SHUTDOWN"})
    rt.tick(plan, args, 0, docker)
    assert next((root / "results/partitions").glob("*.json")).read_bytes() == before
    assert (root / "attempt-00001.calculation.lock").exists()
    assert p.read_json(root / "attempt-00001.result.json")["kind"] == "INTERRUPTED"
    assert len(docker.containers) == 2


def test_no_progress_timeout_never_retries(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    args.retry_timeouts = True
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    name = next(iter(docker.containers))
    docker.containers[name]["State"].update(Running=False, Status="exited", ExitCode=124)
    with pytest.raises(ValueError, match="failed exit 124"):
        rt.tick(plan, args, 0, docker)
    assert len(docker.containers) == 1


def test_foreign_or_live_locks_never_archived(tmp_path: Path) -> None:
    root = tmp_path
    (root / "results").mkdir()
    (root / "results/calculation.lock").touch()
    with pytest.raises(ValueError, match="still owns"):
        rt.reconcile_lock(root, {"State": {"Running": True}}, {"attempt": 1})
    assert (root / "results/calculation.lock").exists()


def test_paths_and_immutable_publication(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        p.contained(tmp_path, "../foreign")
    path = tmp_path / "receipt.json"
    p.immutable(path, {"a": 1})
    p.immutable(path, {"a": 1})
    with pytest.raises(ValueError):
        p.immutable(path, {"a": 2})
    assert p.read_json(path) == {"a": 1}


def test_seed_plan_and_resume_contract_end_to_end(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Generated fixture rows are intentionally not accepted as real evidence by production pins.
    canonical = Path(p.__file__).parent / "data/canonical-county-fips-2022.txt"
    counties = sorted(canonical.read_text().splitlines())
    artifacts = tmp_path / "artifacts"
    national = seed(artifacts / "national", basis, counties, 223)
    proof = seed(
        artifacts / "proof",
        basis,
        ["02013", "06075", "09110", "15001", "46127", "48081", "51013"],
        7,
    )
    monkeypatch.setattr(p, "REFERENCE", national)
    monkeypatch.setattr(p, "PROOF", proof)
    monkeypatch.setattr(
        p,
        "SEED_INVENTORIES",
        (
            p.fingerprint(p.audit_run(artifacts / "national", basis)),
            p.fingerprint(p.audit_run(artifacts / "proof", basis)),
        ),
    )
    plan = p.make_plan(artifacts, ["national", "proof"], 8)
    assert len(plan["remaining"]) == 2911 and len(plan["accepted"]) == 198
    assert not set(plan["remaining"]) & {r["county_fips"] for r in plan["accepted"]}
    directory = tmp_path / "plan"
    p.save_plan(directory, plan)
    resumed = p.load_plan(directory)
    p.verify_accepted(resumed, artifacts)
    with pytest.raises(ValueError, match="missing"):
        p.assembly(resumed, artifacts, tmp_path / "state")
    # A small newly committed worker prefix remains independently attributable.
    worker = tmp_path / "state/worker-00/results"
    digest = seed(worker, basis, plan["workers"][0], 1)
    progress = rt.status(resumed, tmp_path / "state")
    assert progress["new_completed"] == 1
    assert p.audit_run(worker, basis, plan["workers"][0])[0]["run_id"] == "mrlc2025_" + digest
    # Modifying accepted bytes cannot be hidden by an unchanged assignment.
    part = next((artifacts / "national/partitions").glob("*.json"))
    part.write_bytes(part.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes changed"):
        p.verify_accepted(resumed, artifacts)


def test_scientific_failure_halts_without_lock_removal(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    root = args.state / "worker-00"
    (root / "results/calculation.lock").touch()
    container = next(iter(docker.containers.values()))
    container["State"].update(Running=False, Status="exited", ExitCode=1)
    docker.logs = "Traceback: ValueError: Pixel or supported areas exceed frozen county area"
    with pytest.raises(ValueError, match="failed exit 1"):
        rt.tick(plan, args, 0, docker)
    assert (root / "results/calculation.lock").exists()
    assert len(docker.containers) == 1


def test_successful_completed_worker_does_not_launch_again(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    seed(args.state / "worker-00/results", basis, ["01001"], 1)
    context = next((args.state / "worker-00/results").glob("*.lineage.json"))
    p.immutable(
        context.parent
        / "partitions"
        / context.name.replace(".lineage.json", ".partitions-complete.json"),
        {"count": 1},
    )
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=0
    )
    assert rt.tick(plan, args, 0, docker) is True
    assert rt.tick(plan, args, 0, docker) is True
    assert len(docker.containers) == 1


@pytest.mark.parametrize("change", ["payload", "physical", "receipt"])
def test_frozen_terminal_rejects_self_consistent_tampering(
    tmp_path: Path, basis: p.Json, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]], "accepted": []}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    monkeypatch.setattr(p, "verify_accepted", lambda *a: None)
    plan["scope"] = "national"
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    root = args.state / "worker-00/results"
    digest = seed(root, basis, ["01001"], 1)
    marker = root / "partitions" / f"mrlc2025_{digest}.partitions-complete.json"
    p.immutable(marker, {"count": 1})
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=0
    )
    assert rt.tick(plan, args, 0, docker)
    part = next((root / "partitions").glob("*.part-*.json"))
    receipt_ref = p.read_json(root.parent / "completed.inventory.json")["completion_receipts"][0]
    assert receipt_ref["path"].startswith("partitions/") and "\\" not in receipt_ref["path"]
    if change == "payload":
        payload = p.read_json(part)
        payload["records"][0]["value"] = 0.5
        payload["sha256"] = p.fingerprint(payload["records"])
        payload["byte_count"] = len(p.canonical(payload["records"]))
        part.write_bytes(p.canonical(payload))
    else:
        target = marker if change == "receipt" else part
        target.write_bytes(target.read_bytes() + b"\n")
    for operation in (
        lambda: rt.tick(plan, args, 0, docker),
        lambda: rt.status(plan, args.state),
        lambda: p.assembly(plan, tmp_path, args.state),
        lambda: p.verify_inventory(
            plan, root, 0, root.parent / "completed.inventory.json", complete=True
        ),
    ):
        with pytest.raises(ValueError, match="inventory changed"):
            operation()


def test_final_marker_publication_race_has_one_stable_reaudit(
    tmp_path: Path, basis: p.Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = ["01001", "01003"]
    digest = seed(tmp_path, basis, selected, 1)
    original = Path.glob
    published = False

    def interleaving(path: Path, pattern: str) -> Any:
        nonlocal published
        if (
            path == tmp_path / "partitions"
            and pattern == "*partitions-complete.json"
            and not published
        ):
            published = True
            seed(tmp_path, basis, selected, 2)
            p.immutable(path / f"mrlc2025_{digest}.partitions-complete.json", {"count": 2})
        return original(path, pattern)

    monkeypatch.setattr(Path, "glob", interleaving)
    assert len(p.audit_run(tmp_path, basis, selected)) == 2
    assert published


@pytest.mark.parametrize("marker", [{"count": 1}, {"count": 2}, {"count": 2, "extra": True}])
def test_stable_bad_completion_fails_closed(tmp_path: Path, basis: p.Json, marker: p.Json) -> None:
    digest = seed(tmp_path, basis, ["01001", "01003"], 1)
    p.immutable(tmp_path / "partitions" / f"mrlc2025_{digest}.partitions-complete.json", marker)
    with pytest.raises(ValueError, match="completion receipt"):
        p.audit_run(tmp_path, basis)


def test_publication_retry_is_strictly_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def changing(*args: Any) -> list[p.Json]:
        calls.append(1)
        raise p.PublicationChanged("still changing")

    monkeypatch.setattr(p, "_audit_run", changing)
    with pytest.raises(p.PublicationChanged):
        p.audit_run(Path("unused"), {})
    assert len(calls) == 2


def test_worker_rejects_wrong_container_user(tmp_path: Path) -> None:
    container = {"Config": {"User": "0:0", "Labels": {}}}
    with pytest.raises(ValueError, match="UID/GID"):
        rt.owned(container, "plan", 0, tmp_path)


@pytest.mark.parametrize(
    "crash_after", ["inventory.json", "result.json", "completed.inventory.json"]
)
def test_terminal_publication_crash_recovers_original_inventory(
    tmp_path: Path, basis: p.Json, monkeypatch: pytest.MonkeyPatch, crash_after: str
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    root = args.state / "worker-00/results"
    digest = seed(root, basis, ["01001"], 1)
    p.immutable(root / "partitions" / f"mrlc2025_{digest}.partitions-complete.json", {"count": 1})
    original = p.audit_run(root, basis)
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=0
    )

    def crash(path: Path, value: p.Json) -> None:
        p.immutable(path, value)
        target = (
            "attempt-00001." + crash_after
            if crash_after != "completed.inventory.json"
            else crash_after
        )
        if path.name == target:
            raise RuntimeError("simulated operator death")

    with monkeypatch.context() as patch:
        patch.setattr(rt, "immutable", crash)
        with pytest.raises(RuntimeError, match="operator death"):
            rt.tick(plan, args, 0, docker)
    assert rt.tick(plan, args, 0, docker)
    assert p.audit_run(root, basis) == original
    assert len(docker.containers) == 1


def test_worker_uses_explicit_nonroot_identity(tmp_path: Path, basis: p.Json) -> None:
    args = runtime_args(tmp_path)
    command = rt.worker_command({"plan_id": "a", "workers": [["01001"]]}, args, 0, 1, "test")
    assert command[command.index("--user") + 1] == "1001:1001"
    assert "--cap-drop=ALL" in command and "--network=none" in command


def test_last_partition_without_receipt_requires_calculator_resume(
    tmp_path: Path, basis: p.Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    root = args.state / "worker-00/results"
    digest = seed(root, basis, ["01001"], 1)
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=0
    )
    assert not rt.tick(plan, args, 0, docker)
    assert len(docker.containers) == 2
    original = p.audit_run(root, basis)
    p.immutable(root / "partitions" / f"mrlc2025_{digest}.partitions-complete.json", {"count": 1})
    list(docker.containers.values())[-1]["State"].update(Running=False, Status="exited", ExitCode=0)
    assert rt.tick(plan, args, 0, docker)
    assert p.audit_run(root, basis) == original


def test_interrupted_restart_rejects_rehashed_completed_prefix(
    tmp_path: Path, basis: p.Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001", "01003"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    root = args.state / "worker-00/results"
    seed(root, basis, plan["workers"][0], 1)
    p.immutable(root.parent / "attempt-00001.stop.json", {"reason": "SUPERVISOR_SHUTDOWN"})
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=143
    )
    assert not rt.tick(plan, args, 0, docker)
    path = next((root / "partitions").glob("*.part-*.json"))
    payload = p.read_json(path)
    payload["records"][0]["value"] = 0.5
    payload["sha256"] = p.fingerprint(payload["records"])
    payload["byte_count"] = len(p.canonical(payload["records"]))
    path.write_bytes(p.canonical(payload))
    with pytest.raises(ValueError, match="inventory changed"):
        rt.tick(plan, args, 0, docker)


def test_malformed_marker_is_never_pending(
    tmp_path: Path, basis: p.Json, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]], "accepted": []}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    root = args.state / "worker-00/results"
    digest = seed(root, basis, ["01001"], 1)
    (root / "partitions" / f"mrlc2025_{digest}.partitions-complete.json").write_text("{")
    import json

    with pytest.raises(json.JSONDecodeError):
        rt.tick(plan, args, 0, docker)
    with pytest.raises(json.JSONDecodeError):
        rt.status(plan, args.state)


@pytest.mark.skipif(
    not os.environ.get("NLCD_NATIVE_DOCKER_ROOT"), reason="Explicit native Linux Docker proof only"
)
def test_linux_docker_nonroot_commit_interrupt_resume() -> None:
    """Real Linux UID/GID, two real counties, host audit, stop/resume and byte hashes."""
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "scripts/verify_nlcd_linux_identity.py",
            "--root",
            os.environ["NLCD_NATIVE_DOCKER_ROOT"],
            "--basis",
            os.environ["NLCD_NATIVE_BASIS"],
        ],
        check=True,
        timeout=1900,
    )


def test_timeout_with_progress_requires_explicit_bounded_recovery(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001", "01003"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    seed(args.state / "worker-00/results", basis, plan["workers"][0], 1)
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=124
    )
    with pytest.raises(ValueError, match="retry-timeouts"):
        rt.tick(plan, args, 0, docker)
    assert len(docker.containers) == 1
    args.retry_timeouts = True
    rt.tick(plan, args, 0, docker)
    assert len(docker.containers) == 2


def test_reboot_terminal_owner_can_resume(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    monkeypatch.setattr(rt, "boot_id", lambda: "old-boot")
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=137
    )
    monkeypatch.setattr(rt, "boot_id", lambda: "new-boot")
    rt.tick(plan, args, 0, docker)
    assert p.read_json(args.state / "worker-00/attempt-00001.result.json")["kind"] == "INTERRUPTED"
    assert len(docker.containers) == 2


def test_nonempty_stale_lock_needs_diagnosis(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    lock = tmp_path / "results/calculation.lock"
    lock.write_text("unexpected")
    with pytest.raises(ValueError, match="Unexpected lock"):
        rt.reconcile_lock(
            tmp_path, {"State": {"Running": False, "Status": "exited"}}, {"attempt": 1}
        )
    assert lock.read_text() == "unexpected"


@pytest.mark.skipif(os.name != "posix", reason="Linux kernel advisory lock")
def test_only_one_linux_supervisor_owns_state(tmp_path: Path) -> None:
    with (
        rt.ownership(tmp_path),
        pytest.raises(ValueError, match="Another supervisor"),
        rt.ownership(tmp_path),
    ):
        pytest.fail("second writer admitted")


def test_stalled_worker_halts(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]]}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    next(iter(docker.containers.values()))["State"]["StartedAt"] = "2020-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="stalled"):
        rt.tick(plan, args, 0, docker)


def test_final_assembly_is_deterministic_and_keeps_original_runs(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = fixture_plan(basis)
    for i, ref in enumerate(plan["accepted"]):
        ref.update(
            rows=7,
            run_id="national" if i < 193 else "proof",
            payload_sha256="original",
            file_sha256="original-file",
        )
    monkeypatch.setattr(p, "verify_accepted", lambda *a: None)
    monkeypatch.setattr(p, "verify_inventory", lambda *a, **kw: {})
    monkeypatch.setattr(
        p,
        "audit_run",
        lambda root, basis, selected: [
            {
                "county_fips": f,
                "rows": 7,
                "run_id": root.parent.name,
                "payload_sha256": f,
                "file_sha256": f,
            }
            for f in selected
        ],
    )
    before = copy.deepcopy(plan["accepted"])
    for index in range(8):
        p.immutable(tmp_path / f"worker-{index:02d}/completed.inventory.json", {"fixture": index})
    result = p.assembly(plan, tmp_path, tmp_path)
    assert result == p.assembly(plan, tmp_path, tmp_path)
    assert result["observations"] == 21763 and result["counties"] == 3109
    assert "national" in result["runs"] and "proof" in result["runs"]
    assert plan["accepted"] == before
    output = tmp_path / "assembly.json"
    p.immutable(output, result)
    p.immutable(output, result)
    assert p.read_json(output) == result


def test_copied_state_cannot_adopt_or_stop_another_output(tmp_path: Path) -> None:
    container = {
        "Config": {"Labels": {rt.LABEL: "plan", "atlas.nlcd.worker": "0"}, "User": "1001:1001"},
        "Mounts": [{"Destination": "/results", "Source": str(tmp_path / "original"), "RW": True}],
    }
    rt.owned(container, "plan", 0, tmp_path / "original")
    with pytest.raises(ValueError, match="different state directory"):
        rt.owned(container, "plan", 0, tmp_path / "copy")


@pytest.mark.skipif(os.name != "posix", reason="Portable CI symlink creation")
def test_symlink_cannot_alias_worker_outputs(tmp_path: Path, basis: p.Json) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        p.audit_run(alias / "results", basis)


def test_shutdown_attempts_other_workers_after_ownership_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visited = []

    def stop(plan: p.Json, state: Path, docker: rt.Docker, index: int) -> None:
        visited.append(index)
        if index == 0:
            raise ValueError("foreign owner")

    monkeypatch.setattr(rt, "stop_worker", stop)
    with pytest.raises(ValueError, match="shutdown requires attention"):
        rt.stop_owned({"workers": [[], []]}, tmp_path, FakeDocker())
    assert visited == [0, 1]


def test_rebuilt_runtime_cannot_substitute_for_audited_image() -> None:
    image = {"Os": "linux", "Architecture": "amd64", "Id": rt.RUNTIME_IMAGE_ID}
    rt.validate_image(image)
    with pytest.raises(ValueError, match="Exact audited"):
        rt.validate_image({**image, "Id": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="Exact audited"):
        rt.validate_image({**image, "Architecture": "arm64"})


def test_in_progress_lineage_is_pending_but_terminal_audit_is_strict(
    tmp_path: Path,
    basis: p.Json,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = runtime_args(tmp_path)
    plan = {"plan_id": "d" * 64, "basis": basis, "workers": [["01001"]], "accepted": []}
    monkeypatch.setattr(rt, "verify_code", lambda *a: None)
    docker = FakeDocker()
    rt.tick(plan, args, 0, docker)
    context = args.state / "worker-00/results/in-progress.lineage.json"
    context.write_text("{")  # Writer has created the file but has not published its JSON yet.
    assert rt.tick(plan, args, 0, docker) is False
    assert rt.status(plan, args.state)["workers"][0]["state"] == "SNAPSHOT_PENDING"
    next(iter(docker.containers.values()))["State"].update(
        Running=False, Status="exited", ExitCode=1
    )
    with pytest.raises(ValueError, match="Terminal worker has unreadable"):
        rt.tick(plan, args, 0, docker)
