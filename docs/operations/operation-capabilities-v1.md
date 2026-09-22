# Curated operation capability contract v1

The machine-readable contract is
[`config/operation-capabilities-v1.yml`](../../config/operation-capabilities-v1.yml).
It intentionally covers only forward migrations, governed source runs,
semantic release, and API reads. It maps a target environment to an expected
executor, distinct grant authority, bounded capability, migration dependency,
and approval class.

It is desired policy derived from ADR 0030, the connection inventory, and
checksum-locked migrations. A preflight report is observed evidence at one
time, not a replacement for those sources and not authorization. Runtime
roles never self-grant and never approve sources. DEV observations never
satisfy PROD requirements.

`pipeline preflight --operation ... --environment ...` reports `PASS`,
`BLOCKED`, or `UNKNOWN` and always reports `mutation_started: false`. A missing
or uninspectable fact is `UNKNOWN`; it blocks the relevant consequential step
without asserting a defect.

For an authorized live identity and migration-ledger observation, pass both
`--inspect-live` and the exact least-privilege named connection, for example
`--snowflake-connection ATLAS_DEV_READ`. This runs only fixed `SELECT` queries;
it does not inspect arbitrary SQL, execute DDL/DML, grant privileges, or record
an approval.

With a named connection, the preflight also issues one fixed `SHOW GRANTS TO
ROLE` query for the contract-mapped executor and compares only the contract's
listed capabilities. A missing observed direct capability is `BLOCKED`; grant
authority and approval remain separate findings and are never repaired.

The read-only inspector is not the operation executor. Its successful identity
observation proves that the preflight ran in the intended environment; the
executor identity remains `UNKNOWN` until it is revalidated immediately before
the separately authorized consequential operation.
