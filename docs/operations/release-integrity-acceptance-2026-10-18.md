# Data 698 / 702 / 703 technical acceptance follow-up

Reviewed base: `0e244a628ab07f24fb75b0d302f00ae573b0e6cd`, PR #706 remains draft.
No migration installation, approval record, deployment or release pointer write
was performed in DEV or PROD during this follow-up.

## Review disposition

- Reviews at 5e2f6df and f160175: January inherited-environment conflict fixed;
  publish/rollback tests now apply the actual workflow step environment and real
  connection-parameter validation with authentication mocked. Timeout60 and
  queued-timeout10 persist, canary uses COMPUTE_WH and clears January flag.
- Correlated EXISTS under OR removed from Tier1, both situation views and
  activation selection. Admission identity relations use DISTINCT or grouped
  distinct model IDs; duplicate decisions cannot multiply prediction rows.
- Same-count county substitution now fails on release ID and exact canonical
  FIPS membership; pointer check also binds bundle. Every required source
  metadata row must have the correct release, source/dataset identifiers,
  label, vintage, URL and limitations. Missing/replaced rows fail before commit.
- Canary loads the actual admitted profile. Fixed Tier1 example counties were
  removed because they conflict with approved partial-coverage rollback.
  Zero and nonzero degraded-model coverage have regression tests; retained
  exception authorization remains mandatory.
- Full source lineage remains an acceptance gate, not satisfied by the existing
  18,864 matching predictor cells. V157 now additionally compares every model
  source observation's county/measure/time/source-version/run/artifact/record/
  row-hash tuple, with multiplicity, in both directions by state. Missing source
  mappings cannot pass as two empty sets. Read-only verifier also checks governed
  audit attribution and that audit rows equal all base observations.

## Actual execution evidence

Named DEV PAT context: MATTHEWCARAWAY / OH_LYME_DEV_READ /
ONE_HEALTH_LYME_GAP_ATLAS_DEV / OH_LYME_DEV_INGEST_XS_WH.
Read-only engine fixtures passed for exact, compatible, duplicate admission,
incompatible and deactivated/zero cases. See JSON query-ID receipts:

- `release-integrity-dev-sql-2026-10-18.json`: 15 SELECT executions over actual
  V158 view SELECTs and the shared Tier1 join builder; the original zero case
  deactivated surveillance only, leaving exact Tier1 eligible.
- `release-integrity-dev-activation-sql-2026-10-18.json`: five executions of
  the actual activation eligibility SELECT (no activation or procedure call).
- `release-integrity-dev-tier1-zero-sql-2026-10-18.json`: explicit empty Tier1 case.

These are Snowflake compilation/execution evidence over inline fixtures, not
installed V157/V158 procedure, transaction, concurrency or permission proof.
Both frozen ML138 fits validate offline: 3,144 rows each, probabilities/class
counts checked, county SHA256
`02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b`.
No model was refitted, relabelled or published.

Local Ruff, format, mypy and dbt parse passed. Targeted tests: 69 plus five
lineage-proof adversarial tests passed. Final hosted CI is authoritative for
full pytest, container and secret scanning; exact fix SHA/run recorded in PR.

## Inventory and production compatibility

The inventory covers human, tick, pathogen, SVI/population/geometry, RUCC,
bounded NLCD, January climate, Tier1 and both latent-class variants, plus both
independent intelligence feeds and indicator/measure/methodology metadata.
API reader source was checked against the view inventory. Source metadata pins
were refreshed through named PROD READ, without data/approval mutation.
Tests reject unchanged county counts with old release, replaced FIPS, empty
sources, replaced source keys, wrong source release and lost provenance.
Climate/NLCD measure/day/cohort checks and model distributions remain enforced.
This verifies inventory/gate implementation, not every live typed consumer.
Tier1 carry-forward is still NOT authorized. The two LCA variants retain the
exact frozen October15 input pair; any later release requires its own admission.

## Remaining access and human gates

V157 and V158 are absent from DEV's migration ledger. DEV currently points to
`governed-2026-10-09-january-climate-dev`, bundle
`67cdf470a8c39973251d8325777132a840f63ee42b67f129973936c30e66d9f4`,
which differs from frozen ML138. No pointer was moved to manufacture acceptance.
The protected workflow owns migration credentials; a personal DEV READ PAT
cannot install migrations, approve fixture authority or prove publisher denials.
An approved isolated DEV fixture/deployment with the frozen release identity is
required for installation, both fits, atomic activation/failure/concurrency,
replay, rollback and direct/inherited least-privilege checks. The existing
runbook specifies reviewed/merged deployment, while this task forbids merge;
a reviewed premerge isolation path/access decision is still needed.

Full lineage attempt is incomplete at retained source-manifest access.
PROD READ denies SEMANTIC_RELEASES, confirmed query
`01c7d1fa-030c-4eac-0064-2d07012cd572`; the bounded verifier also fails at
that prerequisite. Do not treat matching values or a sample as authorization.
No PROD OWNER/admin credential was used to bypass this boundary.

ADR0047 scientific/engineering/access-control review, Data publication owner
approval, Tier1 compatibility admission, exact release-completeness admission
and real API-service canary credential provisioning remain pending. No human
approval was recorded by the agent. PR #706 is not ready to leave draft.

Next: owner/security reviewers approve the isolated premerge DEV validation
path and retained-manifest read diagnostic. Complete those gates and review the
exact fix SHA before deciding draft readiness. Only afterward may separately
approved merge and protected digest-pinned PROD installation/publication proceed.

## Migration source checksums (normalized loader text; not applied receipts)

- V157: `96ea5c9ee51769e207efc44479d380fe6fd7752e5c6621dcbfd71559231593d1`
- V158: `104f3022133066f7b6888628ecae6e3632f70ddb0dda6a1d0a7babe969ba8cf5`
