# Sanitized failure evidence v1 — DATA376

Baseline: data main `c5a23105719ac77f8abbca9b613b661654e22845`, audited
2026-10-02. This explicitly authorized follow-on supersedes the September
deferral for this implementation only. No Guardian, logging backend, runtime
repair, automatic retry, credential, role change, or migration is required.
No `.agents/skills` directory exists in this baseline. Workspace governance
and ADR 0005 are outside this checkout; governed runtime work must resolve
those prerequisites before execution.

## Contract with DATA375, DATA250 and parallel work

[DATA375 handoff](handoff-v1.schema.json) remains unchanged. Its requested SHA,
workflow head, tested/deployed artifact, semantic bundle/API contract, and four
verification states remain separate. Link the packet from the optional failure
section; packet `workload_sha` is the actual executed checkout, never inferred
from requested SHA, workflow head, PR repair head, merge SHA, or a green build.
Packet observations use `KNOWN`/`UNKNOWN`; handoff verification continues to use
`PASS`/`FAIL`/`UNKNOWN`. Neither format is a release controller.

[Packet schema](failure-packet-v1.schema.json) mirrors the installed Python
`PACKET_SCHEMA`, checked by a regression test. Offline JSON validation applies
closed field/enum rules and behavioral-proof constraints. The Python validator
also verifies the derived correlation key. Use:

```powershell
uv run python scripts/validate_failure_evidence.py docs/delivery/failures/pr-336.json
uv run pytest tests/test_failure_evidence.py tests/test_handoff_validation.py -q
```

DATA250 operational `FailureCategory` is reused unchanged: configuration,
acquisition, policy/license, schema, normalization, warehouse, quality,
provider/model, graph, deployment, permission, process. The separate delivery
failure class is explicitly reviewed, never inferred from that category:
software defect, permission/configuration prerequisite, expected governance
block, upstream outage, intentional negative test, or UNKNOWN. A warehouse
error alone does not establish a defect. Do not count expected blocks, negative
tests or unrelated outages as code defects.

DATA372 owns its snapshot files; DATA374 owns skill entry points; DATA377 owns
capstone fixtures. Their owners may consume this schema and validator without
editing DATA376 files. Parent coordinates any shared contract change. This
implementation owns only `failure_evidence.py`, `validate_failure_evidence.py`,
`test_failure_evidence.py`, and these `docs/delivery/failure*` files.

## Privacy and bounded diagnostics

This is an opt-in utility over reviewed metadata, not a raw-log collector or
automatic pipeline hook. Never pass exception objects/messages, SQL, parameters,
prompts, workbooks, environment dumps, private payloads, or source user data.
Regex replacement cannot establish their safety. Unknown keys and arbitrary
strings fail closed. Diagnostic codes, boundaries, operation, classification,
and approved role identifiers are closed enums; hashes have exact formats;
query IDs are bounded UUIDs; public references are limited to this repository's
PRs/issues/commits/Actions IDs without fragments, query strings or credentials.
All rejected values and sink errors produce constant status codes without echo.
Public references must themselves point to reviewed safe evidence. Syntactic
validation does not prove that a supplied reference or hash is truthful.

Useful diagnostics retain boundary/category/code, approved effective-role
identifier when visible, run/job/attempt identities, query IDs, artifact hashes,
and independently checkable evidence references. No raw error message is retained.
Add new codes/roles only in reviewed contract changes; do not broaden strings
to work around a rejection. The role allowlist describes packet visibility,
not authority to execute or grant anything.

Each missing observation includes a reason: NOT_COLLECTED, UNAVAILABLE,
INCOMPLETE_LOGS, ROLE_NOT_VISIBLE, QUERY_ID_UNAVAILABLE, REDACTION_REJECTED, or
NOT_APPLICABLE. Missing visibility is not confirmed absence. An empty query
list cannot claim KNOWN. Partial logs cannot prove complete failure history.
UNKNOWN workload identity makes correlation provisional: identical public
metadata can group unrelated unknown workloads. Resolve it with actual execution
evidence; do not invent it. `recorded_at` is packet compilation time, not incident
time. Run/job/attempt IDs remain separate from the stable key; a missing attempt
cannot be represented as an auditable known attempt.

## Optional collection and original failure

`collect_failure(context, sink)` copies and validates metadata, returns COLLECTED,
REDACTION_REJECTED, or COLLECTION_UNAVAILABLE, and never reads exception text.
The caller chooses a reviewed sink/destination and retains collection status
separately from the original pipeline outcome. There is no default filesystem,
network, data-store write, privilege request or retry. A sink must be bounded,
nonblocking and independent of pipeline data; this helper cannot enforce the
behavior of an arbitrary callback. No production sink is wired by this change.

```python
try:
    existing_operation()
except Exception:
    collection_status = collect_failure(reviewed_metadata, safe_sink)
    # Preserve original outcome and traceback, even when collection is unavailable.
    raise
```

Tests inject a failing sink and an exception whose string renderer raises, and
prove the same original exception object escapes and input context is unchanged.
No broader privilege is needed for offline packet construction.

## Independent reviewer handoff

`review_context(packet)` produces bounded fresh-context review instructions.
Start from the packet, current main and authoritative contracts; do not rely on
the implementer's narrative. Identify the boundary, missing preventive check,
evidence gaps, required regression, and next authorized action. Falsify the
failure hypothesis using the relevant driver, engine, role, contract fixture or
deployed artifact. Verify workload/artifact identity independently of workflow
head. Request narrowly bounded integration authorization where absent.

DB, permissions, deployment, contract and UNKNOWN risk require independent
behavioral evidence before release. Prose-only work does not mandate multi-agent
review. A repair PASS requires linked behavioral regression PASS and behavioral
repair PASS; passing the insufficient static check cannot close an incident.
The validator enforces declared proof kinds, not the correctness of linked
evidence: the reviewer must inspect that proof and authorization.

Historical [336](failures/pr-336.json), [353](failures/pr-353.json),
[365](failures/pr-365.json), [366](failures/pr-366.json) use current GitHub PR
metadata and DATA250 as sources. Static regression PASS records only the local
checks reported there; runtime repair, executed SHA, hashes, role and query
visibility remain UNKNOWN. The repaired PR is a verified fact reference, not
proof of deployed behavioral repair. Suggested required regressions are driver
batch execution, engine VARIANT binding, canonical fixture execution and intended
release-role execution respectively. Safe executable reproductions remain
UNKNOWN until a reviewed bounded fixture/proof is available.

## Parallel and release discipline

Use isolated branches/worktrees and disjoint file ownership. Serialize shared
migration numbering, role-model changes, release pointers and breaking contracts
through the parent. Refresh main, review the exact resulting head independently,
rerun the exact Quality workflow, then serialize merges and existing deployments.
Never overwrite another agent's uncommitted changes. This change adds no runtime
deployment dependency; installing it in the existing image follows the existing
protected deployment. DEV/PROD behavioral invocation and deployed-image proof
remain separate evidence from local tests or merged PRs.
