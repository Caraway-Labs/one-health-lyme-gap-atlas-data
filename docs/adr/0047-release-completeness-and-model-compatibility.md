# 0047: Release completeness and immutable model compatibility

Status: Proposed for human scientific, engineering and access-control review
Date: 2026-10-18
Owner: Atlas Data engineering, scientific owner and production release owner
Issues: DATA #698, #702, #703

## Context

The October 15 pointer is current while the
approved Tier 1 output still retained its September input identity. The API
returns the original output; Web rejects its different release ID. Publication
checks county/observation counts and CDC compatibility, but not all independent
model or presentation consumers. Equality of release titles or row counts does
not prove scientific reuse.

## Decision proposed for review

Embed an explicit completeness inventory in every new immutable source manifest.
Before PROD pointer changes, validate all required artifacts and exact model
compatibility. After tentative pointer movement, query actual presentation views
inside the same transaction. Missing dependencies, changed required distributions,
lost API SELECT grants and unavailable models abort the transaction. The existing
protected workflow remains the only automated publication entry point.
The existing image-promotion workflow gains a bounded V157/V158 installation
scope. It reviews the full pending inventory but executes only this pair, preserves
unrelated pending/applied migrations, and reuses existing immutable ledger/legacy
authority validation. No historical receipt is reconciled or rewritten by it.

V157 retains append-only compatibility decisions independently of model rows.
Only the existing human OWNER role may admit Tier 1 reuse. Its procedure proves
complete bidirectional feature/evidence equality, canonical membership and source
lineage before recording the caller, evidence reference and exact release/bundle
pair. Installation records no decision and changes no Tier 1 output or view.
No retraining is required when this strict proof succeeds and the owner approves.
Changed scientific inputs require ML review/recomputation, not retagging.
The proof includes complete source mappings and per-observation source record
and row-hash identities, with multiplicities, compared in both directions by
canonical state partitions. Predictor equality or sampled source pins alone
cannot satisfy it. A read-only pre-approval verifier retains incomplete results
on timeout/access failure; it must not issue an admission itself.

V158 independently stores the frozen ML138 handoff. Existing ML_PUBLISHER may
stage exact chunks and publish only the approved SHA-bound v1 documents. It cannot
stage or activate until a separate Data OWNER authorization binds the actual V158
ledger commit, DEV-tested image, DEV evidence and production approval reference.
The ML handoff approval is not that authorization. The publisher cannot record it.
Failed staging attempts remain immutable in bounded separate namespaces. It cannot
approve Tier 1 compatibility or operate the rollback control. The existing human
OWNER may deactivate/reactivate the batch with an append-only event. READ receives
only the compatibility and latent-class presentation views. No new role or auth
model is introduced; inherited access and procedure dependency ownership still
require DEV and production security verification.

## Alternatives and consequences

Retagging outputs loses input lineage. Removing Web equality without an approved
relationship would admit stale results. Automatic retraining on every unrelated
data extension changes scientific outputs unnecessarily. A second release engine
would duplicate the protected path. Reuse existing storage and transactions.

Historical manifests without completeness evidence fail closed on publication
and rollback; do not modify them in place. The owner-only
`SP_ADMIT_RELEASE_COMPLETENESS` records a separate, immutable exact-bundle
admission so retained releases can be reconciled without rewriting history.
Any intentional degradation still requires its separate owner exception. No
legacy admission or completed rollback rehearsal is claimed by this proposal.

V157's separate owner-only exception procedure records an exact candidate/bundle,
artifact, expected reduced count, reason, consumer implications and rollback plan.
The guard requires that retained record; manifest-only exceptions fail. Installing
the migration approves no exception. The procedure is not granted to publishers.

## Acceptance and rollout

Offline gates and frozen-artifact replay precede human review and merge. Exercise
server-side transactions, concurrency, permission denials, replay, partial failure
and rollback in DEV before protected PROD migration/publication. The DEV current
release must satisfy the frozen batch identity; never substitute DEV predictions.
Verify all consumers under OH_LYME_API_SVC/OH_LYME_PROD_READ after deployment.
Preserve the September Tier 1 input release and add an API/Web compatibility
handoff instead of changing its existing payload identity.

## Observability and rollback

Guard failures stop promotion; retained workflow failures are operational signals.
Publication and rollback use existing semantic events; model deactivation records
actor/time/reason in V158's events. Never delete staged bytes or historical rows
to recover a failed publication. Retry identical chunks/documents. Model rollback
uses the owner procedure, leaves the batch retained and yields an empty current
view when deactivated. Model refresh requires a new reviewed version/migration.


## Pending isolation and diagnostic security review

The human review package proposes three fixed RI706 fixture schemas in existing
DEV, using only a separately reviewed mode of the protected DEV workflow. This
is not authority to rewrite the live DEV ledger/pointer or broaden the current
PROD-only scoped migration guard. Synthetic owner-control fixture calls are not
scientific/Data-owner approvals and require explicit test-only scope.

Full retained-lineage access should reuse the existing READ audit boundary via
four exact-release/source secure projections, rather than broad base-table
SELECT or OWNER/MIGRATOR escalation. The proposed views/grants are review-only
SQL under `sql/validation/`; provisioning them in PROD requires its own protected
DDL authorization. No such grant/DDL is authorized or executed by preparation.
