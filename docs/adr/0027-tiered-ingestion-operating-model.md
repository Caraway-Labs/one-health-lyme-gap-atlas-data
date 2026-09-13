# 0027: Tiered Ingestion Operating Model (Epic #223 / Story #224)

Status: Accepted
Date: 2026-09-13
Decision owner: One Health Lyme Gap Atlas product and engineering leads
Parent: Epic #223 — Simplify Atlas ingestion pipelines

## Context

ADR 0005 made Snowflake Streamlit the mandatory human-review gate before full
source-data acquisition. That gate protects real licensing, semantic, and
production-release concerns, but it also forced routine DEV public-source work
through steward clicks, source-specific allowlist migrations, and per-source
Actions recovery paths. Epic #223 requires a fast Tier A/B path without building
a second permanent governance system.

## Decision

Adopt risk-tiered governance for tabular and literature ingestion:

| Tier | Scope | Gate |
|---|---|---|
| **A — Local/fixture** | No external writes; fixtures/mocks only | Automated schema/config checks only |
| **B — DEV public source** | Routine public sources with a committed `SourceDefinition` fitting an existing adapter | Deterministic automated policy, provenance, schema, and technical quality checks. **No human approval solely to advance technical stages.** |
| **C — PROD publication/promotion** | PROD writes, digest promotion, public-facing publication | Protected GitHub Environment + explicit release controls (ADR 0006). Streamlit/steward review remains where product requires publication judgment. |
| **D — Exceptional/restricted** | First-time novel source classes, restricted/licensed data, licensing ambiguity, security exceptions | Human steward review before full acquisition or graph publication |

Default rule: **deterministic checks replace human approval** unless the decision
is genuinely semantic, licensing/policy, security, or production-release related.

Golden-path sources for this epic:

- Tier B reference: `cdc_lyme_x5j9_wybp` (Socrata)
- Second adapter proof: `cdc_tick_ixodes_county_status` (HTTP XLSX)

### Controls removed or automated from the Tier A/B happy path

Removed from routine Tier A/B (no longer required to advance technical state):

1. Streamlit steward click between evidence capture and DEV full acquire/load for
   an already-defined routine public source.
2. New source-specific GitHub Actions workflow YAML for capture/ingest/recover.
3. New source-specific Snowflake role or orchestration-only owner procedure.
4. Per-source allowlist rewrite of `SP_RECORD_SOURCE_REVIEW_DECISION` /
   `V_SOURCE_APPROVAL_*` solely to permit a routine public Tier B run.
5. Manual App Platform topology edits for a bounded one-source DEV smoke.

Automated (remain required, but machine-enforced):

- SourceDefinition schema validation
- Adapter/auth mode compatibility
- Provenance/lineage field presence
- Artifact checksum recording
- Declared technical quality rules
- Environment isolation (DEV credentials only for Tier B)
- Safe defaults preventing accidental PROD writes from local/Tier A paths

### Controls retained

- Immutable Spaces artifacts and append-only governance ledgers
- Secret handling (no secrets in `NEXT_PUBLIC_*`, logs, fixtures, or GitHub)
- Environment isolation and digest-identical DEV→PROD promotion (ADR 0006)
- Pipeline runtime role **never** records steward approvals
- Tier C protected PROD promotion workflows
- Tier D human review for restricted/licensed/exceptional sources
- Literature: human review for genuine semantic publication decisions;
  licensing ambiguity routes to an explicit exception state

This ADR **amends** workspace ADR 0005: Streamlit remains the approval console
for Tier D and for publication judgments that product still requires, but it is
no longer the mandatory stage-gate for every Tier B technical transition.

## Happy-path sequence (Tier B DEV public source)

```text
Developer/agent
  -> source init/validate (Tier A local)
  -> source run --tier B (orchestrator)
  -> automated policy/schema/provenance checks
  -> ACQUIRE -> VALIDATE -> NORMALIZE -> LOAD -> QUALITY -> STAGE
  -> runs inspect / resume on failure
  -> (optional later) Tier C promote via protected workflow
```

## Exception-path sequence (Tier D)

```text
Novel/restricted/ambiguous source
  -> evidence/assessment capture
  -> Streamlit steward decision (APPROVED / REJECTED / DEFERRED / EXCEPTION)
  -> only after approval: orchestrator full acquire
  -> licensing ambiguity remains EXCEPTION without blocking unrelated sources
```

## Consequences

- Stories #225/#226/#228 may implement the golden path without further
  governance discovery.
- Catalog-to-Snowflake contracts must reflect Tier B automation.
- Net platform surface area must decrease for migrated sources (epic #232).

## Non-goals

- Inventorying every historical control before coding
- A generic policy engine or governance DSL
- Removing PROD protection or immutable provenance

## Links

- Epic #223, Story #224
- Workspace ADR 0005 (amended by this decision)
- Workspace ADR 0006
- `docs/contracts/catalog-to-snowflake/implementation-decisions.md`
- `docs/contracts/catalog-to-snowflake/streamlit-snowflake-approval-app-requirements.md`
- `docs/contracts/simplified-ingestion/operating-model.md`
