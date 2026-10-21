# 0046: Bounded offline NLCD parallel calculation

Status: Proposed for human review
Date: 2026-10-17
Owner: Atlas data stewardship and engineering
References: DATA #594; draft PR #606; ADRs 0036, 0037, 0038

## Context

The corrected national run contains 193 CONUS counties and 30 Alaska exclusions.
The compatible reviewed proof run contributes five additional CONUS counties.
The 2,911 missing counties can be calculated independently. The current operator
is serial, and changing the selected panel changes scientific run identity.

## Decision

Add a standard-library Linux host operator using Docker CLI, immutable assignment
manifests and isolated per-worker directories. Support 1, 2, 4 or 8 workers;
require the operator to select the count explicitly. Keep the scientific checkout
separate and byte-pinned to PR #606 revision
`a1dca40aa049f5c8db4c819f20230843bc8041cf`. Do not copy, merge or modify that
calculator in this change. All source inputs and calculator mounts are read-only.

Freeze the two audited input runs and their physical partition hashes. Validate
their exact lineage identities and all seven observations before assignment.
Create a new lineage per shard using the existing calculator, then assemble
references across old and new runs. Never rewrite prior partitions or mint a
completion receipt for the incomplete original run. This is offline scientific
calculation, not a second governed ingestion/publication orchestrator.

Concurrency uses kernel advisory host ownership and per-worker calculator locks.
Stopped-container locks can be archived only after ownership and saved-prefix
checks. Scientific failures and no-progress timeouts halt; operational recovery
is explicitly bounded. Retain containers for diagnosis rather than pruning them.

## Alternatives and consequences

Unchanged serial completion repeats five compatible counties. Shared multiwriter
checkpoint directories lose the existing ordinal/run boundary. Kubernetes and
remote queues add unnecessary infrastructure for one host. Docker CLI preserves
the existing runtime and makes container ownership inspectable.

Repeated complete input hashing is retained. Disk contention and the 30-minute
invocation deadline remain constraints. No linear scaling claim is made. Actual
VM provisioning, staging/transfers, paid execution, source admission, Snowflake,
PROD publication, and merging #606 require separate authorization/review.

## Acceptance, rollout and rollback

See the invariant matrix and operator procedures in
`../operations/annual-nlcd-parallel.md`. Test fixtures are not source-backed
national evidence. Benchmark 1/4/8 workers before choosing cloud concurrency.
Stop with SIGTERM; retain every committed result and operational receipt.
Rollback stops the operator and its owned containers, preserving originals.
Cloud teardown must follow verified artifact export and explicit owner approval.

### Interrupted-run recovery implementation (2026-10-18)

The owner-verified recovery archive pins 905 additional corrected county prefixes.
A new assignment may reference those original files read-only alongside the198
original counties, leaving2006 for new isolated workers. Prior incomplete run
identities, locks and receipts remain immutable evidence; no old container is
adopted and no completion receipt is synthesized. Final assembly retains each
original run identity. The frozen archive is an explicit bounded admission,
not arbitrary checkpoint discovery or a change to the scientific calculations.

Run the supervisor directly with durable stdout/stderr and journal capture;
keep optional resource sampling in a separate process so a telemetry exception
cannot terminate healthy calculations. The previous initiating exception remains
unknown. Infrastructure, scientific admission and production publication gates
remain as described above.
