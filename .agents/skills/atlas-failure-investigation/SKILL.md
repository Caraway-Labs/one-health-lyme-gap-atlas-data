---
name: atlas-failure-investigation
description: Investigate Atlas pipeline failures with bounded sanitized evidence and falsifiable regressions; use for an actual failure, not broad autonomous monitoring.
---

Required inputs: task outcome, actual starting SHA/date, environment, permitted action,
operation or incident, available evidence references, and unresolved dependencies.
Read [the reference index](references/workflow.md) for authoritative paths and recipes.

Distinguish verified facts, hypotheses and unknowns. Identify the failing boundary and propose one falsifiable correction with a regression. Preserve original failures and append-only history; use DATA376 packets when delivered without inventing that interface.

Run the existing credential-free context check. For a covered operation, use the
existing pipeline preflight with explicit operation/environment. Aggregate BLOCKED
and UNKNOWN prerequisites; stop dependent consequential work until authorized evidence
resolves them. Do not self-grant, broaden identity, change locked migrations, or
substitute source-string assertions for driver/engine behavior.

Output: outcome; baseline; scope; environment/identity; contracts; prerequisite findings
(PASS/BLOCKED/UNKNOWN with evidence and next authorized action); commands/results;
separate offline, DEV execution, deployment and live proof; remaining blockers.
Use the existing delivery handoff schema for applicable cross-repository tasks.

Examples: positive: Investigate a failed protected build. Negative: Monitor every system continuously.
Near miss: Explain a hypothetical Snowflake error requires explanation only; do not start consequential actions.
