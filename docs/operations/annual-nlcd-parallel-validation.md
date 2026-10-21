# DATA #594 parallel operator validation

Implementation baseline: Data `main` at
`70035167a3924415731c497f7557964c34cd5830`.
Scientific dependency: separate draft #606 checkout at
`a1dca40aa049f5c8db4c819f20230843bc8041cf` (not merged or modified).

## Retained evidence audit

The real retained national and reviewed proof runs passed the new read-only
partition audits. They contribute 198 distinct CONUS counties. All source input
and geometry identities are the existing pinned science identities; no source
or checkpoint was regenerated for assignment validation.

Reference-inventory SHA-256 includes original physical file hashes, payload
hashes, county/run identities and relative paths. Production planning pins:

| Run | Reference inventory SHA-256 |
| --- | --- |
| National (223 including exclusions) | `4dd21c2dfa78907f9bcfe941a2b3b507f54a5ba3f99c84a16cc28e2590c913f2` |
| Reviewed proof (7 including exclusions) | `fe6e3f301cac77462be67c78fc70b1b2f4e9553c72e0f72e7effb4b1a17cb53b` |

The seed pins prevent a changed value with a newly calculated checksum from
being accepted as the audited historical result. Fixture tests replace these
pins explicitly within the test process; production CLI has no fixture bypass.

Actual plan generation and load/resume validation produced:

| Workers | Remaining assignment sizes | Plan ID |
| --- | --- | --- |
| 1 | 2911 | `9a2cf6d65a94d67c572d7194e1ee15a9c2f7143f34d18e5e188c96fad9e471e5` |
| 2 | 1456,1455 | `bd56651351dc0a8b5da8bbcf83cdcd04474d0caebe15932c3d0ba8dd34950f5d` |
| 4 | 728,728,728,727 | `6e10f38c4cad1e92002132c5512b488b375e036f2a339c3b9ae94f1007f95f90` |
| 8 | 364,364,364,364,364,364,364,363 | `2110f75530893f6cc3252685a8d2c0d460e2471a2ec15ae8edb66765b2ae4dec` |

These plan IDs use the original retained directory names documented in the
runbook. Using different logical origin names legitimately changes the plan ID.
Generated private manifests remain outside Git.

## Verification boundaries

- Offline tests exercise deterministic assignment, mixed-run assembly, immutable
  publication, physical/payload preservation, worker ownership/isolation,
  graceful/reboot interruption, stopped-lock reconciliation, scientific failure,
  no-progress timeout, bounded progress-timeout recovery, and stale monitoring.
- The opt-in source-backed Docker test uses the cached image and one temporary
  Arlington (51013) run, never the national output directory. It removes only its
  uniquely labelled test container.
- An initial 180-second/0.5-CPU source-backed test reached its deadline without
  committing a county; the supervisor halted with exit 124 and did not retry.
  The controlled proof test uses the existing wrapper's 900-second default and
  one CPU. The calculator's 1,800-second maximum is unchanged.
- The 900-second proof passed (one temporary Arlington county; 262.95 seconds
  pytest wall time). Its test-owned container was removed. The final output-mount
  ownership check was also exercised against the real Docker container metadata.
- A repeat using a long workspace-local Windows test path failed at the Windows
  file-path limit. Use a short `--basetemp` (for example a new directory under
  `C:\temp`) for retained-input Windows Docker tests. Linux execution is the
  supported deployment target. Monitoring now also reports partially published
  initial lineage as `SNAPSHOT_PENDING`; terminal/assembly audits remain strict.
- Repository lint/format pass. The new modules pass strict mypy locally. A reused
  Windows development environment lacks Shapely typing stubs for pre-existing
  modules; that full typing attempt is not claimed passed.
- A Windows full pytest attempt was stopped at 7% without a reported failure
  because it competed with another active repository job and the bounded Docker
  proof. Exact-commit hosted Linux quality is the full-suite/build/dbt authority.
- Native Windows `dbt parse --no-partial-parse` passed without Snowflake queries.
- Initial commit `e9c6b5016d5e5d2491784e0b9993e2fcad447c11` passed hosted Quality
  run `39088950582`: 4,516 tests passed / two skipped, full strict typing,
  lint/format, dbt parse, Docker build/packaged runtime, both dry runs and secret
  scanning. Final review adds ownership/symlink/runtime-image regression checks;
  the PR check must pass again at the final reviewed head.
- No multi-worker source-backed benchmark, VM provisioning, transfer, national
  execution, Snowflake operation, deployment or scientific admission is claimed.

See the PR's exact-commit CI result for the final full-suite and packaged runtime
checks. Successful offline fixtures do not establish eight-worker cloud capacity.
