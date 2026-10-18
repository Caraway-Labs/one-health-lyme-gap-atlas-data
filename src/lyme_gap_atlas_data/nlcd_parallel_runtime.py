"""Single-host Linux Docker supervisor for the frozen NLCD assignment contract."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .nlcd_parallel import (
    REVISION,
    Json,
    audit_run,
    canonical,
    file_hash,
    immutable,
    read_json,
    require,
    verify_accepted,
)

LABEL = "atlas.nlcd.plan"


def boot_id() -> str:
    path = Path("/proc/sys/kernel/random/boot_id")
    return path.read_text().strip() if path.exists() else "unavailable"


def command(arguments: list[str], timeout: int = 60) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
    require(
        result.returncode == 0,
        f"Command failed ({arguments[0]} {arguments[1]}): {result.stderr[:2000]}",
    )
    return result.stdout + (result.stderr if arguments[1:2] == ["logs"] else "")


def atomic_status(path: Path, value: Json) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".status-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def ownership(state: Path) -> Iterator[None]:
    require(os.name == "posix", "Execution requires Linux; planning/audit are portable")
    fcntl = importlib.import_module("fcntl")
    with (state / "supervisor.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another supervisor owns this state directory") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def verify_code(code: Path, basis: Json) -> None:
    require(
        command(["git", "-C", str(code), "rev-parse", "HEAD"]).strip() == REVISION,
        "Calculator checkout must be exact #606 revision",
    )
    require(
        not command(["git", "-C", str(code), "status", "--porcelain"]).strip(),
        "Calculator checkout is dirty",
    )
    for key, relative in (
        ("calculation_code_sha256", "ingestion/annual_nlcd_mosaic.py"),
        ("weight_code_sha256", "ingestion/annual_nlcd.py"),
        ("geometry_code_sha256", "county_analysis_geometry.py"),
    ):
        require(
            file_hash(code / "src/lyme_gap_atlas_data" / relative) == basis[key],
            "Calculator/geometry bytes differ (including line endings)",
        )


def verify_inputs(inputs: Path, basis: Json) -> None:
    require(
        file_hash(inputs / "verified-inputs.json") == basis["input_manifest_sha256"],
        "Input manifest changed",
    )
    source = basis["source"]
    require(read_json(inputs / "verified-inputs.json") == source, "Source identity changed")
    require(
        file_hash(inputs / "mrlc-capture-receipt.json") == source["capture_receipt_sha256"],
        "Capture receipt changed",
    )
    for record in source["packages"].values():
        for member in record["members"]:
            require(Path(member["name"]).name == member["name"], "Unsafe input member")
            path = inputs / member["name"]
            require(
                path.stat().st_size == member["bytes"] and file_hash(path) == member["sha256"],
                "Prepared source member changed",
            )
    require(file_hash(inputs / "tl_2025_us_county.zip") == basis["tiger_sha256"], "TIGER changed")


class Docker:
    def inspect(self, name: str) -> Json | None:
        # Do not interpret daemon errors as missing containers.
        names = command(["docker", "container", "ls", "-a", "--format", "{{.Names}}"])
        if name not in names.splitlines():
            return None
        return json.loads(command(["docker", "inspect", name]))[0]  # type: ignore[no-any-return]

    def action(self, *arguments: str) -> str:
        return command(["docker", *arguments])


def owned(container: Json, plan_id: str, worker: int) -> None:
    labels = container["Config"]["Labels"]
    require(
        labels.get(LABEL) == plan_id and labels.get("atlas.nlcd.worker") == str(worker),
        "Container ownership conflict; never stop or adopt a foreign container",
    )


def worker_command(
    plan: Json, args: argparse.Namespace, index: int, attempt: int, name: str
) -> list[str]:
    root = args.state.resolve() / f"worker-{index:02d}"
    selected = plan["workers"][index]
    return [
        "create",
        "--pull=never",
        "--name",
        name,
        "--label",
        f"{LABEL}={plan['plan_id']}",
        "--label",
        f"atlas.nlcd.worker={index}",
        "--label",
        f"atlas.nlcd.attempt={attempt}",
        f"--cpus={args.cpus}",
        f"--memory={args.memory_gib}g",
        f"--memory-swap={args.memory_gib}g",
        "--pids-limit=64",
        "--log-driver=local",
        "--log-opt=max-size=2m",
        "--log-opt=max-file=2",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--env",
        "PYTHONPATH=/proof/src",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "OPENBLAS_NUM_THREADS=1",
        "--env",
        "OMP_NUM_THREADS=1",
        "--env",
        "PROJ_NETWORK=OFF",
        "--mount",
        f"type=bind,src={args.code.resolve()}/src,dst=/proof/src,readonly",
        "--mount",
        f"type=bind,src={args.code.resolve()}/config,dst=/proof/config,readonly",
        "--mount",
        f"type=bind,src={args.inputs.resolve()},dst=/inputs,readonly",
        "--mount",
        f"type=bind,src={root}/results,dst=/results",
        "--entrypoint",
        "timeout",
        args.image,
        "--signal=TERM",
        "--kill-after=10s",
        str(args.seconds),
        "/app/.venv/bin/python",
        "-m",
        "lyme_gap_atlas_data.ingestion.annual_nlcd_mosaic",
        "calculate",
        "--extracted",
        "/inputs",
        "--tiger",
        "/inputs/tl_2025_us_county.zip",
        "--output",
        "/results",
        "--counties",
        ",".join(selected),
        "--maximum-counties",
        str(args.batch_counties),
        "--seconds",
        str(args.seconds),
        "--code-revision",
        REVISION,
    ]


def status(plan: Json, state: Path) -> Json:
    workers = []
    for index, selected in enumerate(plan["workers"]):
        root = state / f"worker-{index:02d}"
        refs = audit_run(root / "results", plan["basis"], selected)
        status_path = root / "status.json"
        workers.append(
            {
                "worker": index,
                "assigned": len(selected),
                "completed": len(refs),
                "state": "COMPLETE" if len(refs) == len(selected) else "INCOMPLETE",
                "last_operator_status": read_json(status_path) if status_path.exists() else None,
            }
        )
    return {
        "plan_id": plan["plan_id"],
        "accepted": len(plan["accepted"]),
        "workers": workers,
        "new_completed": sum(w["completed"] for w in workers),
    }


def reconcile_lock(root: Path, container: Json, meta: Json) -> None:
    """Archive only an empty lock after the actual owned container is terminal."""
    require(
        not container["State"]["Running"] and container["State"]["Status"] in ("exited", "dead"),
        "Container still owns lock",
    )
    lock = root / "results/calculation.lock"
    if lock.exists():
        require(
            lock.is_file() and not lock.is_symlink() and lock.stat().st_size == 0,
            "Unexpected lock contents; manual diagnosis required",
        )
        destination = root / f"attempt-{meta['attempt']:05d}.calculation.lock"
        require(not destination.exists(), "Lock archive conflict")
        lock.rename(destination)


def finish_attempt(plan: Json, root: Path, meta: Json, container: Json, docker: Docker) -> Json:
    owned(container, plan["plan_id"], meta["worker"])
    refs = audit_run(root / "results", plan["basis"], plan["workers"][meta["worker"]])
    require(
        [r["file_sha256"] for r in refs[: len(meta["prefix"])]] == meta["prefix"],
        "Previously committed county changed",
    )
    code = container["State"]["ExitCode"]
    require(not container["State"].get("OOMKilled"), "OOM: halt; inspect resources before restart")
    logs = docker.action("logs", meta["name"])
    immutable(root / f"attempt-{meta['attempt']:05d}.log.json", {"stdout": logs})
    # Exit 124 is an operational timeout only if there is no calculator traceback.
    operational = code == 124 and "Traceback" not in logs and len(refs) > len(meta["prefix"])
    stop_path = root / f"attempt-{meta['attempt']:05d}.stop.json"
    interrupted = stop_path.exists() and read_json(stop_path)["reason"] == "SUPERVISOR_SHUTDOWN"
    interrupted = interrupted or (
        meta.get("boot_id", "unavailable") != "unavailable"
        and boot_id() != meta["boot_id"]
        and code in (137, 143)
    )
    result = {
        "attempt": meta["attempt"],
        "exit_code": code,
        "completed": len(refs),
        "new_counties": len(refs) - len(meta["prefix"]),
        "kind": (
            "SUCCESS"
            if code == 0
            else "INTERRUPTED"
            if interrupted and "Traceback" not in logs
            else "TIMEOUT_WITH_PROGRESS"
            if operational
            else "FAILED"
        ),
        "finished_at": container["State"].get("FinishedAt"),
        "started_at": container["State"].get("StartedAt"),
        "observed_at": time.time(),
    }
    if code == 0:
        require(result["new_counties"] > 0, "Successful invocation made no progress")
    immutable(root / f"attempt-{meta['attempt']:05d}.result.json", result)
    # Scientific/integrity failure leaves the lock in place for investigation.
    if result["kind"] != "FAILED":
        reconcile_lock(root, container, meta)
    return result


def tick(plan: Json, args: argparse.Namespace, index: int, docker: Docker) -> bool:
    """One worker transition. Immutable intent exists before any Docker mutation."""
    root = args.state / f"worker-{index:02d}"
    selected = plan["workers"][index]
    (root / "results").mkdir(parents=True, exist_ok=True)
    metas = sorted(root.glob("attempt-*.intent.json"))
    refs = audit_run(root / "results", plan["basis"], selected)
    if metas:
        meta = read_json(metas[-1])
        result_path = root / f"attempt-{meta['attempt']:05d}.result.json"
        container = docker.inspect(meta["name"])
        if container is None:
            raise ValueError("Recorded container missing; halt, preserve evidence")
        owned(container, plan["plan_id"], index)
        if container["State"]["Running"]:
            require(not result_path.exists(), "Terminal receipt has a running owner")
            started = datetime.fromisoformat(container["State"]["StartedAt"].replace("Z", "+00:00"))
            require(
                (datetime.now(UTC) - started).total_seconds() <= args.seconds + 60,
                f"Worker {index} stalled beyond hard deadline; stopping owned workload",
            )
            atomic_status(
                root / "status.json",
                {
                    "state": "RUNNING",
                    "completed": len(refs),
                    "container": meta["name"],
                    "observed_at": time.time(),
                },
            )
            return False
        if container["State"]["Status"] == "created":
            require(not result_path.exists(), "Terminal receipt has unstarted owner")
            docker.action("start", meta["name"])
            return False
        result = (
            read_json(result_path)
            if result_path.exists()
            else finish_attempt(plan, root, meta, container, docker)
        )
        if result["kind"] == "FAILED":
            atomic_status(root / "status.json", {"state": "FAILED", "result": result})
            raise ValueError(
                f"Worker {index} failed exit {result['exit_code']}; inspect logs; no auto retry"
            )
        reconcile_lock(root, container, meta)
        if result["kind"] == "TIMEOUT_WITH_PROGRESS":
            timeouts = sum(
                read_json(p)["kind"] == "TIMEOUT_WITH_PROGRESS"
                for p in root.glob("attempt-*.result.json")
            )
            require(
                args.retry_timeouts and timeouts <= 2,
                "Timeout: resume explicitly with --retry-timeouts (maximum two recoveries); "
                "single-county/no-progress timeouts require diagnosis",
            )
        if result["kind"] == "INTERRUPTED":
            interrupted_count = sum(
                read_json(p)["kind"] == "INTERRUPTED" for p in root.glob("attempt-*.result.json")
            )
            require(interrupted_count <= 2, "Repeated interruptions: halt for operator diagnosis")
    if len(refs) == len(selected):
        atomic_status(root / "status.json", {"state": "COMPLETE", "completed": len(refs)})
        return True
    require(not (root / "results/calculation.lock").exists(), "Unreconciled calculator lock")
    verify_code(args.code, plan["basis"])
    number = len(metas) + 1
    name = f"atlas-nlcd-{plan['plan_id'][:20]}-{index:02d}-{number:05d}"
    require(docker.inspect(name) is None, "Pre-existing container; preserve and diagnose")
    meta = {
        "plan_id": plan["plan_id"],
        "worker": index,
        "attempt": number,
        "name": name,
        "prefix": [r["file_sha256"] for r in refs],
        "recorded_at": time.time(),
        "boot_id": boot_id(),
    }
    immutable(root / f"attempt-{number:05d}.intent.json", meta)
    docker.action(*worker_command(plan, args, index, number, name))
    docker.action("start", name)
    return False


def stop_owned(plan: Json, state: Path, docker: Docker) -> None:
    for index in range(len(plan["workers"])):
        metas = sorted((state / f"worker-{index:02d}").glob("attempt-*.intent.json"))
        if metas:
            meta = read_json(metas[-1])
            container = docker.inspect(meta["name"])
            if container is not None:
                owned(container, plan["plan_id"], index)
                if container["State"]["Running"]:
                    path = (
                        state / f"worker-{index:02d}" / f"attempt-{meta['attempt']:05d}.stop.json"
                    )
                    if not path.exists():
                        immutable(
                            path, {"reason": "SUPERVISOR_SHUTDOWN", "requested_at": time.time()}
                        )
                    docker.action("stop", "--time", "15", meta["name"])


def preflight(plan: Json, args: argparse.Namespace, docker: Docker) -> None:
    require(
        math.isfinite(args.cpus) and 0 < args.cpus <= 16 and 1 <= args.memory_gib <= 32,
        "Invalid per-worker limits",
    )
    require(
        1 <= args.batch_counties <= 128
        and 60 <= args.seconds <= 1800
        and 1 <= args.max_duration <= 7 * 86400,
        "Invalid bounded runtime",
    )
    require(
        re.fullmatch(r"(?:sha256:|[a-zA-Z0-9./:_-]+@sha256:)[a-f0-9]{64}", args.image) is not None,
        "Pinned image required",
    )
    paths = [
        args.state.resolve(),
        args.code.resolve(),
        args.inputs.resolve(),
        args.artifacts.resolve(),
    ]
    require(
        not any(
            a == b or a.is_relative_to(b) or b.is_relative_to(a)
            for a in paths[:1]
            for b in paths[1:]
        ),
        "State must be isolated from inputs/artifacts/code",
    )
    require(all("," not in str(p) and not p.is_symlink() for p in paths), "Unsafe bind mount path")
    verify_accepted(plan, args.artifacts)
    verify_code(args.code, plan["basis"])
    verify_inputs(args.inputs, plan["basis"])
    info = json.loads(docker.action("info", "--format", "{{json .}}"))
    count = len(plan["workers"])
    require(
        count * args.cpus <= info["NCPU"]
        and count * args.memory_gib * 1024**3 <= info["MemTotal"] - 2 * 1024**3,
        "Insufficient Docker CPU/RAM plus 2 GiB reserve",
    )
    image = json.loads(docker.action("image", "inspect", args.image))[0]
    require(image["Os"] == "linux", "Linux image required")
    software_code = (
        "import json,platform,numpy,rasterio,pyproj,shapely;"
        "print(json.dumps(dict(python=platform.python_version(),numpy=numpy.__version__,"
        "rasterio=rasterio.__version__,gdal=rasterio.__gdal_version__,"
        "pyproj=pyproj.__version__,shapely=shapely.__version__)))"
    )
    observed = json.loads(
        docker.action(
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cpus=0.5",
            "--memory=512m",
            "--pids-limit=32",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--env",
            "OPENBLAS_NUM_THREADS=1",
            "--env",
            "OMP_NUM_THREADS=1",
            "--entrypoint",
            "/app/.venv/bin/python",
            args.image,
            "-c",
            software_code,
        )
    )
    require(observed == plan["basis"]["software"], "Image software differs from accepted lineage")
    immutable(
        args.state / "execution.json",
        {
            "plan_id": plan["plan_id"],
            "image_id": image["Id"],
            "cpus": args.cpus,
            "memory_gib": args.memory_gib,
            "seconds": args.seconds,
            "batch_counties": args.batch_counties,
            "code": str(args.code.resolve()),
            "inputs": str(args.inputs.resolve()),
            "artifacts": str(args.artifacts.resolve()),
        },
    )


def run(plan: Json, args: argparse.Namespace) -> None:
    args.state.mkdir(parents=True, exist_ok=True)
    with ownership(args.state):
        docker = Docker()
        preflight(plan, args, docker)
        stopped = False

        def shutdown(signum: int, frame: Any) -> None:
            nonlocal stopped
            stopped = True

        previous = {s: signal.signal(s, shutdown) for s in (signal.SIGINT, signal.SIGTERM)}
        started = time.monotonic()
        initial = status(plan, args.state)["new_completed"]
        try:
            while not stopped:
                if time.monotonic() - started >= args.max_duration:
                    stopped = True
                    break
                done = []
                for index in range(len(plan["workers"])):
                    if stopped or time.monotonic() - started >= args.max_duration:
                        stopped = True
                        break
                    done.append(tick(plan, args, index, docker))
                progress = status(plan, args.state)
                elapsed = time.monotonic() - started
                progress.update(
                    elapsed_seconds=elapsed,
                    new_counties_this_session=progress["new_completed"] - initial,
                    counties_per_hour=(progress["new_completed"] - initial)
                    * 3600
                    / max(elapsed, 1),
                )
                atomic_status(args.state / "progress.json", progress)
                print(json.dumps(progress), flush=True)
                if len(done) == len(plan["workers"]) and all(done):
                    return
                time.sleep(5)
        except Exception as exc:
            atomic_status(
                args.state / "progress.json",
                {
                    "plan_id": plan["plan_id"],
                    "state": "HALTED",
                    "reason": str(exc),
                    "observed_at": time.time(),
                    "elapsed_seconds": time.monotonic() - started,
                },
            )
            raise
        finally:
            stop_owned(plan, args.state, docker)
            for s, handler in previous.items():
                signal.signal(s, handler)
        raise ValueError("Supervisor stopped at signal or duration limit; checkpoints preserved")
