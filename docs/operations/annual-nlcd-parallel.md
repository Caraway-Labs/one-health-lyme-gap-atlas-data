# Offline national NLCD operator — DATA #594

This PR implements execution preparation. It does not authorize provisioning,
paid work, national execution, Snowflake access or publication. ADR 0046 is
proposed; #606 remains a separate scientific review. No formulas change here.

## Architecture and prerequisites

Linux host Python 3.11–3.13 plus Docker Engine and Git; no host scientific Python
dependencies. Run the operator from this repository with `PYTHONPATH=src`.
Use a separate clean scientific checkout at
`a1dca40aa049f5c8db4c819f20230843bc8041cf`. Code bytes, including line endings,
must match the audited identities. Keep historical inputs/results read-only at
the filesystem/volume level; grant write permission only to new plan/state paths.
Docker access is a privileged host capability; restrict it to the authorized
operator account. Do not expose the Docker socket to containers.

The operator must run as a non-root Linux user with a nonzero primary GID.
Every worker receives an explicit `--user <operator UID>:<operator GID>`;
the execution receipt pins these identities and adoption checks `Config.User`.
New result directories use mode 0750. Atomic calculator files retain their
0600 permissions and remain readable/writable by the same host operator.
Do not use root, `chmod 777`, privileged workers or a different resume account.
Inputs and the scientific checkout must be readable by that account.

Raw scientific file hashes are part of the accepted lineage. A plain Linux
checkout normalizes the retained Windows CRLF bytes and fails preflight.
Stage byte-preserving copies of the reviewed calculator, weight and geometry
files alongside the exact Git revision; keep Git line-ending configuration
consistent (`core.autocrlf=true`) and verify a clean status and the three raw
hashes before execution. Do not edit formulas or replace the expected hashes.

The seed runs are byte-pinned:

- National: `2cc8c5a6e1069945bce1c9e4a5fa0b51ac1043bac9cee58db568eea5930db1ba`.
- Reviewed proof: `12d3307d38bf247a467b03f42f48b4a3740fef66b30fcaa1b7ada31f926da499`.

The national run contributes 193 CONUS counties; the proof contributes
`06075,09110,46127,48081,51013`. Exclusion partitions are verified but never used
as numeric CONUS results. The old 2,426 uncorrected partitions are not seed input.

## Input staging (separate transfer authorization)

Preserve directory contents and bytes when staging:

```text
/srv/nlcd/artifacts/
  data594-weight-repair-results-national/
  data594-weight-repair-results-reviewed/
/srv/nlcd/inputs/
  verified-inputs.json
  mrlc-capture-receipt.json
  tl_2025_us_county.zip
  Annual_NLCD_{LndCov,FctImp,LndChg}_2025_CU_C1V2.{tif,xml}
  corresponding .tif.aux.xml files
/opt/nlcd-calculator/                 # clean exact #606 checkout
/opt/nlcd-operator/                   # this reviewed orchestration revision
/srv/nlcd/plans/                      # new owned immutable assignments
/srv/nlcd/state/                      # new owned writable checkpoints/receipts
```

Use a cached immutable image ID or repository digest resolving to the exact audited
Linux/amd64 image. Its required image ID is
`sha256:a1a2939b969fd2ec8ca78a973f921b95486f97a71b7ddfc4c4be4be1a6c3b6d7`.
Transport that exact image separately when authorized; the operator never pulls
and rejects rebuilt/substituted image IDs even if package version strings match.
It verifies image software against the original lineage with a short network-off
container, and rehashes all prepared inputs before launching workers.

Expected runtime: Python 3.12.15, NumPy 2.4.6, Rasterio 1.5.1, GDAL 3.12.4,
pyproj 3.8.0, Shapely 2.1.2. A rebuild with newer libraries is not equivalent.

## Freeze assignment

Proposal only until national execution is separately approved:

```bash
cd /opt/nlcd-operator
export PYTHONPATH="$PWD/src"
python3 -m lyme_gap_atlas_data.nlcd_parallel plan \
  --artifacts /srv/nlcd/artifacts \
  --accepted data594-weight-repair-results-national data594-weight-repair-results-reviewed \
  --workers 8 --plan /srv/nlcd/plans/national-8
```

Select `--workers 1`, `2`, `4` or `8` explicitly; no accidental eight-worker
default. Every county is assigned once. Default sorted round-robin shard sizes
are 364,364,364,364,364,364,364,363. Assignment files contain full county lists,
source/software identities, physical/payload hashes and content hashes. Repeating
the same plan is idempotent; conflicting existing files fail closed.

Optional `--timings measured-seconds.json` accepts a county-to-positive-seconds
mapping. Deterministic longest-first balancing uses worker index as tie-breaker
and the median supplied duration for unknown counties. Both measurements and
their hash are frozen. Never rebalance an existing plan during resume; unknown
geographies and first-county startup make historical estimates imperfect.

## Launch and monitor (requires execution approval)

```bash
python3 -m lyme_gap_atlas_data.nlcd_parallel run \
  --plan /srv/nlcd/plans/national-8 --artifacts /srv/nlcd/artifacts \
  --state /srv/nlcd/state/national-8 \
  --code /opt/nlcd-calculator --inputs /srv/nlcd/inputs \
  --image sha256:a1a2939b969fd2ec8ca78a973f921b95486f97a71b7ddfc4c4be4be1a6c3b6d7 \
  --cpus 1 --memory-gib 2 --batch-counties 8 --seconds 1800 \
  --max-duration 86400
```

On a 16-vCPU/32-GiB host, eight one-CPU/two-GiB limits leave CPU capacity and
memory for the host and page cache. Limits are ceilings, not reservations. The
operator requires an additional 2 GiB engine reserve. Do not assign many CPUs
to each mostly single-threaded calculator. Start benchmarks at 1/4 workers.

Inputs and code are mounted read-only; `/tmp` is a bounded 64 MiB tmpfs.
Network is disabled, capabilities dropped, root filesystem read-only, PIDs
bounded and swap disabled per container. No credentials are passed. Containers
have deterministic plan/worker/attempt names and ownership labels. Container
logs are capped at two 2 MiB files. Each worker has its own writable results,
lock, status and immutable attempt intent/result/log receipts.

`progress.json` and stdout report actual session elapsed time, committed county
counts and throughput. Attempt receipts retain actual container start/finish
times; they do not convert CPU quotas into measured CPU usage.

```bash
python3 -m lyme_gap_atlas_data.nlcd_parallel status \
  --plan /srv/nlcd/plans/national-8 --artifacts /srv/nlcd/artifacts \
  --state /srv/nlcd/state/national-8
docker ps -a --filter label=atlas.nlcd.plan=FULL_PLAN_HASH
```

Startup rehashes approximately 4.42 GB per invocation. Eight simultaneous starts
produce about 35 GB logical verification reads; caching may reduce physical I/O.
Watch disk latency, available RAM, CPU and county progress before increasing
concurrency. Small batches amplify startup overhead. Do not weaken verification
or raise the calculator's 1,800-second maximum to improve a benchmark.

## Recovery and shutdown

Run in the foreground under an owner-controlled terminal or service with
SIGTERM forwarding. `--max-duration` bounds each supervisor session (at most
seven days). SIGTERM/SIGINT stops new dispatch and stops only owned running
containers. Committed seven-row partitions survive; an unfinished county repeats.
No completion receipt is manufactured for an interrupted run.

Restart with the identical command and state. The kernel host lock prevents a
second supervisor. After a host-process crash, running containers are adopted,
not duplicated. After a VM reboot, a changed Linux boot ID and owned terminal
container provide interruption evidence. Interrupted attempts have a persistent
two-recovery ceiling. Unknown/missing containers, OOM, scientific tracebacks,
foreign ownership, changed prefixes, or conflicting assignments halt.

An empty calculator lock is archived only after the actual owned container is
terminal and its saved partitions/prefix pass validation. Nonempty locks require
manual diagnosis. Never delete a lock based only on heartbeat age.

An exit-124 timeout with valid new counties may be explicitly resumed using
`--retry-timeouts`; at most two such recoveries per worker are allowed. A
single-county/no-progress timeout halts. Scientific failures are never retried
automatically. Read the retained logs and diagnose the county/deadline before
any separately reviewed recovery. A created-but-not-started owned container can
be started on resume; an intent whose container is missing halts for diagnosis.

Stopped attempt containers are retained for evidence. There is no prune/cleanup
command. After export/reconciliation, remove only individually verified owned
containers through the normal operator procedure, under explicit cleanup scope.

## Reconcile

```bash
python3 -m lyme_gap_atlas_data.nlcd_parallel assemble \
  --plan /srv/nlcd/plans/national-8 --artifacts /srv/nlcd/artifacts \
  --state /srv/nlcd/state/national-8 --output /srv/nlcd/national-assembly.json
```

This revalidates original and new files. Acceptance requires exactly 3,109
distinct CONUS counties, seven distinct required measures each and 21,763 logical
observations, without duplicates or gaps. The immutable manifest references each
original run, lineage, file and payload hash. Original results remain in place.
Assembly does not register a governed source, change Snowflake or publish an API.

Export the plan, execution settings, assembly, all contributing lineages and
partitions, and operational receipts to approved durable storage. Verify hashes
and a separate readback before owner-approved VM teardown. Stopping the operator
does not stop VM billing; this code neither provisions nor destroys cloud hosts.

## Benchmark preparation

Create separate plans with `--benchmark --workers 1`, `4`, and `8`, separate
plan/state directories, and identical runtime limits. Do not mix benchmark
partitions into the production assignment. The fixed missing-county panel is:

| FIPS | Reason for inclusion |
| --- | --- |
| 06073 | Large coastal county; complex boundary |
| 08001 | Mixed urban/rural plains |
| 08031 | Small urban county |
| 12086 | Large coastal/wetland county |
| 30013 | Montana landscape and geographic diversity |
| 36061 | Small island/urban footprint |
| 48113 | Urban Texas county |
| 48201 | Large metropolitan county |
| 48301 | Small-population rural county; population is not a geometry cost proxy |
| 51107 | Smaller eastern county |
| 56013 | Large western county |

No benchmark is launched by `plan`. Separately authorize `run` with a short
`--max-duration`. Compare aggregate wall time, per-county progress deltas, input
validation/startup, CPU time/peak RSS from calculator reports, actual disk I/O,
retries and host headroom. Report cold/warm cache conditions without clearing
system caches automatically. Do not assume linear speedup or extrapolate this
small panel without geographic limitations. Benchmark scope cannot emit a
national assembly.

For the opt-in Linux Docker integration test, stage disposable copies of the
exact clean calculator and verified inputs under a fresh native Linux root
containing `code/` and `inputs/`. Keep historical sources read-only.
Run as the intended non-root operator with the cached audited image:

```bash
export NLCD_NATIVE_DOCKER_ROOT=/srv/nlcd/test-UNIQUE
export NLCD_NATIVE_BASIS=/srv/nlcd/artifacts/data594-weight-repair-results-national/mrlc2025_2cc8c5a6e1069945bce1c9e4a5fa0b51ac1043bac9cee58db568eea5930db1ba.lineage.json
PYTHONPATH=src pytest tests/test_nlcd_parallel.py -k linux_docker
```

The test runner `scripts/verify_nlcd_linux_identity.py` reproduces the original
root/cap-drop permission failure, then calculates only Arlington (51013) and
Falls Church (51610), with a 900-second invocation deadline and 1 CPU/2 GiB.
It audits the first commit as the non-root host, stops the second invocation,
resumes, checks unchanged committed hashes, and writes a verification receipt.
It removes only its owned worker containers and retains its new test evidence.
Windows bind mounts do not prove Linux permissions. A local Linux operator test
container may use a Docker socket to exercise native-volume permissions; that
test harness has Docker host authority. Calculation workers never receive it.

## Frozen terminal output inventories

Each non-failed terminal attempt publishes an immutable `attempt-NNNNN.inventory.json`
and records its physical SHA-256 in the attempt result. It binds the exact county
prefix, seven measures, source/calculation identities, original run/lineage,
physical partition hashes and payload hashes, and any actual completion receipt.
A full worker also publishes `completed.inventory.json`; full completion requires
the calculator's own valid receipt, including after an interruption between the
last partition and receipt. The operator never manufactures a scientific receipt.

Tick/restart, status and assembly validate the retained inventories. Assembly
also binds each completed inventory hash to an original terminal attempt and
records inventory hashes in its reference-only manifest. Cached legacy successes
without inventories fail closed; do not backfill inventories from unverified
current bytes or alter historical seeds. Diagnose and review any such state.

The auditor rechecks once only when a valid completion receipt appears after a
partition snapshot and a rescan proves the partition-file list changed. Stable
missing partitions, malformed receipts and other corruption fail closed.

## Invariant / evidence matrix

| Invariant | Enforcement / evidence |
| --- | --- |
| Corrected code unchanged | Exact separate checkout, clean Git status, calculator/weight/geometry SHA-256 |
| Real retained seeds | Exact two lineage pins, partition audits, frozen physical/payload references |
| No duplicate work | Accepted exclusion set, disjoint full assignment, explicit worker county argument |
| Isolation | Separate writable roots, read-only shared inputs, host lock and container ownership labels |
| Resume | Immutable assignments, prefix hash checks, bounded recovery, no stale-lock guessing |
| Scientific interpretation | Seven measures, original identities, finite/range/area/coverage/null checks |
| National completeness | Exact canonical set, 3,109 counties / 21,763 observations |
| No historical relabelling | Reference-only multi-run assembly, no original completion receipt writes |
| No automatic paid operations | Local CLI only; no cloud SDK, downloads, Snowflake or deployment workflow |

Offline unit/integration fixtures prove orchestration behavior, not national
scientific results. Source-backed Docker validation must be reported separately.

## Recover the owner-verified interrupted cloud run

The bounded `--recovery-root recovered-610148769` option admits only archive
`ef1defeaa9ba1f211d5f99b85abcec73a0edeec9bd187b801ced37e8b226409f`.
Stage `archive.tar.gz` and its byte-identical extracted `contents/` below that
relative artifacts root. Keep the two original seed roots at the artifacts root.
The old assignment and all original files are checked against the pinned archive;
all905 saved county prefixes and terminal inventories are revalidated read-only.
This is prefix admission, not adoption of destroyed Docker containers. The old
locks, assignments and interrupted attempt receipts remain historical evidence.
No scientific completion receipt is generated for an interrupted run.

`plan --workers 4 --recovery-root recovered-610148769` freezes1103 accepted
counties and exactly2006 remaining counties into a new immutable assignment.
The same `run`, resource limits, checkpoint rules and `assemble` commands apply.
Existing plans without this option retain their original198/2911 contract.
No scientific calculator file or formula changes.

Run the reviewed `nlcd_parallel run` directly as the non-root systemd service
process. Persist its complete stdout/stderr to an append-only supervisor log;
export the service journal, unit configuration, Docker creation/start/stop events,
filtered container inspection state, checkpoints, terminal inventories and cost
ledger every few minutes and before teardown. Run optional
`python -m lyme_gap_atlas_data.nlcd_parallel_monitor --root /srv/nlcd
--output /srv/nlcd/evidence/metrics.jsonl --max-duration 432000` separately.
Monitoring exceptions retain full tracebacks and never signal calculation workers.
Do not couple worker lifetime to a `docker stats` sampling subprocess. This is
hardening against a demonstrated failure mode, not an established explanation
of the prior wrapper exit1: its initiating traceback was not retained.
