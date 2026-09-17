# 0030: Snowflake Role Model Simplification (Epic #294 / Story #296)

Status: Accepted
Date: 2026-09-16
Decision owner: One Health Lyme Gap Atlas product and engineering leads
Parent: Epic #294 — Reduce Snowflake role sprawl and ingestion governance overhead

## Context

Story #295 produced a read-only, evidence-based inventory of every Snowflake
role in DEV and PROD
(`docs/operations/role-inventory-dev.md`, `docs/operations/role-inventory-prod.md`,
`docs/operations/role-classification.md`) and of the 12 named `snow` CLI
connections required to operate them (`docs/operations/connection-inventory.md`).

22 custom roles exist today (11 DEV, 9 PROD), not counting the 2 legacy Alpha
POC roles, which are out of scope for this decision. Of those 22:

- 11 are active and load-bearing, each protecting a named control from
  workspace `AGENTS.md`, data-repo `AGENTS.md`, ADR 0005, ADR 0006, or ADR 0027.
- 3 (`API_RUNTIME` x2, `PROD_KG_PAPER_REVIEW_OWNER`) are dormant with zero
  current holders but are legitimately reserved for not-yet-completed work
  (Epic #252 story #275's API cutover; PROD literature activation).
- 2 (`SECURITY_ADMIN` x2) exist only as an undocumented indirection — their
  entire purpose is letting the migration deployer assume `STREAMLIT_OWNER`,
  something a single direct `GRANT` could achieve without a dedicated role.
- 4 (`DATA_STEWARD` x2, `APPROVAL_VIEWER` x2) are unused duplicates: identical
  grants to each other, zero references anywhere in the git-tracked repo, and
  at most one accidental human holder.

The product owner has stated that Snowflake role complexity is impeding
development velocity on core-product ingestion (multi-day ingestion builds)
and requested a single Dev role and single Prod role that can do everything.
Workspace `TECHNOLOGY_AND_GOVERNANCE.md` requires human owner review and an
ADR for access-control changes, and both `AGENTS.md` files require explicit
authorization for privilege changes. This ADR exists to make that review
concrete: it presents the requested two-role model side by side with a
smaller consolidation that keeps today's separation-of-duties controls, and
records which named controls each option keeps, merges, or drops.

## Decision drivers carried unchanged from ADR 0005 / ADR 0027 / `AGENTS.md`

1. **"Pipeline runtime role must never approve candidates"** — the scheduled
   ingestion identity must never be able to call an approval/steward-decision
   procedure.
2. **Owner-rights procedures separated from runtime** — objects that require
   a human or migration-deploy identity to own (Streamlit apps, budget
   procedures, governed views) must not be owned or directly writable by the
   routine scheduled runtime.
3. **DEV/PROD independence** (ADR 0006) — DEV and PROD roles, credentials,
   and warehouses remain fully separate regardless of how many roles exist
   within each environment.
4. **Migration/deployment identity distinct from the routine runtime** — the
   credential that runs forward-only schema DDL is not the same credential
   that runs on every scheduled ingestion tick.

## No-regret cleanup (applies under either option, executed in Story #297/#298)

Regardless of which option below is accepted:

- Drop `OH_LYME_{DEV,PROD}_DATA_STEWARD` and `OH_LYME_{DEV,PROD}_APPROVAL_VIEWER`
  (4 roles) — unused duplicates, zero git references, protect no named control.
- Replace `OH_LYME_{DEV,PROD}_SECURITY_ADMIN` (2 roles) with a direct
  `GRANT USAGE ON ROLE OH_LYME_{ENV}_STREAMLIT_OWNER TO ROLE
  OH_LYME_{ENV}_MIGRATION_DEPLOYER`.
- Leave `OH_LYME_{DEV,PROD}_API_RUNTIME` and `OH_LYME_PROD_KG_PAPER_REVIEW_OWNER`
  untouched until Epic #252 stories #275 (API cutover) and the PROD literature
  activation resolve their status — they are reserved, not sprawl.

This alone takes 22 custom roles to 16 with zero functional risk.

## Option A — True two-role model (`OH_LYME_{ENV}_ALL`)

One role per environment holding every remaining privilege (everything
currently on `PIPELINE_RUNTIME`, `STREAMLIT_OWNER`, `GOVERNED_VIEW_OWNER`,
`KG_PAPER_REVIEW_OWNER`, `KG_LLM_BUDGET_OWNER`, `PMC_AUDITOR`, and
`MIGRATION_DEPLOYER` for that environment), directly matching the product
owner's original request.

**Controls this drops, named explicitly:**

1. Runtime could self-approve: the scheduled ingestion job's own credential
   gains the ability to call `SP_RECORD_SOURCE_REVIEW_DECISION` and
   `SP_RECORD_PAPER_REVIEW_BATCH`. A compromised or buggy scheduled run could
   approve its own source or literature candidate with no separate identity
   required — this directly voids decision driver 1.
2. Owner-rights procedures separated from runtime — the runtime identity
   gains direct `OWNERSHIP`, not just `USAGE`, on governed views, budget
   procedures, and the Streamlit apps — this voids decision driver 2.
3. Migration/deployment identity distinct from routine runtime — one
   credential now holds both the recurring, internet-reachable ingestion path
   and full schema DDL rights — this voids decision driver 4.
4. Read-only audit separation (`PMC_AUDITOR`) disappears entirely; every read
   becomes indistinguishable from a role that can also write and approve.

**What is preserved:** DEV/PROD independence (decision driver 3) — `DEV_ALL`
and `PROD_ALL` remain fully separate roles, credentials, and warehouses.

**Operational effect:** `snow` connections collapse to roughly 4 total
(1 DEV, 1 PROD, plus interactive/legacy Alpha POC). Fastest possible
day-to-day operation; largest acceptance of concentrated blast radius from a
single leaked or misused credential.

## Option B — Minimal consolidated model (~4 roles per environment)

Per environment: `{ENV}_RUNTIME` (ingestion + dbt transform, unchanged from
today's `PIPELINE_RUNTIME`), `{ENV}_OWNER` (merges `STREAMLIT_OWNER`,
`GOVERNED_VIEW_OWNER`, `KG_PAPER_REVIEW_OWNER`, and `KG_LLM_BUDGET_OWNER` into
one owner-rights identity), `{ENV}_READ` (merges `PMC_AUDITOR` with the
reserved `API_RUNTIME` grants), `{ENV}_MIGRATION_DEPLOYER` (unchanged).

**Controls this keeps intact:**

1. Runtime never approves — `RUNTIME` still never holds an owner-rights
   procedure beyond `USAGE`.
2. Owner-rights separated from runtime — `OWNER` remains a distinct
   credential from `RUNTIME`.
3. DEV/PROD independence — unchanged.
4. Migration identity distinct from runtime — unchanged.

**Controls this merges (a named, bounded trade-off, not a silent drop):**

1. Streamlit (Tier D source) and literature (PMC/KG) steward decisions would
   be recorded under the same `OWNER` credential instead of two separate
   roles — anyone who can approve a data source could also approve a paper,
   and vice versa. Both remain distinct from, and still cannot be assumed by,
   `RUNTIME`.
2. Read-only audit (`PMC_AUDITOR`) and the reserved future API-read boundary
   share one `READ` role — acceptable because both are already read-only.

**Operational effect:** `snow` connections drop from 12 to roughly 6-7
(`{ENV}_RUNTIME`, `{ENV}_OWNER`, `{ENV}_READ`, `{ENV}_MIGRATION_DEPLOYER` x2
environments, plus interactive/legacy). Total custom roles drop from 22 to 8
(4 per environment) plus the 2 unaffected legacy Alpha POC roles — a 64%
reduction from today, while every decision driver above stays intact.

## Decision

**Option B — minimal consolidated model (~4 roles per environment) is
accepted.** The product owner reviewed both options, including the explicit
list of controls Option A would void (runtime-never-approves, owner-rights/
runtime separation, migration/runtime separation), and selected Option B to
keep all four decision drivers intact while still cutting role count by 64%.

Per environment, the target model is:

| Role | Replaces / merges | Notes |
|---|---|---|
| `OH_LYME_{ENV}_RUNTIME` | `PIPELINE_RUNTIME` (rename only, no grant change) | Scheduled ingestion + dbt transform. Never gains an owner-rights grant. |
| `OH_LYME_{ENV}_OWNER` | `STREAMLIT_OWNER` + `GOVERNED_VIEW_OWNER` + `KG_PAPER_REVIEW_OWNER` + `KG_LLM_BUDGET_OWNER` (DEV only for the last) | Single owner-rights identity for Tier D source and literature steward decisions plus governed-view/budget procedure ownership. |
| `OH_LYME_{ENV}_READ` | `PMC_AUDITOR` + reserved `API_RUNTIME` grants | Read-only. `API_RUNTIME`'s grants merge in as-is since it has zero current holders; this does not activate the API cutover, it only avoids keeping a fourth near-empty role. |
| `OH_LYME_{ENV}_MIGRATION_DEPLOYER` | `MIGRATION_DEPLOYER` (unchanged) | One-time/per-deploy schema DDL identity. |

Plus the no-regret cleanup from above (drop `DATA_STEWARD`/`APPROVAL_VIEWER`
x2 each; replace `SECURITY_ADMIN` x2 with a direct grant). Net: 22 custom
roles (11 DEV + 9 PROD) become 8 (4 DEV + 4 PROD), plus the 2 unaffected
legacy Alpha POC roles.

`OH_LYME_PROD_KG_PAPER_REVIEW_OWNER`'s grants fold into `OH_LYME_PROD_OWNER`
at the same time even though it is currently dormant (zero holders) — this is
a rename/consolidation of an already-provisioned, unused role, not new PROD
literature activation; it changes nothing about whether that capability is
live in PROD.

Until Story #297 lands the DEV migration for this table, no
`CREATE`/`ALTER`/`DROP ROLE`, `GRANT`, or `REVOKE` for this epic executes.

## Consequences

- Story #297 implements the accepted model in DEV only, then runs a live
  Tier B ingestion as proof before merging.
- Story #298 mirrors the accepted model to PROD behind the ADR-0006 protected
  promotion gate.
- Story #300 updates the `snow` connection surface and both `AGENTS.md` files
  to match the accepted model's final role names.
- `docs/operations/snowflake-stable-role-model.md` is rewritten to match the
  accepted model once implemented, replacing its current "Status note"
  pointing back to this ADR.

## Non-goals

- Changing the legacy Alpha POC's `OH_LYME_API_READER` / `OH_LYME_DATA_LOADER`
  roles or database.
- Removing PROD protection, immutable provenance, or the ADR-0006 promotion
  gate.
- Deleting `API_RUNTIME` or `PROD_KG_PAPER_REVIEW_OWNER` before their
  dependent work (Epic #252 #275; PROD literature activation) resolves.

## Links

- Epic #294, Story #295 (inventory), Story #296 (this ADR), Story #297/#298
  (implementation)
- `docs/operations/role-inventory-dev.md`
- `docs/operations/role-inventory-prod.md`
- `docs/operations/role-classification.md`
- `docs/operations/connection-inventory.md`
- Workspace `TECHNOLOGY_AND_GOVERNANCE.md` (access-control ADR requirement)
- Workspace ADR 0005, ADR 0006
- Data ADR 0027 (tiered ingestion operating model)
