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

## Environment-scoped semantic assembly correction (DATA377)

Semantic assembly checks `PRESENTATION.SEMANTIC_RELEASES:INSERT`, the actual
`semantic_release._insert_release` boundary. The desired protected executor is
`migration_deployer`, supported by V071's protected-builder design, V099 and the
protected workflow. Workflow secret role values remain unobserved.

`required_migrations` contains shared dependencies. Optional
`required_migrations_by_environment` adds dependencies only for an explicit `dev`
or `prod` plan. V099 is PROD-only in the migration runner, so only the PROD
semantic plan adds it. DEV retains V071/V072/V073 without V099. Contract validation
rejects unknown environments, missing migrations and dependencies outside the
runner's environment scope. No grants or migration history are changed.

Grant authority, effective executor, runtime capability and approval findings
remain separate even when desired executor and authority aliases match. No
observation is fabricated from policy: absent identity/privilege evidence stays
UNKNOWN; a supplied denied INSERT produces BLOCKED without self-grant or repair.
