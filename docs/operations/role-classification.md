# Snowflake role classification and ADR options (Epic #294, Story #295)

Source evidence: [role-inventory-dev.md](role-inventory-dev.md),
[role-inventory-prod.md](role-inventory-prod.md),
[connection-inventory.md](connection-inventory.md). All read-only; no
Snowflake role, grant, or user was created, altered, or dropped to produce
this document.

## Full classification (22 custom roles: 2 legacy Alpha POC + 11 DEV + 9 PROD)

| Role | Environment | Classification | Named control it protects (if any) | Recommended disposition |
|---|---|---|---|---|
| `PIPELINE_RUNTIME` | DEV, PROD | Active, load-bearing | "Runtime never approves" (`AGENTS.md`, ADR 0005/0027) | Keep as a distinct role in every option |
| `STREAMLIT_OWNER` | DEV, PROD | Active, load-bearing | Owner-rights separated from runtime; Tier D steward decisions | Keep, or merge with `KG_PAPER_REVIEW_OWNER` into one "approval/steward owner" role |
| `GOVERNED_VIEW_OWNER` | DEV, PROD | Active, load-bearing | Owner-rights separated from runtime for governed/explorer views | Keep, or merge with `MIGRATION_DEPLOYER` |
| `KG_PAPER_REVIEW_OWNER` | DEV; PROD dormant | Active (DEV) / dormant (PROD) | Owner-rights separated from runtime for literature steward decisions | Keep, or merge with `STREAMLIT_OWNER` |
| `KG_LLM_BUDGET_OWNER` | DEV only | Active, load-bearing (narrow) | Owner-rights separated from runtime for budget procedures | Merge into `GOVERNED_VIEW_OWNER`-equivalent "owner" role — same holder already |
| `PMC_AUDITOR` | DEV only | Active, load-bearing (read-only) | Read-only audit boundary, no write path | Keep distinct, or merge into a single "governed read/audit" role |
| `MIGRATION_DEPLOYER` | DEV, PROD | Active, load-bearing | DEV/PROD independence (ADR 0006); one-time bootstrap identity | Keep as a distinct role in every option |
| `API_RUNTIME` | DEV, PROD | **Dormant, reserved** — zero current holders | Future browser-to-API boundary (Epic #252 #275) | Do not delete; do not count as "sprawl" until #275 either activates or cancels it |
| `SECURITY_ADMIN` | DEV, PROD | **Undocumented indirection** — no git history, PROD copy has zero holders | None found; sole purpose is `USAGE ON ROLE *_STREAMLIT_OWNER` | Eliminate: grant `USAGE ON ROLE *_STREAMLIT_OWNER` directly to `MIGRATION_DEPLOYER` instead |
| `DATA_STEWARD` | DEV, PROD | **Unused duplicate** — zero git references | None found | Delete — no-regret, see below |
| `APPROVAL_VIEWER` | DEV, PROD | **Unused duplicate** — zero git references, zero holders | None found | Delete — no-regret, see below |
| `OH_LYME_API_READER` | Legacy Alpha POC | Active (serves current production API) | Out of scope — Alpha POC is untouched by this epic | No change |
| `OH_LYME_DATA_LOADER` | Legacy Alpha POC | Unused, zero holders | Out of scope — Alpha POC is untouched by this epic | No change (leave as documented manual-assumption role) |

## No-regret deletions (recommended regardless of which ADR option is chosen)

`DATA_STEWARD` and `APPROVAL_VIEWER` exist in both DEV and PROD with
byte-for-byte identical grants, zero references anywhere in the git-tracked
repository, and — except for one accidental human grant of `DEV_DATA_STEWARD`
— zero current holders. They protect no named control and nothing in the
codebase depends on them. Dropping all four (`OH_LYME_DEV_DATA_STEWARD`,
`OH_LYME_DEV_APPROVAL_VIEWER`, `OH_LYME_PROD_DATA_STEWARD`,
`OH_LYME_PROD_APPROVAL_VIEWER`) reduces the inventory from 22 to 18 roles with
zero functional risk, independent of the broader ADR decision. This is
proposed as an early, low-risk action inside Story #297/#298 rather than a
reason to delay the ADR.

## The `SECURITY_ADMIN` indirection

`OH_LYME_DEV_SECURITY_ADMIN` and `OH_LYME_PROD_SECURITY_ADMIN` were each
created directly against the account (no migration, no PR, no commit) and each
holds exactly one privilege: `USAGE ON ROLE OH_LYME_{ENV}_STREAMLIT_OWNER`.
The PROD copy has zero current holders. Removing both and replacing them with
a direct `GRANT USAGE ON ROLE OH_LYME_{ENV}_STREAMLIT_OWNER TO ROLE
OH_LYME_{ENV}_MIGRATION_DEPLOYER` achieves the identical effect for the one
holder that matters (the migration deployer) while removing two more roles and
two more `snow` connections (`BVB26657_SECURITY_ADMIN_PAT` and its PROD
equivalent) from the surface a developer must track.

## ADR options for Story #296

Both options assume the four no-regret deletions and the `SECURITY_ADMIN`
indirection removal above happen either way. They differ only in how far
consolidation goes beyond that, and what each additionally gives up.

### Option A — True two-role model (`{ENV}_ALL`)

One role per environment (`OH_LYME_DEV_ALL`, `OH_LYME_PROD_ALL`) holding every
privilege currently spread across `PIPELINE_RUNTIME`, `STREAMLIT_OWNER`,
`GOVERNED_VIEW_OWNER`, `KG_PAPER_REVIEW_OWNER`, `KG_LLM_BUDGET_OWNER`,
`PMC_AUDITOR`, and `MIGRATION_DEPLOYER` for that environment.

Controls this **drops**, named explicitly:

1. **"Pipeline runtime role must never approve candidates"** (`AGENTS.md`,
   ADR 0005/0027) — the scheduled ingestion job's credential could now also
   call `SP_RECORD_SOURCE_REVIEW_DECISION` and `SP_RECORD_PAPER_REVIEW_BATCH`.
   A compromised or buggy scheduled run could self-approve its own source or
   literature candidate with no separate identity required.
2. **Owner-rights procedures separated from runtime** (data-repo `AGENTS.md`,
   `docs/operations/snowflake-stable-role-model.md`) — the runtime identity
   would gain direct `OWNERSHIP` on governed views, budget procedures, and the
   Streamlit apps themselves, not just `USAGE`, removing the audit boundary
   that currently shows *who* changed governance-facing objects versus who
   merely executed them.
3. **Migration/deployment identity distinct from the routine scheduled
   runtime** (ADR 0006 spirit) — one compromised credential now has both the
   recurring, internet-reachable ingestion path *and* full schema DDL rights.
4. Read-only audit separation (`PMC_AUDITOR`) disappears — every read becomes
   indistinguishable from a role that can also write and approve.

Consequence if accepted: `snow` connections collapse to roughly 4 total
(1 DEV, 1 PROD, plus the existing interactive/legacy Alpha POC ones). Fastest
to operate; largest acceptance of concentrated blast radius.

### Option B — Minimal consolidated model (~4 roles per environment)

Per environment: `{ENV}_RUNTIME` (ingestion + transform, unchanged), 
`{ENV}_OWNER` (merges `STREAMLIT_OWNER`, `GOVERNED_VIEW_OWNER`,
`KG_PAPER_REVIEW_OWNER`, `KG_LLM_BUDGET_OWNER` — all of today's "owner-rights,
human- or migration-deployer-assumed, never runtime-held" roles into one),
`{ENV}_READ` (merges `PMC_AUDITOR` plus the reserved `API_RUNTIME` grants),
`{ENV}_MIGRATION_DEPLOYER` (unchanged).

Controls this **keeps intact**:

1. "Runtime never approves" — `RUNTIME` still never holds an owner-rights
   procedure beyond `USAGE`.
2. Owner-rights separated from runtime — `OWNER` is still a distinct
   credential from `RUNTIME` and from `MIGRATION_DEPLOYER`.
3. Migration/deployment identity distinct from the runtime — unchanged.

Controls this **merges** (a smaller, named trade-off, not a silent drop):

1. Streamlit (Tier D source) and literature (PMC/KG) steward decisions would
   be recorded under the same `OWNER` credential instead of two separate
   roles. Anyone who can approve a data source could also approve a paper,
   and vice versa — a reduction in decision-domain separation, but both
   remain distinct from, and still cannot be assumed by, `RUNTIME`.
2. Read-only audit (`PMC_AUDITOR`) and the reserved future API-read boundary
   share one `READ` role — acceptable because both are already read-only
   today.

Consequence if accepted: `snow` connections drop from 12 to roughly 6-7
(`{ENV}_RUNTIME`, `{ENV}_OWNER`, `{ENV}_READ`, `{ENV}_MIGRATION_DEPLOYER` x2
environments, plus interactive/legacy). Total custom roles drop from 22 to 8
(4 per environment) plus the 2 unaffected legacy Alpha POC roles.

## Recommendation for the ADR

Present both options with their explicit trade-offs to the product owner
unchanged from above; this document does not pre-select one. Story #296's ADR
must record the choice, name the date, and (if Option A is chosen) record that
the three controls it drops were reviewed and knowingly accepted.
