# 0042: Internal semantic lineage audit projection

Status: Proposed for product and engineering access-control review
Date: 2026-10-05
Decision owner: Atlas product and data engineering
Issue: DATA #604, parent DATA #605

## Context

ADR 0030 separates READ, OWNER, RUNTIME and MIGRATION_DEPLOYER. Live PROD grants on 2026-10-05 show OWNER can SELECT semantic observations, RUNTIME can SELECT conformed records, and neither is the intended single read-only audit identity. PROD `PRESENTATION` is ACCOUNTADMIN-owned; the migration identity has semantic-table SELECT but no CREATE VIEW there. The migration identity has database CREATE SCHEMA and owns or reads the required source-record relations.

## Decision

Create the dedicated `LINEAGE_AUDIT` schema and one secure view through the environment's protected migration identity. Grant the existing environment READ role only schema USAGE and view SELECT. The view exposes the exact keys, IDs, and hashes required to validate semantic observation → release → source version → run → artifact → immutable revision or legacy conformed record. It excludes payloads and private artifact locations. See the [field contract](../contracts/semantic-domain/data-604-lineage-audit-v1.md).

## Alternatives considered

An owner-rights procedure adds an execution interface and code for a relational read-only use case. Extending a public/current-release projection would expose internal artifact identifiers and hide historical release rows. Granting OWNER access to conformed base tables, or RUNTIME access to semantic base tables, would weaken ADR 0030. Adding a new role would increase role and connection count. Giving the migration role CREATE VIEW on an existing ACCOUNTADMIN-owned schema would require an unrelated privileged bootstrap grant.

## Consequences

READ receives only object-level audit evidence and no base-table or write privilege. The new schema is dedicated to this view, so its USAGE grant gives no access to other objects. DEV and PROD remain separate. The view is internal and must not become a public API response.

## Acceptance and rollback

Source checks and fixture tests are necessary but insufficient. DEV and PROD each require protected migration application, effective-grant inspection, a single READ identity query with a unique authoritative lineage match, and negative checks on base-table and DML access. Rollback is a reviewed forward migration revoking only this view's SELECT and this schema's USAGE from READ, then dropping this view and its now-empty dedicated schema. Source rows, semantic releases, pointers, and owner/runtime/migration grants are untouched.
