# 0041: Dataset Discovery recommendation and reviewer identities

Status: Proposed — requires Atlas owner and security approval before any role creation or grant
Date: 2026-09-26
Decision owner: Atlas product, data platform, and security owners
Related: Dataset Discovery [ADR 0001](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-dataset-discovery/blob/main/docs/adr/0001-dataset-discovery-persistence-and-service-boundary.md), data #449/#450/#454, Dataset Discovery #2/#3/#9

## Context

[ADR 0030](0030-snowflake-role-model-simplification.md) describes five stable roles per environment. None is suitable for an unattended recommendation service that must read catalog evidence and persist recommendations while being technically unable to ingest or approve a source. `RUNTIME` has ingestion rights, `OWNER` has governed review rights, `READ` cannot persist, and `MIGRATION_DEPLOYER` is too privileged. A human reviewer also needs an identity distinct from the unattended service. Adding these application-boundary roles is an explicit exception to ADR 0030's exhaustive inventory; the separation-of-duties principles survive.

## Proposed decision

After owner/security approval, create three environment-local roles through the governed role bootstrap and protected migration path:

| Role | Allowed | Denied |
|---|---|---|
| `OH_LYME_{ENV}_DATASET_DISCOVERY_RUNTIME` | Database/schema/warehouse USAGE; SELECT on explicitly listed bounded catalog, evidence and run views; USAGE on data-owned create-run, candidate-outcome, recommendation-commit and finalize-run procedures | Direct base-table DML; `GOVERNANCE` writes; source-review/approval, onboarding handoff, acquisition, ingestion, publication, active search configuration, CREATE/OWNERSHIP, and arbitrary procedure execution |
| `OH_LYME_{ENV}_DATASET_DISCOVERY_REVIEWER` | Individually assigned Snowflake human user; SELECT on reviewed pending/evidence/history views; USAGE on owner-rights review and explicit handoff procedures whose owner derives the caller through session context | Runtime recommendation writes; source approval, ingestion, publication, raw restricted artifacts, migration ownership and direct `GOVERNANCE` DML |
| `OH_LYME_{ENV}_DATASET_DISCOVERY_WRITE_OWNER` | Owns only Dataset Discovery write procedures and their table/view dependencies; narrowly approved `READ SESSION` on account for review principal attribution | Interactive login, routine service credential, source approval, ingestion, publication, and migration deployment |

None of these roles inherits `RUNTIME`, `OWNER`, `STREAMLIT_OWNER`, or `MIGRATION_DEPLOYER`. The deployer may temporarily assume the non-login write-owner role through a reviewed, direct hierarchy edge solely to create/replace procedures and grant their USAGE; the runtime and reviewer never inherit write-owner or deployer. DEV and PROD roles, users, secrets, warehouses and database grants remain separate. The existing role inventory and connection inventory will be updated only when roles actually exist and grants are verified.

The review CLI uses an individual Snowflake-authenticated session; no `--reviewer` option exists. Snowflake caller-rights procedures would require the reviewer role to hold direct table DML, defeating the narrow boundary. The proposed review write procedure therefore uses owner rights with no reviewer table DML. Its dedicated procedure-owner role must receive the narrowly reviewed account-level `READ SESSION` privilege so the procedure can use `SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_NAME')`, `PRINCIPAL_TYPE`, and session role to identify the actual caller. It checks a human-only reviewer allowlist, rejects service/shared principals and NULL context, and records the exact recommendation version and authenticated principal. `CURRENT_USER()` or `SYS_CONTEXT('SNOWFLAKE$CURRENT', ...)` inside owner rights is **not** accepted as the caller proof. The `READ SESSION` grant is a separate owner/security approval item; if it is unavailable, no review write path is enabled and a different reviewed identity boundary is required. A future owner-rights UI requires its own viewer-identity binding.

Data #449 owns a dedicated `DATASET_DISCOVERY` schema and narrow views/procedures. Mutating procedures use explicit DML transactions and a pre-created serialization control row. Standard-table PRIMARY KEY/UNIQUE declarations and `MERGE` alone are not accepted as concurrent uniqueness evidence. Genuine concurrent DEV sessions and lost-acknowledgment replay must pass before hosted acceptance. If the serialization design fails under live Snowflake behavior, revise the procedure boundary before deployment.

Data #450 owns a narrow, human-triggered handoff procedure that creates investigation work only. Rights unknown and review-required states can enter investigation; known restricted means no automated acquisition; only a reviewed hard prohibition blocks the appropriate investigation request. Handoff has no source-approval or ingestion path.

## Relation to ADR 0030 and ADR 0001

On acceptance, this ADR supersedes **only** ADR 0030's claim that the five named roles are exhaustive for every Atlas application boundary. ADR 0030's runtime/owner/deployer separation and DEV/PROD isolation remain mandatory. Historical ADR 0030 text and applied migration checksums stay unchanged. Dataset Discovery ADR 0001 remains authoritative for the standalone service and Snowflake persistence; add a backlink to this accepted role exception there after approval. No competing Dataset Discovery persistence decision is created.

## Alternatives considered

1. Extend `RUNTIME`: rejected because the agent would inherit ingestion authority.
2. Extend `OWNER` or `MIGRATION_DEPLOYER`: rejected because the agent would inherit review or DDL authority.
3. Add writes to `READ`: rejected because it changes a read-only audit role's meaning and makes reviewer/service separation unclear.
4. Use one shared Dataset Discovery role for inference and review: rejected because the unattended service could impersonate a reviewer.
5. New narrow runtime, reviewer, and procedure-owner roles: proposed; adds role count but preserves the control boundary and keeps `READ SESSION` off broad existing roles.

## Acceptance, rollout, and rollback

Owner/security approval must identify who may create the roles, who may grant them to service and individual users, and whether the dedicated procedure owner may receive `READ SESSION` on account. That privilege is never granted to the runtime or reviewer role. Data #454's V103 partial-state and protected migration health must be resolved before any #449 migration is applied. Do not use ACCOUNTADMIN/SYSADMIN or broad `MANAGE GRANTS` as a shortcut. Verify current user/role/database/warehouse, grants, effective role hierarchy, authenticated principal attribution, positive procedure/view access, and alternate-path denials in DEV. PROD requires its own protected approval and equivalent tests. Rollback disables runtime/reviewer credentials and procedure grants while retaining append-only audit records; use a forward migration for schema correction rather than editing applied checksums.
