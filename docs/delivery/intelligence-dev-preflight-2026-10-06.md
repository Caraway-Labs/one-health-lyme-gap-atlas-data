# Fixed protected DEV intelligence metadata preflight

Add one read-only option to the existing DEV workflow using its existing service
identity and warehouse. It exits before migration application and refuses mixed
modes. Targets are two retention metadata tables, source-version registry, and
V1/V2 feed views. Missing visibility remains unknown rather than presumed absent.
No registry rows or documents, source HTTP requests, source approval, source
registration, DDL, grants, or cleanup operations are included.

Only public-safe fixed target tokens and boolean inspection/owner/version-literal and exact reviewed-definition
statuses are emitted. Actual owners, columns, grants and view DDL remain transient
in process memory. Presence of a version literal is preliminary evidence requiring
exact definition review; a separate conservative token comparison checks the reviewed body without exporting SQL. No artifacts,
encryption keys or credentials are added. Completed safe object observations are
emitted progressively and retained if a later inspection fails. The 50-second watchdog exits without evidence I/O, independently of blocked/broken output. Statements
have ten-second limits. No exception message is emitted.

The public boolean accounting input confirms independently reconciled private
forward-only allowance covers this bounded diagnostic, including
idle/service overhead and other reserved spend. It contains no dollars, pricing,
private evidence references or request receipts. This is an attestation gate, not
a billing meter. Historical charges are separately unreconciled and are not asserted by this forward-only confirmation; the
private financial evidence stays with the authorized reviewer outside Actions.

Offline tests cover wrong identity, accounting gate, unknown visibility, partial
safe evidence, public input surface and workflow branch ordering. Hosted Quality
remains required. No live query, grant, DDL, deployment or paid feed execution.
Source/native policy, exact schema/definition review and physical-retention
prerequisites remain separately gated.

The readiness follow-up compares all returned table columns against fixed approved
names/types/nullability/defaults, and each target role's privileges against its
fixed expected set. Missing privileges, extras and grant option are separate
booleans; no raw metadata is emitted or automatically repaired. The three newly
approved scopes remain documents SELECT/INSERT, audit INSERT and V2 READ SELECT.
Comparisons reuse existing DESCRIBE/SHOW GRANTS results and add no queries.
