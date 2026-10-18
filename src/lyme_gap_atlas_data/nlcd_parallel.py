"""Offline NLCD assignment and reference assembly; never changes scientific files.

Runtime is deliberately separate from the calculator checkout pinned by #606.
Only the standard library is required on the Linux operator host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, cast

REVISION = "a1dca40aa049f5c8db4c819f20230843bc8041cf"
REFERENCE = "2cc8c5a6e1069945bce1c9e4a5fa0b51ac1043bac9cee58db568eea5930db1ba"
PROOF = "12d3307d38bf247a467b03f42f48b4a3740fef66b30fcaa1b7ada31f926da499"
# Content hashes of the audited reference inventories, including original file bytes.
SEED_INVENTORIES = (
    "4dd21c2dfa78907f9bcfe941a2b3b507f54a5ba3f99c84a16cc28e2590c913f2",
    "fe6e3f301cac77462be67c78fc70b1b2f4e9553c72e0f72e7effb4b1a17cb53b",
)
MEASURES = {
    "FOREST_AREA_SHARE",
    "DEVELOPED_AREA_SHARE",
    "AGRICULTURE_AREA_SHARE",
    "WETLAND_AREA_SHARE",
    "OPEN_WATER_AREA_SHARE",
    "MEAN_IMPERVIOUS_FRACTION",
    "LAND_COVER_CHANGED_AREA_SHARE",
}
SCIENCE_KEYS = (
    "input_manifest_sha256",
    "source",
    "tiger_sha256",
    "software",
    "calculation_code_sha256",
    "weight_code_sha256",
    "geometry_code_sha256",
    "transform",
    "code_revision",
    "grid",
    "scope",
)
BENCHMARK = [
    "06073",
    "08001",
    "08031",
    "12086",
    "30013",
    "36061",
    "48113",
    "48201",
    "48301",
    "51107",
    "56013",
]
Json = dict[str, Any]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"Regular file required: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Json:
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), f"JSON object required: {path}")
    return cast(Json, value)


def immutable(path: Path, value: Any) -> None:
    """Publish complete bytes without overwriting even a racing existing file."""
    content = canonical(value)
    if path.exists():
        require(path.read_bytes() == content, f"Immutable content differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".publish-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            require(path.read_bytes() == content, f"Immutable content differs: {path}")
    finally:
        temporary.unlink(missing_ok=True)


def contained(root: Path, relative: str) -> Path:
    path = root / relative
    require(
        not Path(relative).is_absolute() and ".." not in Path(relative).parts,
        "Relative artifact path required",
    )
    require(path.resolve().is_relative_to(root.resolve()), "Artifact escapes root")
    require(
        not any(p.is_symlink() for p in [path, *path.parents] if p != root.parent),
        "Symlink artifact paths are unsupported",
    )
    return path


def plain_path(path: Path) -> None:
    require(
        not any(p.is_symlink() for p in [path, *path.parents]),
        "Symlink paths cannot own scientific checkpoints",
    )


def fips_list(values: list[str]) -> list[str]:
    require(
        all(isinstance(f, str) and re.fullmatch(r"[0-9]{5}", f) for f in values),
        "Five ASCII digit county identifiers required",
    )
    require(values == sorted(set(values)), "Counties must be sorted and unique")
    return values


def identity(lineage: Json) -> Json:
    return {key: lineage[key] for key in SCIENCE_KEYS}


def finite(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def validate_rows(rows: list[Json], fips: str, lineage_id: str, basis: Json) -> None:
    require(
        len(rows) == 7 and {r["measure"] for r in rows} == MEASURES,
        "Exactly seven distinct NLCD measures required",
    )
    for row in rows:
        require(
            row["county_fips"] == fips and row["lineage_id"] == lineage_id,
            "County or lineage mismatch",
        )
        require(
            row["mapping_year"] == 2025
            and row["collection_version"] == "C1V2"
            and row["unit"] == "fraction"
            and row["denominator"] == "valid_source_supported_area_m2",
            "Year/product/unit/denominator mismatch",
        )
        require(
            row["transformation_version"] == basis["transform"]
            and row["geometry_version"] == "atlas-county-analysis-geometry/1"
            and row["weight_version"] == "atlas-grid-county-area-weight/1"
            and re.fullmatch(r"[a-f0-9]{64}", row["geometry_digest"]) is not None,
            "Geometry/weight/transformation identity mismatch",
        )
        fields = (
            "expected_area_m2",
            "intersected_area_m2",
            "source_supported_area_m2",
            "valid_area_m2",
            "source_coverage_fraction",
            "valid_fraction_of_supported_area",
        )
        if fips.startswith(("02", "15")):
            require(
                row["coverage_status"] == "OUT_OF_SOURCE_COVERAGE"
                and row["value"] is None
                and all(row[k] is None for k in fields)
                and row["native_class_area_m2"] == {},
                "Invalid exclusion record",
            )
            continue
        expected, intersected, supported, valid = (row[k] for k in fields[:4])
        require(
            all(finite(row[k]) and row[k] >= 0 for k in fields[:4]) and expected > 0, "Invalid area"
        )
        require(
            valid <= supported * (1 + 1e-8)
            and supported <= intersected * (1 + 1e-8)
            and intersected <= expected * (1 + 1e-8),
            "Area conservation failed",
        )
        require(
            finite(row["source_coverage_fraction"])
            and math.isclose(
                row["source_coverage_fraction"], supported / expected, rel_tol=1e-8, abs_tol=1e-12
            ),
            "Source coverage differs",
        )
        fraction = row["valid_fraction_of_supported_area"]
        status = row["coverage_status"]
        if supported == 0:
            require(
                status == "SOURCE_MISSING" and fraction is None and row["value"] is None,
                "Missing support must remain null",
            )
        else:
            require(
                finite(fraction)
                and math.isclose(fraction, valid / supported, rel_tol=1e-8, abs_tol=1e-12),
                "Valid fraction differs",
            )
            complete = fraction + 1e-12 >= 1
            require(
                status == ("COMPLETE" if complete else "PARTIAL_COVERAGE"),
                "Completeness state differs",
            )
            require(
                (finite(row["value"]) and 0 <= row["value"] <= 1)
                if complete
                else row["value"] is None,
                "Invalid numeric/null value",
            )
        classes = row["native_class_area_m2"]
        require(all(finite(v) and v >= 0 for v in classes.values()), "Invalid class area")
        if classes:
            require(
                math.isclose(math.fsum(classes.values()), valid, rel_tol=1e-8, abs_tol=1e-6),
                "Class areas differ from valid area",
            )
    require(len({r["geometry_digest"] for r in rows}) == 1, "Mixed county geometry")


class PublicationChanged(ValueError):
    """A valid marker appeared after the partition directory snapshot."""


class LineagePending(ValueError):
    """Only the calculator's initial, non-atomic lineage publication is pending."""


def audit_run(root: Path, basis: Json, selected: list[str] | None = None) -> list[Json]:
    """Retry once, exclusively for a demonstrated final-publication race."""
    try:
        return _audit_run(root, basis, selected)
    except PublicationChanged:
        return _audit_run(root, basis, selected)


def _audit_run(root: Path, basis: Json, selected: list[str] | None = None) -> list[Json]:
    """Validate saved partitions, not merely attempt receipts. No files are written."""
    plain_path(root)
    contexts = sorted(root.glob("*.lineage.json"))
    if not contexts:
        require(not list(root.rglob("*.json")), "Partitions without lineage")
        return []
    require(len(contexts) == 1, "One immutable run per output directory required")
    path = contexts[0]
    try:
        lineage = read_json(path)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        raise LineagePending("Initial lineage publication pending") from exc
    lineage_id = fingerprint(lineage)
    run = "mrlc2025_" + lineage_id
    require(
        path.name == run + ".lineage.json" and path.read_bytes() == canonical(lineage),
        "Lineage filename or bytes differ",
    )
    require(identity(lineage) == basis, "Unreviewed source/software/calculation identity")
    counties = fips_list(lineage["selected_counties"])
    if selected is not None:
        require(counties == selected, "Worker assignment differs from scientific lineage")
    refs = []
    paths = sorted((root / "partitions").glob("*.part-*.json"))
    for ordinal, part_path in enumerate(paths):
        part = read_json(part_path)
        rows = part["records"]
        require(
            ordinal < len(counties)
            and part["ordinal"] == ordinal
            and part_path.name == f"{run}.part-{ordinal:08d}.json",
            "Partition gap or foreign run",
        )
        require(
            part["sha256"] == fingerprint(rows) and part["byte_count"] == len(canonical(rows)),
            "Partition checksum differs",
        )
        validate_rows(rows, counties[ordinal], lineage_id, basis)
        refs.append(
            {
                "county_fips": counties[ordinal],
                "run_id": run,
                "lineage_sha256": file_hash(path),
                "lineage_path": path.name,
                "partition_path": str(part_path.relative_to(root)).replace("\\", "/"),
                "file_sha256": file_hash(part_path),
                "payload_sha256": part["sha256"],
                "rows": 7,
            }
        )
    markers = list((root / "partitions").glob("*partitions-complete.json"))
    for marker in markers:
        receipt = read_json(marker)
        require(
            marker.name == run + ".partitions-complete.json"
            and type(receipt.get("count")) is int
            and receipt == {"count": len(counties)},
            "Invalid completion receipt",
        )
        if len(refs) != len(counties):
            if paths != sorted((root / "partitions").glob("*.part-*.json")):
                raise PublicationChanged("Final partitions published during audit; re-audit once")
            raise ValueError("Invalid completion receipt: stable incomplete partitions")
    return refs


def output_inventory(plan: Json, root: Path, index: int, refs: list[Json]) -> Json:
    """Bind original bytes and identities, without rewriting scientific artifacts."""
    receipts = [
        {
            "path": p.relative_to(root).as_posix(),
            "file_sha256": file_hash(p),
            "receipt": read_json(p),
        }
        for p in sorted((root / "partitions").glob("*partitions-complete.json"))
    ]
    body = {
        "schema": "atlas-nlcd-output-inventory/1",
        "plan_id": plan["plan_id"],
        "worker": index,
        "selected_counties": plan["workers"][index],
        "basis": plan["basis"],
        "partitions": refs,
        "partition_count": len(refs),
        "measures": sorted(MEASURES),
        "observations": len(refs) * 7,
        "completion_receipts": receipts,
    }
    return {**body, "inventory_id": fingerprint(body)}


def verify_inventory(plan: Json, root: Path, index: int, path: Path, *, complete: bool) -> Json:
    require(path.is_file(), "Frozen output inventory missing; do not adopt legacy success")
    saved = read_json(path)
    refs = audit_run(root, plan["basis"], plan["workers"][index])
    count = saved["partition_count"]
    current = output_inventory(plan, root, index, refs[:count])
    # An interrupted prefix may subsequently gain the calculator's real marker.
    if not saved["completion_receipts"] and not complete:
        current["completion_receipts"] = []
        current["inventory_id"] = fingerprint(
            {k: v for k, v in current.items() if k != "inventory_id"}
        )
    require(current == saved, "Frozen output inventory changed")
    if complete:
        require(
            count == len(refs) == len(plan["workers"][index])
            and bool(saved["completion_receipts"]),
            "Completed inventory requires all counties and original completion receipt",
        )
        digest = file_hash(path)
        require(
            any(
                result.get("inventory_sha256") == digest
                and file_hash(root.parent / f"attempt-{result['attempt']:05d}.inventory.json")
                == digest
                for result in (read_json(p) for p in root.parent.glob("attempt-*.result.json"))
            ),
            "Completed inventory is not bound to an original terminal attempt",
        )
    return saved


def assign(
    counties: list[str], workers: int, timings: dict[str, float] | None = None
) -> list[list[str]]:
    fips_list(counties)
    require(workers in (1, 2, 4, 8), "Worker count must be 1, 2, 4 or 8")
    bins: list[list[str]] = [[] for _ in range(workers)]
    if timings is None:
        for index, county in enumerate(counties):
            bins[index % workers].append(county)
    else:
        require(
            set(timings) <= set(counties) and all(finite(v) and v > 0 for v in timings.values()),
            "Invalid measured timings",
        )
        fallback = sorted(timings.values())[len(timings) // 2] if timings else 1.0
        loads = [0.0] * workers
        for county in sorted(counties, key=lambda f: (-timings.get(f, fallback), f)):
            index = min(range(workers), key=lambda i: (loads[i], i))
            bins[index].append(county)
            loads[index] += timings.get(county, fallback)
    return [sorted(group) for group in bins]


def make_plan(
    artifacts: Path,
    names: list[str],
    workers: int,
    benchmark: bool = False,
    timings: dict[str, float] | None = None,
) -> Json:
    require(
        len(names) == len(set(names)) == 2, "Exactly national and reviewed proof roots required"
    )
    national = contained(artifacts, names[0])
    lineage_path = national / f"mrlc2025_{REFERENCE}.lineage.json"
    require(file_hash(lineage_path) == REFERENCE, "Exact audited national lineage required")
    lineage = read_json(lineage_path)
    require(lineage["code_revision"] == REVISION, "Corrected #606 revision required")
    basis = identity(lineage)
    universe = [
        f for f in fips_list(lineage["selected_counties"]) if not f.startswith(("02", "15"))
    ]
    require(
        len(universe) == 3109 and len(lineage["selected_counties"]) == 3144,
        "Frozen national county universe differs",
    )
    accepted = []
    seen: set[str] = set()
    for index, name in enumerate(names):
        root = contained(artifacts, name)
        refs = audit_run(root, basis)
        require(
            fingerprint(refs) == SEED_INVENTORIES[index], "Audited seed partition bytes changed"
        )
        expected_id = REFERENCE if index == 0 else PROOF
        require(
            all(r["run_id"] == "mrlc2025_" + expected_id for r in refs),
            "Only audited corrected national/proof runs may seed execution",
        )
        require(len(refs) == (223 if index == 0 else 7), "Audited accepted inventory changed")
        for ref in refs:
            if ref["county_fips"].startswith(("02", "15")):
                continue
            require(ref["county_fips"] not in seen, "Overlapping accepted counties")
            seen.add(ref["county_fips"])
            accepted.append({**ref, "origin": name})
    require(len(seen) == 198 and seen <= set(universe), "Expected 198 accepted CONUS counties")
    remaining = sorted(set(universe) - seen)
    if benchmark:
        remaining = sorted(set(remaining) & set(BENCHMARK))
    groups = assign(remaining, workers, timings)
    body = {
        "schema": "atlas-nlcd-assignment/1",
        "scope": "benchmark" if benchmark else "national",
        "basis": basis,
        "universe": universe,
        "accepted": sorted(accepted, key=lambda r: r["county_fips"]),
        "origins": names,
        "workers": groups,
        "remaining": remaining,
        "timings": timings,
        "timings_sha256": fingerprint(timings),
    }
    return {**body, "plan_id": fingerprint(body)}


def save_plan(directory: Path, plan: Json) -> None:
    immutable(directory / "assignment.json", plan)
    for index, counties in enumerate(plan["workers"]):
        immutable(
            directory / f"worker-{index:02d}.json",
            {
                "plan_id": plan["plan_id"],
                "worker": index,
                "counties": counties,
                "assignment_sha256": fingerprint(counties),
                "basis_sha256": fingerprint(plan["basis"]),
            },
        )


def load_plan(directory: Path) -> Json:
    plan = read_json(directory / "assignment.json")
    body = {k: v for k, v in plan.items() if k != "plan_id"}
    require(
        fingerprint(body) == plan["plan_id"] and plan["schema"] == "atlas-nlcd-assignment/1",
        "Assignment hash differs",
    )
    require(plan["basis"]["code_revision"] == REVISION, "Incorrect scientific revision")
    require(len(plan["workers"]) in (1, 2, 4, 8), "Invalid worker count")
    remaining = fips_list(plan["remaining"])
    flat = [f for group in plan["workers"] for f in fips_list(group)]
    require(
        len(flat) == len(set(flat)) and sorted(flat) == remaining, "Overlapping/missing assignments"
    )
    accepted = [r["county_fips"] for r in plan["accepted"]]
    require(len(accepted) == len(set(accepted)) == 198, "Accepted inventory differs")
    target = sorted(set(plan["universe"]) - set(accepted))
    if plan["scope"] == "benchmark":
        target = sorted(set(target) & set(BENCHMARK))
    else:
        require(plan["scope"] == "national" and len(target) == 2911, "National scope differs")
    require(remaining == target and not set(accepted) & set(remaining), "Selection differs")
    for index, group in enumerate(plan["workers"]):
        require(
            read_json(directory / f"worker-{index:02d}.json")
            == {
                "plan_id": plan["plan_id"],
                "worker": index,
                "counties": group,
                "assignment_sha256": fingerprint(group),
                "basis_sha256": fingerprint(plan["basis"]),
            },
            "Frozen worker manifest differs",
        )
    return plan


def verify_accepted(plan: Json, artifacts: Path) -> None:
    refs: list[Json] = []
    for index, name in enumerate(plan["origins"]):
        root = contained(artifacts, name)
        expected = REFERENCE if index == 0 else PROOF
        context = root / f"mrlc2025_{expected}.lineage.json"
        require(
            file_hash(context) == expected and identity(read_json(context)) == plan["basis"],
            "Seed scientific lineage differs from audited identity",
        )
        if index == 0:
            require(
                plan["universe"]
                == [
                    f
                    for f in read_json(context)["selected_counties"]
                    if not f.startswith(("02", "15"))
                ],
                "Frozen canonical universe differs",
            )
        saved = audit_run(root, plan["basis"])
        require(
            fingerprint(saved) == SEED_INVENTORIES[index], "Audited seed partition bytes changed"
        )
        refs.extend(
            {**r, "origin": name} for r in saved if not r["county_fips"].startswith(("02", "15"))
        )
    require(
        sorted(refs, key=lambda r: r["county_fips"]) == plan["accepted"],
        "Accepted scientific artifacts changed",
    )


def assembly(plan: Json, artifacts: Path, state: Path) -> Json:
    verify_accepted(plan, artifacts)
    require(plan["scope"] == "national", "Benchmark cannot produce a national assembly")
    refs = [{**r, "kind": "accepted"} for r in plan["accepted"]]
    inventories = []
    for index, selected in enumerate(plan["workers"]):
        root = state / f"worker-{index:02d}" / "results"
        verify_inventory(plan, root, index, root.parent / "completed.inventory.json", complete=True)
        inventories.append(
            {"worker": index, "file_sha256": file_hash(root.parent / "completed.inventory.json")}
        )
        refs.extend(
            {**r, "origin": f"worker-{index:02d}/results", "kind": "worker"}
            for r in audit_run(root, plan["basis"], selected)
        )
    validate_union(refs, plan["universe"])
    body = {
        "schema": "atlas-nlcd-national-assembly/1",
        "assignment_sha256": plan["plan_id"],
        "scope": "LOCAL_CALCULATION_ONLY_NOT_GOVERNED_SOURCE_ADMISSION",
        "basis": plan["basis"],
        "counties": 3109,
        "observations": 21763,
        "exclusions": {"02": "OUT_OF_SOURCE_COVERAGE", "15": "OUT_OF_SOURCE_COVERAGE"},
        "runs": sorted({r["run_id"] for r in refs}),
        "worker_inventories": inventories,
        "partitions": sorted(refs, key=lambda r: r["county_fips"]),
    }
    return {**body, "assembly_id": fingerprint(body)}


def validate_union(refs: list[Json], universe: list[str]) -> None:
    counties = [r["county_fips"] for r in refs]
    require(
        len(counties) == len(set(counties)) == 3109
        and sorted(counties) == universe
        and all(r["rows"] == 7 for r in refs),
        "National assembly has missing/duplicate counties or incorrect observation counts",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--artifacts", type=Path, required=True)
    plan.add_argument("--accepted", nargs=2, required=True, metavar=("NATIONAL", "PROOF"))
    plan.add_argument("--workers", type=int, choices=(1, 2, 4, 8), required=True)
    plan.add_argument("--plan", type=Path, required=True)
    plan.add_argument("--benchmark", action="store_true")
    plan.add_argument("--timings", type=Path)
    for name in ("run", "status", "assemble"):
        item = sub.add_parser(name)
        item.add_argument("--plan", type=Path, required=True)
        item.add_argument("--artifacts", type=Path, required=True)
        item.add_argument("--state", type=Path, required=True)
        if name == "run":
            item.add_argument("--code", type=Path, required=True)
            item.add_argument("--inputs", type=Path, required=True)
            item.add_argument("--image", required=True)
            item.add_argument("--cpus", type=float, default=1)
            item.add_argument("--memory-gib", type=int, default=2)
            item.add_argument("--batch-counties", type=int, default=8)
            item.add_argument("--seconds", type=int, default=1800)
            item.add_argument("--max-duration", type=int, required=True)
            item.add_argument("--retry-timeouts", action="store_true")
        if name == "assemble":
            item.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        document = make_plan(
            args.artifacts,
            args.accepted,
            args.workers,
            args.benchmark,
            read_json(args.timings) if args.timings else None,
        )
        save_plan(args.plan, document)
        print(json.dumps({"plan_id": document["plan_id"], "remaining": len(document["remaining"])}))
    else:
        document = load_plan(args.plan)
        if args.command == "assemble":
            result = assembly(document, args.artifacts, args.state)
            immutable(args.output, result)
            print(json.dumps({"assembly_id": result["assembly_id"], "observations": 21763}))
        else:
            from .nlcd_parallel_runtime import run, status

            if args.command == "run":
                run(document, args)
            else:
                verify_accepted(document, args.artifacts)
                print(json.dumps(status(document, args.state)))


if __name__ == "__main__":
    main()
