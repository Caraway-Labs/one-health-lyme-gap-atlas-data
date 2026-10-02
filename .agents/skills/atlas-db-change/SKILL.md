---
name: atlas-db-change
description: Plan governed Atlas database changes and forward-only migrations using curated capabilities; use for schema or privilege-sensitive implementation, not SQL tutorials.
---

Required inputs: task outcome, actual starting SHA/date, environment, permitted action,
operation or incident, available evidence references, and unresolved dependencies.
Read [the reference index](references/workflow.md) for authoritative paths and recipes.

Declare target environment and execution identity; inspect migration checksums and available snapshots; separate runtime capability from grant authority. Select behavioral tests for the actual execution boundary. Never replay metadata as migrations.

Run the existing credential-free context check. For a covered operation, use the
existing pipeline preflight with explicit operation/environment. Aggregate BLOCKED
and UNKNOWN prerequisites; stop dependent consequential work until authorized evidence
resolves them. Do not self-grant, broaden identity, change locked migrations, or
substitute source-string assertions for driver/engine behavior.

Output: outcome; baseline; scope; environment/identity; contracts; prerequisite findings
(PASS/BLOCKED/UNKNOWN with evidence and next authorized action); commands/results;
separate offline, DEV execution, deployment and live proof; remaining blockers.
Use the existing delivery handoff schema for applicable cross-repository tasks.

Examples: positive: Plan a DEV forward-only migration. Negative: Explain SQL joins.
Near miss: Describe an old migration without changing it requires explanation only; do not start consequential actions.
