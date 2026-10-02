# DATA377 offline comparison and acceptance limits

Expected outcomes were frozen at commit 3c81b47 before supporting artifacts.
Independent rubric review is pending. Baseline inspected: c5a2310.
Context, operation and handoff interfaces reuse DATA370/371/373/375; no duplicates
of snapshot or failure-evidence implementations are introduced.

| Historical case | Frozen requirement | Delivered observation | Assessment |
| --- | --- | --- | --- |
| #336 connector bulk writes | UNKNOWN without engine proof | Preflight without observed facts UNKNOWN | Engine semantics unverified; no preventive claim |
| #353 procedure binding | UNKNOWN without separate procedure proof | Preflight without observed facts UNKNOWN | Caller/owner invocation unverified |
| #365 canonical coverage | 2/3; one explicitly unknown, source-only unallocated | Deterministic set fixture preserves expected membership | Fixture arithmetic only; V098 engine behavior unverified |
| #366 runtime INSERT | BLOCKED runtime; separate UNKNOWN authority | Contract checks GOVERNED_RELEASES, not historical SEMANTIC_RELEASES; UNKNOWN | Coverage gap; capstone not accepted |
| Missing context | BLOCKED with missing path | Existing helper returns AGENTS.md for empty fixture | Offline reference helper proof |
| Stale context | UNKNOWN current readiness | No observed facts gives UNKNOWN | Actual stale-snapshot integration awaits DATA372 |

The tests intentionally preserve the #366 gap rather than alter the curated contract
without its owner. Passing these tests validates comparison honesty, not complete
historical prevention. No performance percentage or deterministic agent behavior claim.

DATA372 final snapshot schema/freshness/drift fixtures and DATA376 final sanitized
failure packet/correlation/redaction outputs must be integrated before capstone
acceptance. Their paths are pending, not invented. Separate owners should provide exact
heads, schema versions, fixture entrypoints and evidence classes to the parent.

Local verification uses locked uv dependencies. Live database execution, deployment,
and live functional proof remain UNKNOWN. Documentation and fixtures require no DB
migration or runtime release; parent coordinates independent review, refreshed main,
exact Quality CI and serialized existing deployment if needed.
