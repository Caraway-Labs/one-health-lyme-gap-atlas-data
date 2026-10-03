# DATA199 current residual acceptance audit

Status: implementation delivered; runtime acceptance remains **BLOCKED**.
This audit supplements, and does not supersede, the
[2026-10-02 field matrix](story-199-svi-reconciliation-2026-10-02.md).
Issue #199 was read on 2026-10-03 with no comments. PR #557 is already merged;
PR #560 supplies the merged SVI/RUCC compatibility fixtures. No duplicate loader,
field expansion, metadata admission, release, source run or deployment is proposed.

## Baseline and isolation

Fetched `origin/main` at `aab1041567e005e772c29b76ce48b4f7b3c48dc9`.
Local branch `codex/data199-residual-audit-20261003` uses its own worktree under
`task-9/data199`, backed by an independent clone under `task-9/repository`.
Existing worktrees and open PRs were inspected before changes. DATA200's RUCC
contract and shared #202 tests are consumed read-only; no DATA200/shared tests,
worktree, source definition, runtime code, migration or release slot is changed.
The parent coordinates the parallel DATA200 lane.

Authorities read: repository `AGENTS.md`, agent-context index, source-onboarding
and release-readiness skills/reference indexes, ADR 0027, ingestion operating
model/interface freeze, connection inventory, and #190-#195 contracts. The
isolated checkout has no assembled workspace `TECHNOLOGY_AND_GOVERNANCE.md`
or workspace ADR 0005. Repository context validation passes; workspace-context
validation is not claimed. This evidence-only change does not modify pipeline,
source, DDL or deployment files that require that workspace policy.

## Delivered versus residual gap

The selected scope and existing semantic identities remain frozen:

| Publisher field | Existing measure | Unit / reference | Current evidence / residual |
| --- | --- | --- | --- |
| `E_TOTPOP` | `population_2022` | People; county population estimate | Delivered; DEV reports people and ACS period. Not the uninsured percentage denominator. Separate #192 adapter remains deferred. |
| `RPL_THEMES` | `svi_percentile_2022` | 0-1 percentile; national county reference | Delivered; existing #192 SVI mapper, v2 numeric boundary and period guard retained. Live reviewed state admission unverified. |
| `EP_UNINSUR` | `uninsured_percent_2022` | 0-100 percent; civilian noninstitutionalized population | Delivered; DEV reports percent. Consumer denominator is null; documented source meaning must not be inferred from that null. Separate #192 adapter deferred. |
| `EPL_UNINSUR` | `uninsured_percentile_2022` | 0-1 percentile ranking of uninsured percentage | Delivered; DEV reports percentile. Separate #192 adapter deferred. |
| `STCNTY`, publisher labels, geometry | County identity and display projection | Exact five-character FIPS; publisher display boundary | Existing scope preserved. Current uniqueness/domain checks pass; geometry-type check is not topology proof. |
| Other factors/themes, MOEs, flags, tract/state rankings, other vintages | No accepted projection | Not established for this scope | Deferred, as in the prior matrix; no new uncertainty, scientific eligibility or ML admission. |

The [CDC/ATSDR SVI 2022 documentation](https://www.atsdr.cdc.gov/place-health/media/pdfs/2024/10/SVI2022Documentation.pdf)
was re-read on 2026-10-03: pp. 2-5, 7, 10 and 12 support the retained
ACS 2018-2022 period, national ranking reference, percentile domain,
population/insurance distinction, and `-999` unavailable-data sentinel.
The existing v2 projection keeps original RAW values, emits null/MISSING for
sentinel/empty/null input, preserves ZERO, and rejects invalid domains.
This audit makes no source interpretation change or historical rewrite.

## Actual governed read-only evidence

Identity queries ran first using named connections; no role override,
interactive login, grants or credentials were changed. Effective roles and
databases were `OH_LYME_DEV_READ` / `ONE_HEALTH_LYME_GAP_ATLAS_DEV` at
05:04:02 UTC and `OH_LYME_PROD_RUNTIME` /
`ONE_HEALTH_LYME_GAP_ATLAS_PROD` at 05:07:30 UTC on 2026-10-03.
Warehouses were the respective `OH_LYME_DEV_INGEST_XS_WH` and
`OH_LYME_PROD_INGEST_XS_WH`. Only bounded SELECTs followed.

| Read-only check | DEV | PROD |
| --- | --- | --- |
| Current release | `governed-2026-09-17-unknown-coverage` | `governed-2026-09-18-unknown-coverage` |
| County rows / unique FIPS | 3,144 / 3,144 | 3,144 / 3,144 |
| Malformed FIPS, negative population, invalid SVI/uninsured rank/percent | All zero | All zero |
| Missing overall SVI | 0 | 0 |
| Missing population / uninsured percentile / uninsured percentage | Not queried in this session | 0 / 0 / 0 |
| Rows carrying selected-field `-999` | Covered by negative-value/domain checks | Explicit count 0 |
| Invalid geometry type | Not queried in this session | 0 |
| All-release observations / missing lineage ID count | Not queried in this session | 44,016 / 0, via status view |
| Source label, fixed vintage, contextual/noncausal/nonindividual note | Retained | Retained |
| Four measure units and ACS period | Confirmed | Metadata view denied |
| Exact SVI source/version/run/artifact table visibility | Denied `002003` | Denied `002003` |

Observed bundle hashes:

- DEV: `55192e53b0b046cfe5148c13ffe5c570f615ec233e2b5c1103247f00b1a51233`.
- PROD: `038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026`.

These bind the observed current release identity. They are not recomputed hashes
of retained artifacts, proof that the two environments are identical, or proof
of unchanged values relative to an unavailable prior value-level fingerprint.
This change performs no release write. The existing PROD 3,144/44,016 audit
counts were reproduced, separately from fixture evidence.

DEV `CURRENT_MEASURE_METADATA_V` returns `denominator = null` for all four
measures. V123 explicitly projects a null denominator; the field is not evidence
of a reviewed #191 denominator envelope. It also does not expose a #191 revision,
meaning signature, allowed-state list or steward review. PROD access to this view
returned `002003`; that means absent-or-not-authorized, not proven absent.
`CURRENT_SOURCE_METADATA_V` exposes label/vintage/note, not exact source tuple.
The source tuple in the existing YAML/matrix is static contract evidence only.

Both roles were denied direct `SEMANTIC_DATA_SOURCES` access. Consequently no
claim is made about exact source-version/run/artifact/checksum authority joins,
record hashes, reviewed metadata admission or source-backed v2 replay. Zero
missing lineage IDs in a status aggregate proves presence only. County count and
FIPS syntax/uniqueness do not prove canonical county-set equality or cross-source
record alignment; those runtime joins remain unverified. A multi-statement
CLI batch stops after a denied statement; later statements were not counted as
executed. Source metadata and missingness were subsequently queried separately.
The [SQL audit companion](story-199-svi-audit-2026-10-03.sql) records reproducible
SELECTs and these visibility boundaries; execute each separately.

## Fixture verification and remaining acceptance gates

Current-head existing SVI/mapping/#202/metadata/lineage/governance/release suites:
**289 passed**. These exercise sentinel and invalid percentile behavior, exact
FIPS alignment, duplicates, incompatible vintages/periods, original RAW/lineage
preservation, and negative metadata admission. They do not constitute live
source replay. The synthetic state metadata stays PENDING; the original fixture
and live admission are not widened. Repository context, ruff check and format
check passed. Additional full verification is recorded in the PR/handoff.

Before #199 can close, an authorized audit owner must supply an artifact-bound
authority snapshot under existing permissions, or record the specific denied
objects. Reuse #193 validators for exact source/resource/version, run, artifact
SHA-256, source record/hash and release membership. Supply the actual reviewed
#191 metadata revision, semantic version/meaning signature, denominator/reference
and allowed states; confirm MISSING/ZERO admission without changing old metadata.
Then establish intended-role source-backed acceptance of the merged v2 boundary.
If a meaning/state-policy change is necessary, it requires an explicitly reviewed
new version. If historical sentinel values are discovered, preserve the old
release and reconcile through an explicitly approved immutable new release.

No grant expansion or alternate privileged connection is justified to remove
this audit limitation. No reingestion, publication, PROD mutation, release-pointer
move, ML admission, score change, paid batch or Web change occurred. #199 stays
open; clean consumer values and passing fixtures do not close its runtime gates.
