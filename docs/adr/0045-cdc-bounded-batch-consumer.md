# 0045: CDC bounded batch consumer with one-statement shared proof

Status: Proposed for implementation review; product owner explicitly authorized
Option C implementation/tests/benchmarks/PR/independent review on 2026-10-17.
Merge and production deployment remain unauthorized.

Decision owner: Atlas product owner, Data engineering and scientific stewardship.
Tracking: API #248. Contract: [CDC batch v1](../contracts/semantic-domain/cdc-consumer-batch-v1.md).

## Context

The existing request-owned connection still executes identity/authority reads
per county. The investigation found about 1.667M JSON characters of authority
per county, almost entirely repeated full review packets; prior diagnostics also
showed multi-second secure-view compilation. Those timings are not an API SLO
or proof of a future batch latency gain.

## Decision

Add an optional typed versioned Data-owned Python producer for 1–50 counties of
one exact release/measure/source tuple. Keep singleton functions unchanged.
Borrow the caller's exclusive reader callback; read only the existing secure
authority view. One parameterized authority statement returns shared complete
review/receipt proof once plus bounded county facts, asserting identical shared
proof on every retained row. Validate exact requested membership and every row
through existing immutable metadata, physical/semantic admission and safe
projection. Return everything or a fixed safe error.

Use one statement rather than separate anchor/facts reads. Snowflake READ
COMMITTED can observe different committed state across successive statements,
even in one transaction. A single authority statement binds shared proof and
county facts to the same statement snapshot without session or isolation changes.
See [Snowflake transactions](https://docs.snowflake.com/en/sql-reference/transactions).
The earlier identity SELECT is an environment check, not scientific authority.

## Alternatives considered

Two-statement shared proof/facts transport (the publication gate's precedent)
adds a runtime consistency problem. Per-county full proof repeats transport and
compilation. View simplification and persisted serving projections expand scope
and require broader equivalence/freshness controls; neither is authorized here.
Cross-request admission caching is excluded.

## Consequences and acceptance

One authority round trip and shared-proof copy per bounded batch; internal SQL
may still compile/scan expensively. Secure equality may fail closed on different
array order. No DDL, source/metadata/admission change, grant or new base access.
Keep ADRs 0042–0044 and the pre-publication compatibility gate intact. Test every
record, exact singleton parity, current/historical metadata, exclusions, duplicates,
missing/mixed records, safe failure, payload bound and cancellation. Record live
read-only versus synthetic evidence separately; do not infer cold-cache behavior.

## Rollout, observability and rollback

Run repository gates and independent review; stop before merge/deploy. No private
authority or SQL parameters in public logs. Future API integration pins reviewed
Data and retains the request-owned connection/public behavior. Protected rollout
requires separate approval. Rollback selects the previous approved producer pin;
scientific history, receipts, view definitions and release state remain untouched.
