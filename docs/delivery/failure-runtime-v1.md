# Opt-in semantic build failure adapter

DATA376 extends only the existing `pipeline semantic-release-build` invocation:
`--failure-context <reviewed-v1-json> --failure-packet <new-private-file>`.
Both options default to absent. No workflow enables them automatically; no new
backend, directory, credentials, grants or retention destination is created.
The operator must select an existing private directory with suitable ACLs and
the existing applicable retention policy. POSIX files request mode 0600;
Windows privacy depends on that directory's inherited ACLs.

Supply reviewed packet-v1 metadata for this actual invocation, including an
accurate recorded time and attempt. Historical example packets are reference
fixtures, not templates to publish unchanged for a new run. Never substitute
workflow head for unknown actual checkout/artifact. Keep missing identity,
effective role, query IDs, regression and repair evidence UNKNOWN with the
appropriate reason. Operation must be SEMANTIC_RELEASE; the adapter neither
guesses the failed stage nor promotes a hypothesis into a verified category.
Do not pass exception objects, SQL/parameters, raw manifests, credentials,
environment dumps, provider responses or personal paths as packet fields.

The CLI invokes the existing builder once. On an ordinary exception, after its
existing rollback handling, it attempts collection once and uses bare raise.
The original exception object and traceback survive. Success does not read
metadata or create a packet. No retry, commit, approval, query, publication or
release-pointer change is introduced. Output-rendering failures after a
successful builder are not represented as failed build transactions.

Metadata must be a regular file, read at most 32,769 bytes. Packet input/output
is capped at 32,768 bytes; validation precedes publication. Exclusive creation
refuses an existing file or symlink and never overwrites another attempt.
An interrupted write removes its newly created partial file where possible;
an OS failure during cleanup can leave a partial file, which is not a valid
receipt and must not be treated as collected. Each invocation owns a separate
output filename. There is no directory-wide artifact upload.

Only constant collection status is written to stderr: COLLECTED,
REDACTION_REJECTED or COLLECTION_UNAVAILABLE. Failure to emit even this status
does not replace the original exception. Disabled collection emits nothing.
Missing output is not proof of success, absence of failure or repaired behavior.
The repository's existing original exception presentation is unchanged; the
failure packet never renders or copies it. Independently review this adapter
and its behavioral tests before optional use in any protected job.

## Proof and remaining live scope

`tests/test_failure_runtime.py` executes the real builder through its CLI with
an injected failing write connection: exactly one rollback, zero commits,
identical exception/traceback, and collection success/failures. The strict
collector privacy suite remains authoritative. This is offline proof, not
Snowflake engine, live identity or deployed collector proof.

Baseline is f28efd9d510ea117d774846292ead8f6bb3e8603 (2026-10-02), an isolated
worktree; DATA377 files and historical packets are unchanged. The portable
agent-context index applies because assembled workspace governance/ADR0005
files are absent. Read ADR0027 and the ingestion/release contracts before
implementation; no DDL or pipeline data semantics change.

Existing documented DEV inspection target is connection ATLAS_DEV_READ, role
OH_LYME_DEV_READ, database ONE_HEALTH_LYME_GAP_ATLAS_DEV. Start with bounded
effective identity and migration-ledger inspection; never print user/credential
values in public evidence. Semantic candidate construction is separately
protected: operation `semantic_release`, executor MIGRATION_DEPLOYER,
migrations V071/V072/V073 and SEMANTIC_RELEASES INSERT capability. READ does
not authorize construction or an intentional persistent failure replay.

No documented throwaway semantic candidate/rollback invocation authorizes
historical engine reproduction. The release rollback command changes the
published pointer and is not cleanup for a test candidate. V091/V092 caller
rights, V098 procedure and V099 intended-role behavior remain UNKNOWN until a
specific safe existing DEV scope is evidenced. This laptop has no `snow`
executable on PATH at audit; no credentials were inspected, login triggered,
grant changed or live connection attempted. Continue offline engineering;
parent coordinates any existing DEV execution scope and DATA377 integration.
