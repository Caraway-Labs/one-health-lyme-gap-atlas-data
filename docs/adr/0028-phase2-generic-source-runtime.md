# 0028: Phase 2 generic source runtime boundary

Status: Accepted  
Date: 2026-09-13  
Decision owner: One Health Lyme Gap Atlas product and engineering leads  
Parent: [Epic #259](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/259)

## Context

Phase 1 proved the SourceDefinition state machine with fixtures, but live
acquisition, durable payload recovery, and real DEV storage effects were still
missing. The Phase 2 backlog also requires the historical `qtbi-xd4i` source to
use the shared path while preserving the tick workbook's restricted-egress
exception and the protected historical CDC controls.

## Decision

Use one generic runtime boundary for routine public tabular sources:

1. A committed SourceDefinition selects a bounded adapter. Socrata uses
   deterministic paging and HTTP/XLSX uses declared byte, sheet, header, and
   row bounds.
2. ACQUIRE retains response bytes and registers an immutable artifact before
   downstream work. V068 stores the run/stage checkpoints, V070 stores the
   checksum-verified payload and normalized projections, and V069 stores
   idempotent generic RAW/STAGING/CONFORMED rows plus staged publication
   lineage.
3. Tier B is the live DEV path and advances by automated validation, schema,
   provenance, and quality checks. Tier C remains protected and is not callable
   through the generic CLI. Evidence-only definitions are fail-closed for
   Tier B/C and remain Tier D.
4. `x5j9-wybp` and `qtbi-xd4i` use the generic routine DEV path. The tick
   county-status workbook remains the permanent Tier D operator-envelope
   exception under ADR 0023. Historical CDC capture/publication/recovery/
   rollback workflows remain exception-only for approved source versions.
5. Source-specific x5j9 happy-path workflows and CLI load/promote entry points
   are unsupported and fail closed. No source-specific role or routine
   workflow is added.

## Consequences

The same code can be exercised with fixtures and real DEV effects, and a fresh
worker process can resume from a failed stage without replaying completed
acquisition. Generic row tables are a governed projection, not a replacement
for immutable source bytes. Public API onboarding, geometry joins, tick
pathogen mapping, and PROD source approval remain outside this decision.

## References

- [ADR 0023 — restricted evidence](0023-dev-operator-captured-restricted-evidence.md)
- [ADR 0027 — tiered operating model](0027-tiered-ingestion-operating-model.md)
- [Phase 2 inventory](../operations/pipeline-simplification-phase2-inventory.md)
- [Simplified ingestion interface](../contracts/simplified-ingestion/interface-freeze.md)
