# Epic #223 closeout scorecard

Phase 2 follow-on dispositions and release evidence are tracked in [Epic #259
closeout scorecard](epic-259-closeout-scorecard.md). The historical and tick
exceptions listed below are retained there with their current rationale.

## Velocity benchmark (fixture-backed golden path)

Measured on local developer loop for existing adapter pattern (`cdc_lyme_x5j9_wybp`):

| Metric | Before (legacy) | After (simplified) |
|---|---|---|
| Commands to validate+local run | Many (`cdc-sample`, Streamlit, workflow, recover) | `source validate` + `source run --tier A` |
| Manual Tier A/B approvals | Steward click required for technical advance | 0 for routine public Tier B (ADR 0027) |
| Source-specific workflows for x5j9 | capture + approved-ingestion (+ recover cousins) | 0 supported (deprecated redirect) |
| Source-specific roles/procedures added | Historically common | 0 for this migration (V068 generic) |
| Active effort definition→local success | Often hours of ceremony | Target ≤15 minutes; fixture path is seconds |
| Recovery procedures for injected failure | Workflow/runbook archaeology | `runs explain` + `runs resume` |

## Net complexity accounting

| Surface | Added | Removed / deprecated |
|---|---|---|
| Workflows | `run-ingestion.yml` (+1) | `capture-prod-cdc-evidence.yml`, `run-prod-approved-ingestion.yml` deprecated as happy paths (−2 supported) |
| Modules | `lyme_gap_atlas_data.ingestion.*` | No second orchestration entry point |
| Snowflake roles | 0 | 0 new; stable model documented |
| Procedures/tables | Generic checkpoint + literature stage tables | No source-specific orchestration procs |
| Runbooks/commands | `source` / `runs` CLI + migration note | Legacy x5j9 workflow runbooks redirected |
| Supported happy paths | 1 canonical | Dual x5j9 Actions path retired |

## Literature (#230)

- Durable stage vocabulary + independent retry semantics covered by `LiteratureWorkQueue` tests
- Append-only attempt history rules unchanged (workspace AGENTS.md)
- VPC publish constraint retained (ADR 0012)

## Remaining explicit exceptions

- Historical CDC (`qtbi`) workflows remain until a follow-on migration
- Tick operator envelope (ADR 0022/0023) remains for restricted egress exceptions
- Live DEV/PROD Snowflake execution still operator-gated by credentials and Tier C protections
