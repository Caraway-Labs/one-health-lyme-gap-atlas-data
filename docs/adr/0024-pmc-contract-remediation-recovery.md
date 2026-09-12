# 0024: PMC Contract-Remediation Recovery Accounting

Status: Accepted
Date: 2026-09-12
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

Workspace ADR 0015 covers provider requests rejected before inference. After
that recovery path, PMC13314803 reached an OpenAI structured response and
failed closed on a `ValidationError` for illegal relationship endpoints.
Subsequent operator work shipped partial-accept of illegal edges, redacted
diagnostics, Neo4j property sanitization, and durable host-network Neo4j
reachability. Those remediations change the failure mode for a preserved,
steward-approved paper without making the earlier immutable attempt rows false.

A silent paper reset would violate append-only attempt history. Reusing the
provider-rejection classification would mislabel LLM-execution outcomes.

## Decision

A steward may reopen a `retry_exhausted` paper after a reviewed contract or
infra remediation by classifying named failed attempt ids as
`contract_remediation_reopen` through an append-only DEV control. Attempt rows
are never deleted or rewritten. Classified remediation attempts do not count
toward the three LLM-execution failure limit, alongside
`provider_rejected_pre_inference`.

The control requires a correlation id, rationale naming the remediated defect
and code/image evidence, classification rows, and a paper-state event before
returning the paper to `retry_pending`. It authorizes no production promotion
and does not weaken license, identity, budget, or VPC publication gates.

## Consequences

- ValidationError and remediated infra publish failures can be reopened without
  erasing evidence.
- New LLM-execution failures after reopen still count toward exhaustion.
- Operator documentation must keep the VPC worker on an immutable digest and,
  when `NEO4J_URI` targets localhost on the co-located Neo4j host, use Docker
  `--network host` (or an equivalent reachable Bolt endpoint).

## Links

- Workspace ADR 0012: VPC-native PMC extraction worker
- Workspace ADR 0015: PMC provider-rejection recovery accounting
- Workspace ADR 0017: PMC contract-remediation recovery accounting (same decision)
- Migration `V064__dev_pmc_contract_remediation_recovery.sql`
- PRs #238–#242 (partial-accept, Neo4j-safe props, V064 reopen path)
