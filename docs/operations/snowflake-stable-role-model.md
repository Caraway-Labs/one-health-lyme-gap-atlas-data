# Stable Snowflake role model for simplified ingestion (Epic #223 / Story #229).

> **Status note (2026-09-16, Epic #294):** the table below has drifted from
> the live account. A read-only audit found 11 DEV and 9 PROD custom roles —
> `DATA_STEWARD`, `APPROVAL_VIEWER`, `SECURITY_ADMIN`, and
> `MIGRATION_DEPLOYER` exist in Snowflake today but are not listed here at
> all. See [role-inventory-dev.md](role-inventory-dev.md),
> [role-inventory-prod.md](role-inventory-prod.md), and
> [role-classification.md](role-classification.md) for the full reconciled
> inventory and the two ADR options under consideration in
> [Story #296](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/296).
> This document's table is superseded once that ADR is `Accepted`; until then
> it remains the last agreed baseline for what Epic #223 intended.

## Goal

Routine public-source onboarding must not create a new Snowflake role or a
source-specific owner procedure solely for orchestration.

## Minimal stable role model (as designed by Epic #223 — see status note above for drift)

| Capability | Role pattern | Notes |
|---|---|---|
| Ingestion runtime | `OH_LYME_{ENV}_PIPELINE_RUNTIME` | Acquire/load/checkpoint/quality |
| Transformation runtime | same pipeline runtime + dbt warehouse usage | No per-source transform role |
| Governed read | `OH_LYME_{ENV}_GOVERNED_VIEW_OWNER` / API reader roles | Read-only products |
| Application/API read | `OH_LYME_{ENV}_API_RUNTIME` | Public API boundary |
| Streamlit owner | `OH_LYME_{ENV}_STREAMLIT_OWNER` | Tier D decisions only |
| Deployment/migration | dedicated migration identity | One-time platform bootstrap |
| KG paper review owner | `OH_LYME_{ENV}_KG_PAPER_REVIEW_OWNER` | Literature steward procs |
| PMC audit | `OH_LYME_{ENV}_PMC_AUDITOR` / `ATLAS_DEV_PMC_AUDIT` | Read-only recovery audit |

## Generic objects (prefer these)

- `GOVERNANCE.INGESTION_RUNS`
- `GOVERNANCE.INGESTION_RUN_CHECKPOINTS` (V068)
- `GOVERNANCE.LITERATURE_WORK_ITEMS` / `LITERATURE_WORK_STAGES` (V068)
- Generic owner-rights procedures for review/reopen — not per-source clones

## Forbidden for routine onboarding

- New `OH_LYME_*_<SOURCE>_*` roles
- New source-specific orchestration-only procedures
- Rewriting approval allowlists solely to unlock Tier B technical stages

## Rare changes requiring AccountAdmin / ownership handoff

Documented only in `docs/operations/deployment-promotion.md` (procedure owner
bootstraps such as historical V056/V059). Not part of normal source onboarding.

## Privilege-contract tests

See `tests/test_snowflake_role_model.py`.
