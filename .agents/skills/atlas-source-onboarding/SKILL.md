---
name: atlas-source-onboarding
description: Onboard Atlas sources through approved Tier A/B/C/D orchestrator paths while preserving source restrictions and missingness; use for governed ingestion tasks.
---

Required inputs: task outcome, actual starting SHA/date, environment, permitted action,
operation or incident, available evidence references, and unresolved dependencies.
Read [the reference index](references/workflow.md) for authoritative paths and recipes.

Select the approved tier from the operating contract. Preserve lineage and zero/null/unknown/suppressed/not-reported distinctions. Use atlas-data source validate/run and runs show/explain/resume; runtime cannot approve.

Run the existing credential-free context check. For a covered operation, use the
existing pipeline preflight with explicit operation/environment. Aggregate BLOCKED
and UNKNOWN prerequisites; stop dependent consequential work until authorized evidence
resolves them. Do not self-grant, broaden identity, change locked migrations, or
substitute source-string assertions for driver/engine behavior.

Output: outcome; baseline; scope; environment/identity; contracts; prerequisite findings
(PASS/BLOCKED/UNKNOWN with evidence and next authorized action); commands/results;
separate offline, DEV execution, deployment and live proof; remaining blockers.
Use the existing delivery handoff schema for applicable cross-repository tasks.

Examples: positive: Onboard an approved public DEV source. Negative: Summarize a source website.
Near miss: Inspect a dataset without acquiring it requires explanation only; do not start consequential actions.
