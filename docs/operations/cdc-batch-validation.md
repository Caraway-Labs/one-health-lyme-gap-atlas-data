# CDC bounded batch validation — API #248

Baseline: `191df0820fc8ce24a3047ea3de9c9dad8160c461` (fetched main;
unchanged since investigation). Implementation branch/worktree:
`codex/data-cdc-batch-producer`,
`C:/codex_programming/worktrees/data-cdc-batch-producer`.
The original investigation branch/worktree/artifacts are preserved unchanged.

Scope: optional Data producer, typed internal contract, ADR, tests and benchmark
tooling only. No singleton/product source edits, API repository edits, migrations,
Snowflake object/grant/data changes, release/publication actions or deployment.
Stop before merge and production rollout.

## Measured evidence: October 17, 2026 America/Denver

The named PROD reader was verified as MATTHEWCARAWAY / OH_LYME_PROD_READ /
ONE_HEALTH_LYME_GAP_ATLAS_PROD / COMPUTE_WH, with secondary roles disabled.
Workload used only tick 01001/13081 and pathogen 06001/19135, exact October 15
release, source versions and the unchanged secure view. No cache manipulation,
retry, increased timeout, warehouse change or private payload file/log.

Eight initial SELECTs: identity, four singleton reads, two pair-batch reads and
one history lookup. The marker-based lookup returned no rows (comments were not
usable for correlation). One additional history-only SELECT recovered the six
workload query IDs using the exact recorded window. Benchmark tooling now uses
the execution window and closed query shapes, rejects incomplete/ambiguous
history and does not silently declare complete metrics after an empty lookup.

The final producer query uses a FIRST_VALUE window to select shared proof along
one CTE reference chain, rather than reading an anchor CTE again. Four additional
SELECTs validated the revised query: identity, one pair per measure, history.
**Total: 13 SELECTs, eight authority workload reads**, all bounded to at most two
specified counties per read. No further live SQL is required for this PR.

Original singleton reads and the initial batch returned field-for-field identical
complete consumer-safe observations for all four counties after unchanged Data
admission. The revised query also passed unchanged intended-reader, metadata,
physical/semantic membership, donor receipt and consumer-projection validators
for all four counties. The revised envelope has identical measured result size
to the initial batch; source/test review establishes the window rewrite's
all-row equality/cardinality behavior. This is live reader evidence and local
producer validation, not a deployed API/request-owned connector benchmark.

| Measure, two counties | Two singleton logical JSON results, bytes summed | Final batch logical JSON, bytes | Reduction |
|---|---:|---:|---:|
| scapularis_status | 4,490,690 | 2,305,667 | 48.66% |
| burgdorferi_status | 4,490,828 | 2,305,764 | 48.66% |

These are UTF-8 compact reserializations of the complete CLI JSON result,
including VARIANT string escaping, not compressed wire bytes. The investigation's
~1.667M-character value measured only the nested authority JSON, a different unit.
No restricted payload or source record was persisted. Final batch server
`bytes_written_to_result` was 731,311/731,424 respectively. Singleton counters
were zero in these samples, so those counters cannot quantify comparative
network/result-transfer bytes.

| Server metric, ms | Tick singleton 01001 | Tick singleton 13081 | Tick final pair batch | Pathogen singleton 06001 | Pathogen singleton 19135 | Pathogen final pair batch |
|---|---:|---:|---:|---:|---:|---:|
| Total elapsed | 740 | 205 | 7,794 | 700 | 230 | 5,647 |
| Compilation | 738 | 204 | 6,105 | 698 | 228 | 4,239 |
| Execution | 2 | 1 | 1,689 | 2 | 2 | 1,408 |
| Queued | 0 | 0 | 0 | 0 | 0 | 0 |

**No latency improvement is established.** New batch shapes compiled much more
slowly than the existing singleton shapes in these samples. There is one sample
per final shape, no controlled cold/warm comparison, and no proven cache labels.
Near-zero singleton execution/result-write counters are compatible with reuse,
but do not establish the exact cache mechanism. Secure-view scan bytes were zero;
hidden internals prevent interpreting them as physical zero scans/pruning.
CLI elapsed also includes fresh-session authentication/transport and must not
be substituted for server timing or HTTP latency. The window rewrite's compile
benefit is unproven; current evidence supports fewer statements and proof copies.

Final batch query IDs:

- Tick: `01c7cd53-030c-442e-0064-2d07012a67ba`, 2026-10-18 01:23:20.673Z.
- Pathogen: `01c7cd53-030c-442e-0064-2d07012a67c2`, 2026-10-18 01:23:53.622Z.

Safe raw metrics, query history, SQL fingerprints and receipts remain gitignored
at `artifacts/cdc-batch/production-comparison/` and
`artifacts/cdc-batch/window-query-comparison/` in the implementation worktree.
The opt-in reproduction tool is `scripts/benchmark_cdc_batch_readonly.py`;
another production execution requires its own bounded authorization, not an
automatic retry in CI. Regular tests do not call Snowflake.

## Execution model and scientific/security coverage

| Processed counties | Current authority SELECTs | Batch authority SELECTs | Current identity SELECTs | Batch identity SELECTs | Hypothetical integrated explicit total, current -> batch |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 1 | 1 | 1 | 5 -> 5 |
| 2 | 2 | 1 | 2 | 1 | 7 -> 5 |
| 5 | 5 | 1 | 5 | 1 | 13 -> 5 |
| 10 | 10 | 1 | 10 | 1 | 23 -> 5 |
| 50 | 50 | 1 | 50 | 1 | 103 -> 5 |

Only pairs were tested live; larger counts are offline/source-model evidence.
Totals include existing two session setup statements and one release lookup;
SDK implicit statements are excluded. One caller-owned connection remains.
Lookahead counts as processed work; no API pagination behavior changes here.

| Control | Evidence |
|---|---|
| Current/historical scientific parity | Both measures, Established/Reported/Present/No records, 1/2/5/10/50 counties; exact singleton output equality |
| Complete admission | Unchanged _metadata/_inputs/map_record/project_surveillance_evidence for every county |
| Immutable release/source/metadata | No edits to packaged bindings, revision chains, source versions or singleton code |
| Donor/receipt/record linkage | Negative donor equivalence/identity, invented receipt, changed record/revision/hash/workbook/source checks |
| All-or-nothing | Missing, duplicate, extra, mixed rows/identities and second-county failures reject whole batch |
| Shared proof consistency | One authority statement; exact all-row proof equality; NULL false; full proof retained once |
| Security/privacy | Exact reader/environment; only existing secure view; bound ASCII FIPS; private proof excluded from output/errors |
| Resource/failure behavior | 50-county bound, 8 MiB post-fetch envelope limit, sanitized driver failures, BaseException propagation |
| Release compatibility | Existing promotion gate untouched; existing full regression suite retained |

Focused final suite: **93 passed**, independently repeated before the equivalent
window rewrite; independent source review found no actionable scientific or
security defect and confirmed the rewrite's equivalence. Ruff/format, mypy for
144 source files, wheel/sdist and wheel metadata checks, dbt parse, Docker build,
container runtime help, packaged dbt parse and both documented dry-runs passed.
Exact final-head hosted Quality and independent review records accompany the PR;
they supersede provisional earlier-head CI. Local Windows full-suite evidence is
reported separately rather than substituted for hosted Linux acceptance.

## Owner decision and release boundary

This capability is ready for code/scientific/security review, not automatic API
integration or production acceptance. Remaining risks are compilation tails,
cache behavior and peak connector/SQL memory at larger bounds. Shared-evidence
transport is measured; a multi-county HTTP latency gain remains unmeasured.

After separately approved merge, API integration would pin the reviewed immutable
Data commit and borrow its existing exclusive request-owned connection, preserving
public filters/date/order/pagination/lookahead/errors. It requires a matched,
bounded API benchmark and scientific parity checks before protected production
acceptance. Do not change timeouts, grants or view definitions to force success.
Rollback remains the previous approved producer pin with unchanged singleton
behavior; historical evidence and release state are never rewritten.
