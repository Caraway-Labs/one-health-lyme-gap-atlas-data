# PROD Snowflake role consolidation runbook (Epic #294 / Story #298)

Mirrors the DEV consolidation executed in Story #297
(`docs/operations/deployment-promotion.md`'s "DEV role-model consolidation
bootstrap" section) against `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, per
[ADR 0030](../adr/0030-snowflake-role-model-simplification.md). This is a
protected action gated by ADR 0006's GitHub `production` environment
approval; it must not run until the product owner has given explicit
go-ahead for this specific action (per `AGENTS.md`), separate from the ADR
0030 acceptance itself.

## Preconditions

1. Story #297's DEV consolidation PR is merged to `main`.
2. This PR's code/config/test diff (renaming `OH_LYME_PROD_PIPELINE_RUNTIME`
   -> `OH_LYME_PROD_RUNTIME` and the `OWNER`/`READ`/`MIGRATION_DEPLOYER`
   equivalents) is fully drafted and reviewed, but **not merged** — merging
   before the live rename would break the running PROD App Platform
   deployment and the protected `run-prod-ingestion.yml` identity check.
3. An explicit go-ahead has been given for this specific mutating PROD
   action.
4. A connection that resolves to `ACCOUNTADMIN` is available and confirmed
   live with a read-only `SELECT CURRENT_USER(), CURRENT_ROLE()` query
   immediately before use (same pattern as Story #297; `BVB26657_PAT` was
   confirmed to resolve to `ACCOUNTADMIN` at that time — reverify, since
   PATs can be rotated).

## Execution steps

1. **Freeze**: confirm no PROD ingestion/dbt run or PROD migration deploy is
   in flight (`atlas-data status` against PROD, and check
   `.github/workflows/run-prod-ingestion.yml` / deploy-prod workflow run
   history for in-progress runs). Do not start this while a PROD job is
   running.
2. **Capture pre-state evidence** (read-only, before any mutation):
   - `SHOW ROLES LIKE 'OH_LYME_PROD%';`
   - `SHOW GRANTS TO ROLE OH_LYME_PROD_PIPELINE_RUNTIME;` (and to each of
     `STREAMLIT_OWNER`, `GOVERNED_VIEW_OWNER`, `API_RUNTIME`,
     `KG_PAPER_REVIEW_OWNER`, `DATA_STEWARD`, `APPROVAL_VIEWER`,
     `SECURITY_ADMIN`, `MIGRATION_DEPLOYER`)
   - `SHOW GRANTS OF ROLE <each above>;` (to capture holders)
   - Save all output; attach to the Story #298 issue/PR as evidence.
3. **Create the two new roles**: `OH_LYME_PROD_OWNER`, `OH_LYME_PROD_READ`.
4. **Merge grants into `OH_LYME_PROD_OWNER`** from `GOVERNED_VIEW_OWNER` and
   `KG_PAPER_REVIEW_OWNER` (generate the exact `GRANT`/`GRANT OWNERSHIP ...
   COPY CURRENT GRANTS` statements from step 2's live `SHOW GRANTS TO ROLE`
   output for each source role, the same way Story #297 generated
   `tmp/dev_owner_read_grants_deduped.sql` — do not hand-author grants from
   memory). Account-level privileges (`... ON ACCOUNT`) must be granted with
   no object name, not the account locator (Story #297 hit this exact
   syntax error).
5. **Merge grants into `OH_LYME_PROD_READ`** from `API_RUNTIME` (PROD has no
   `PMC_AUDITOR`; `READ` will only hold `API_RUNTIME`'s grants for now).
6. **`STREAMLIT` ownership cannot transfer** (confirmed unsupported by
   Snowflake in Story #297 — do not re-attempt `GRANT OWNERSHIP ON
   STREAMLIT`). Instead: `GRANT ROLE OH_LYME_PROD_STREAMLIT_OWNER TO ROLE
   OH_LYME_PROD_OWNER;`. `STREAMLIT_OWNER` is retained, not dropped.
7. **Grant the new roles to existing holders**: `OH_LYME_PROD_OWNER` to
   whatever human/service principals held `GOVERNED_VIEW_OWNER` or
   `KG_PAPER_REVIEW_OWNER` in step 2's evidence (expected:
   `ACCOUNTADMIN`, `OH_LYME_PROD_MIGRATION_DEPLOY_SVC`), plus directly to
   `OH_LYME_PROD_MIGRATION_DEPLOYER` (replacing the `SECURITY_ADMIN`
   indirection). Grant `OH_LYME_PROD_READ` to any confirmed `API_RUNTIME`
   holders (expected: none, per the Story #295 inventory — confirm this is
   still true in step 2 before skipping).
8. **Rename the runtime role**: `ALTER ROLE OH_LYME_PROD_PIPELINE_RUNTIME
   RENAME TO OH_LYME_PROD_RUNTIME;` (preserves all grants and holders,
   confirmed safe in Story #297).
9. **Drop the merged source roles**: `GOVERNED_VIEW_OWNER`,
   `KG_PAPER_REVIEW_OWNER`, `API_RUNTIME` (only if step 2 confirmed zero
   holders beyond what was migrated).
10. **No-regret cleanup**: drop `DATA_STEWARD`, `APPROVAL_VIEWER`,
    `SECURITY_ADMIN` (zero code references confirmed in
    `docs/operations/role-classification.md`; `SECURITY_ADMIN` has zero
    holders in PROD per `role-inventory-prod.md`, an even weaker
    justification for existing than its DEV counterpart).
11. **Capture post-state evidence**: `SHOW ROLES LIKE 'OH_LYME_PROD%';`
    (expect exactly 5: `RUNTIME`, `OWNER`, `STREAMLIT_OWNER`, `READ`,
    `MIGRATION_DEPLOYER`) and `SHOW GRANTS OF ROLE` for `OWNER`/`READ`.
12. **Merge the prepared code/config PR** (this branch) now that Snowflake
    matches it. Deploy `.do/app.prod.yaml`'s `SNOWFLAKE_ROLE` change through
    the normal PROD deploy path.
13. **Live proof**: run a bounded, already-approved PROD action that
    exercises `OH_LYME_PROD_RUNTIME` (e.g. the next regularly scheduled
    `run-prod-ingestion.yml` Tier C tick, or a manual `workflow_dispatch` if
    the product owner authorizes one specifically for this verification).
    Confirm the identity-check step logs `role=OH_LYME_PROD_RUNTIME` and the
    run succeeds. Attach the run URL to the issue.

## Rollback

Rollback is only needed if step 8 (rename) or later fails, or if step 13's
live proof fails. Because `ALTER ROLE ... RENAME` and `GRANT ROLE ... TO
ROLE` are both fully reversible and non-destructive to data:

1. **If the rename or a grant step fails partway (steps 3-11):** re-run only
   the remaining un-executed steps; every step above is idempotent
   (`CREATE ROLE IF NOT EXISTS` semantics apply naturally since Snowflake
   errors loudly on duplicate `CREATE ROLE`, which is the desired fail-closed
   behavior — do not add `IF NOT EXISTS`, so a partial failure is visible
   rather than silently skipped). Do not proceed past a failed step without
   diagnosing it.
2. **If steps 1-11 fully succeeded but step 12 (PR merge) or step 13 (live
   proof) fails:**
   - `ALTER ROLE OH_LYME_PROD_RUNTIME RENAME TO OH_LYME_PROD_PIPELINE_RUNTIME;`
     reverses step 8 exactly (grants/holders are preserved through a
     rename in both directions, confirmed in Story #297).
   - Do **not** merge or deploy this PR's `.do/app.prod.yaml` /
     `cdc_historical_ingestion.py` / `run-ingestion.yml` changes until the
     rename is confirmed live again under the old name.
   - The dropped roles (`GOVERNED_VIEW_OWNER`, `KG_PAPER_REVIEW_OWNER`,
     `API_RUNTIME`, `DATA_STEWARD`, `APPROVAL_VIEWER`, `SECURITY_ADMIN`) are
     **not** restored automatically by this rollback path. If a step-9/10
     drop already ran and something downstream needs one of those roles
     restored, re-`CREATE ROLE`, re-apply the exact grants captured in step
     2's evidence, and re-grant to the exact holders captured in step 2 —
     do not guess at replacement grants. This is why step 2's evidence
     capture is mandatory before any mutation.
   - Since `OWNER`/`READ` grants were additive (copied, not moved, from the
     merged roles until step 9/10 drops the originals), rollback ordering
     should always revert step 8 (the rename) before considering whether
     steps 9/10 need reversal, because the rename is what the live runtime
     identity depends on.
3. **Escalation**: this rollback does not touch data (`RAW`/`STAGING`/
   `CONFORMED`/`GOVERNANCE` tables and their contents are never altered by
   any step above — only role objects and grants). If PROD ingestion is
   failing after this change and the above rollback does not resolve it
   within the current maintenance window, stop and escalate to the account
   owner rather than attempting further ad hoc Snowflake DDL.

## Non-goals

- This runbook does not touch the 2 legacy Alpha POC roles
  (`OH_LYME_API_READER`, `OH_LYME_DATA_LOADER`) — explicitly out of scope
  per Epic #294 / `AGENTS.md`.
- This runbook does not rotate or reissue any PAT. Story #297 found that
  DEV PATs scoped to dropped roles became invalid; the same will happen to
  any PROD `snow` connection scoped to a role dropped in step 9/10. Confirm
  which named PROD connections (see `docs/operations/connection-inventory.md`)
  are scoped to `GOVERNED_VIEW_OWNER`/`KG_PAPER_REVIEW_OWNER`/`API_RUNTIME`
  before step 9/10 and warn the account owner those will need reissuing.
  Tracked under Story #300.
