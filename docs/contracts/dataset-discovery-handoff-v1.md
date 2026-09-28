# Dataset Discovery governed investigation handoff v1

Owner: data platform (data #450). ADR 0041 accepts the procedure owner/security
model. Applying migrations still requires the protected ledger, and DEV proof
does not authorize PROD promotion.

## Boundary

Only an immutable recommendation version whose **current** human review state
is `ACCEPTED_FOR_INVESTIGATION` may enter the data-owned investigation queue.
The exact review event, authenticated reviewer, run, catalog dataset/resource,
canonical `resource_key`, evidence snapshot and evidence observation IDs travel
with the request. Transport clients submit only the version ID and current
review event ID. They cannot provide a reviewer name, rights finding, catalog
identity, or disposition. The procedure derives those from committed records.
The forward V113 procedure also verifies that referenced catalog observations
belong to the recommendation's pinned discovery run. A matching observation ID
in another run is insufficient for investigation intake.

One logical handoff key is `handoff-v1:<recommendation_version_id>`. The server
derives its ID with SHA-256, serializes admission with `WRITE_SERIALIZATION`,
and commits the request plus receipt in one transaction. A lost response is
recovered by repeating the same call or reading the receipt. A different event
for the same version is a stale/conflicting request. Snowflake uniqueness
declarations are not treated as enforcement.

The queue is investigation intake only. It creates no `SourceDefinition`,
`DATA_SOURCE_VERSIONS`, `MANUAL_REVIEW_DECISIONS`, ingestion run, approval,
publication, or payload acquisition. Governed operators investigate
documentation, rights, access, sampling and assessment using existing controls.
The queue view exposes only bounded metadata and references, not catalog
payloads or private artifact bytes.

## Rights and outcomes

`RIGHTS_UNKNOWN` and `RIGHTS_REVIEW_REQUIRED` are valid investigation inputs.
`CONTROLLED_ACCESS` sets `NO_AUTOMATED_ACQUISITION`; it is not a prohibition.
An independently reviewed `KNOWN_RESTRICTED` finding also remains
investigable, with a restricted access boundary. Only a current, reviewed
`KNOWN_PROHIBITED` policy finding for the exact resource can return
`POLICY_BLOCKED`. That policy ledger is governed owner managed and cannot be
written by the agent or reviewer command. Without a reviewed finding, unknown
rights never become a hard block.
V113 requires nonempty reviewer and evidence-reference values before a rights
finding can support a hard policy disposition.

The handoff receipt carries the original relationship type, so an accepted
mirror or alternate distribution is distinguishable and can be investigated
against its canonical resource. The handoff result vocabulary is `HANDED_OFF`, `ALREADY_GOVERNED`,
`POLICY_BLOCKED`, `REJECTED_OR_STALE`, `MISSING_EVIDENCE`,
`RETRYABLE_FAILURE`, `TERMINAL_FAILURE`. A duplicate/mirror relationship is
retained in queue metadata for investigation rather than silently discarded.
Exact retries return the original logical receipt. Already governed resources
produce an auditable handoff receipt without a duplicate investigation task.
The client classifies transient transport/database errors as retryable; the
procedure does not forge a durable failed receipt for a rolled back transaction.

## Security and application

Only the approved authenticated human reviewer role may call the admission
procedure. The unattended Dataset Discovery runtime can read a narrow receipt
view if the role ADR explicitly grants it; it has no procedure invocation or
governed onboarding DML. The owner-rights procedure requires a dedicated
nonlogin owner with direct dependency grants and `READ SESSION` to recover the
caller principal; those grants and deployment ownership await owner/security
review. DEV and PROD have separate objects and identities. The data platform
must demonstrate that its intake operators consume the queue and that the
existing approval/ingestion boundaries remain authoritative before closure.
