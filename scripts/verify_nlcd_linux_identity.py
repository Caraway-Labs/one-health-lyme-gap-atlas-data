"""Opt-in, two-county native-Linux Docker recovery proof; never a national launcher.

Run as a non-root Linux operator with staged, disposable code/inputs/state on
native Linux storage. Uses only the pinned cached image. See operator docs.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from lyme_gap_atlas_data import nlcd_parallel as p
from lyme_gap_atlas_data import nlcd_parallel_runtime as rt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--basis", type=Path, required=True)
    args = parser.parse_args()
    uid, gid = rt.operator_identity()
    basis = p.identity(p.read_json(args.basis))
    state = args.root / "identity-test"
    p.require(not state.exists(), "Use a fresh disposable directory; never overwrite evidence")
    runtime = argparse.Namespace(
        state=state,
        code=args.root / "code",
        inputs=args.root / "inputs",
        image=rt.RUNTIME_IMAGE_ID,
        cpus=1,
        memory_gib=2,
        seconds=900,
        batch_counties=1,
        retry_timeouts=False,
    )
    plan = {
        "plan_id": p.fingerprint({"identity-test": str(state), "uid": uid, "gid": gid}),
        "basis": basis,
        "workers": [["51013", "51610"]],
        "accepted": [],
    }
    docker = rt.Docker()
    rt.verify_code(runtime.code, basis)
    rt.verify_inputs(runtime.inputs, basis)
    rt.validate_image(json.loads(docker.action("image", "inspect", runtime.image))[0])
    state.mkdir(mode=0o750)
    results = state / "worker-00/results"
    results.mkdir(parents=True, mode=0o750)
    # Reproduce the original failure on Linux DAC, in precisely the same directory.
    try:
        docker.action(
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cpus=0.5",
            "--memory=128m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--mount",
            f"type=bind,src={results},dst=/results",
            "--entrypoint",
            "/app/.venv/bin/python",
            runtime.image,
            "-c",
            "open('/results/root-should-fail', 'x').close()",
        )
    except ValueError as exc:
        p.require("PermissionError" in str(exc), "Baseline failure was not Linux DAC")
    else:
        raise AssertionError("Root/cap-drop baseline unexpectedly wrote host-owned directory")
    start = time.monotonic()
    prefix: list[p.Json] = []
    interrupted = False
    try:
        while True:
            done = rt.tick(plan, runtime, 0, docker)
            refs = p.audit_run(results, basis, plan["workers"][0])
            if len(refs) == 1 and not prefix:
                prefix = refs
                for ref in refs:
                    path = results / ref["partition_path"]
                    p.require(
                        path.stat().st_uid == uid and path.stat().st_gid == gid, "Wrong owner"
                    )
                    p.require(path.stat().st_mode & 0o007 == 0, "World-accessible partition")
            intents = sorted(results.parent.glob("*.intent.json"))
            if prefix and len(intents) == 2 and not interrupted:
                rt.stop_owned(plan, state, docker)
                interrupted = True
            if prefix:
                p.require(refs[:1] == prefix, "Committed county changed across interruption")
            if done:
                break
            p.require(time.monotonic() - start < 1800, "Bounded integration deadline exceeded")
            time.sleep(2)
        p.require(interrupted, "Controlled interruption was not exercised")
        p.require(len(refs) == 2 and rt.tick(plan, runtime, 0, docker), "Resume did not complete")
        inventory = p.verify_inventory(
            plan, results, 0, results.parent / "completed.inventory.json", complete=True
        )
        report = {
            "uid": uid,
            "gid": gid,
            "root_baseline": "PermissionError",
            "counties": [r["county_fips"] for r in refs],
            "observations": 14,
            "interrupted": interrupted,
            "original_prefix": prefix,
            "inventory_id": inventory["inventory_id"],
            "elapsed_seconds": time.monotonic() - start,
            "attempts": [
                p.read_json(path) for path in sorted(results.parent.glob("*.result.json"))
            ],
        }
        p.immutable(state / "verification.json", report)
        print(json.dumps(report, sort_keys=True))
    finally:
        rt.stop_owned(plan, state, docker)
        for path in results.parent.glob("*.intent.json"):
            meta = p.read_json(path)
            container = docker.inspect(meta["name"])
            if container is not None:
                rt.owned(container, plan["plan_id"], 0, results)
                p.require(not container["State"]["Running"], "Test worker still running")
                docker.action("rm", meta["name"])


if __name__ == "__main__":
    main()
