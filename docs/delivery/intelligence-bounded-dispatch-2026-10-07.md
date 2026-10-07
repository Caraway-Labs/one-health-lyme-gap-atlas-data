# Bounded prerequisite and acquisition-only dispatch

The exact feed prerequisite workflow branch selects its reviewed checksum locally,
rejects mixed diagnostics and missing forward-accounting confirmation, and invokes
the existing50-second CLI before either standalone Snowflake identity/ledger read.
Inside that deadline the dedicated migration-service identity is verified using
the existing10-second session limits. Generic migration/diagnostic paths remain.
No new credentials, SQL execution surface, migration number or runner is added.

The existing ingestion workflow adds one false-by-default boolean for approved
DEV/TierB feed acquisition only. It accepts only operation=run, the two approved
feed definition paths, no existingrunid, publish=false and recapture=false. Invalid
combinations fail local validation; Spaces readiness is not invoked by this flag.
The existing CLI receives --fail-after-stage ACQUIRE. Its owned300-second watchdog
and identity check cover all Snowflake work; the former untimed identity probe is
skipped only in this validated mode. HTTP/raw/item/query limits remain unchanged.

This is the established failure-injection stage stop: ACQUIRE completes durably,
then the orchestrator records an intentional failure before NORMALIZE. The Actions
job may report failure. No generic exception/exit is swallowed or renamed success.
Use its persisted stage/artifact receipt to assess capture, not overall jobgreen.
Native/source/retention authority is still required; this option bypasses none of
those facts. It does not deliver normalization, itemstorage or readeracceptance.

Offline executable shell cases cover both approved feed definitions and invalid
operation/environment/tier/runid/publish/recapture/source selections. Role tests
reject wrong service user, role, database orwarehouse; routing tests confirm both
standalone prereq reads are unreachable in the bounded branch and legacy modes
cannot select it. No dispatch, SQL, grants or acquisition occurred. ForwardUS$8 is
separate from unreconciled historical charges; warehousecostevidence remains held.
