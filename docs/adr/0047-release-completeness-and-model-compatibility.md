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


## Approved isolation design; pending implementation security review

The Product Owner approved three fixed RI706 fixture schemas in existing
DEV, using only a separately reviewed mode of the protected DEV workflow. This
is not authority to rewrite the live DEV ledger/pointer or broaden the current
PROD-only scoped migration guard. Synthetic owner-control fixture calls are not
scientific/Data-owner approvals and require explicit test-only scope. The
implemented fixture job binds exact source/review/image/artifact identities,
uses its own ledger and synthetic prerequisites, and exercises interrupted
installation/replay, staging, transactions, concurrency, permissions and complete
inventory rejection. The Product Owner's prospective sole-maintainer policy
replaces independent DEV peer review with native deployment authorization from
CarawayLabs (user5505084) in the separate `ri706-dev-fixture` environment.
Self-review prevention is deliberately disabled for this environment because the
sole owner may also initiate the run; administrator bypass is disabled. This is
owner execution authorization, not a GitHub PR approval or independent review.
The owner must paste the preflight's SHA256 authorization into the native review
comment. It binds repository, exact green source, V157/V158 original/rendered
hashes, fixed schemas, test-only scope, run and attempt, and a two-hour expiry.
Native approval history is checked again before credentials are used and retained
with the immutable image/migration evidence. Existing DEV credentials stay in DEV;
a successful protected authorization job is required before the fixture job starts.
Workflow tokens have read-only permissions and cannot approve deployments.
GitHub cannot distinguish a human from an agent holding the same owner credential:
credential separation remains deferred security hardening by explicit owner
direction; the existing credential may perform repository work. No agent may
submit or bypass deployment approval, change branch protection or self-grant
Snowflake privileges. None of this authorizes PROD installation,
scientific compatibility or Data publication; those separate controls remain.

Pair-only PROD installation consumes the successful isolated DEV acceptance
receipt and registry digest without deploying either operational App. The tested
source commit remains the image and migration-ledger identity. Its ordinary
merge commit must be the protected workflow's exact main SHA, contain that
source commit as an ancestor, and have an identical complete Git tree. Both
identities are retained; changed trees, incomplete receipts and digest mismatches
fail before credentials are used. Protected production authorization remains
required. Installing support objects does not admit Tier 1 compatibility,
publish model batches or move a semantic release pointer.

After a failed fixture acceptance, a fresh owner-authorized execution may reuse
the installed pair only with the prior GitHub receipt and native approval,
identical original/rendered SQL hashes, all three original schema markers and
the complete immutable two-row ledger. Keep its original installation source,
image and synthetic publication authorization; record the corrected harness's
source/image separately. No ledger rewrite, DDL replay, seed recreation or schema
reset is permitted in this resume mode. The owner digest includes the prior run
and receipt hashes, and promotion revalidates that retained installation proof.

Full retained-lineage access should reuse the existing READ audit boundary via
four exact-release/source secure projections, rather than broad base-table
SELECT or OWNER/MIGRATOR escalation. The proposed views/grants are review-only
SQL under `sql/validation/`; provisioning them in PROD requires its own protected
DDL authorization. The Product Owner approved this design, including least
privilege and confidentiality boundaries; actual installation remains separate.
Four projections expire closed on the proposed fixed date and have exact-action
hashes plus scoped revoke/drop instructions. No grant/DDL is authorized or
executed by preparation. Raw feature fields and canonical membership join the
complete source/observation comparison; predictor equality alone never passes.


### Installed DEV correction: V159

The owner-provided failed-query diagnostic for run 39188869461 proves V158's
activation guard rejected Snowflake BOOLEAN values, which JavaScript receives as
numeric 0/1. V159 replaces only that procedure, validates exactly 0/1 and a string
reason of at least 12 characters, and preserves its authorization, compatibility,
transaction and event controls. V157/V158 SQL and applied ledger rows remain
immutable. The protected fixture and scoped PROD installer include V159 in the
exact source/rendered hash manifest; native fixture authorization must explicitly
cover the added artifact. PROD execution still requires its separate authorization.
Recovery preserves original pair provenance and records V159's own source/image.
The four prior publication atomicity cases may be retained only from the hashed,
native-owner-authorized failed receipt with identical V157/V158 artifacts; all
activation, withdrawal and remaining cases run against V159. This does not reuse
prior activation evidence or authorize any real scientific/model admission.


### Restricted retained-lineage installation: V160

The Product Owner explicitly authorized the existing exact-action diagnostic
request on 2026-10-18. V160 preserves its SQL projections, release/bundle pairs,
five-source filter, multiplicities, four SELECT grants and October 25 expiry.
Its dedicated mode in the existing protected PROD migration workflow requires
native production approval, exact green main, the full reviewed pending set and
unchanged authorized SQL hashes. It executes only V160 and leaves V150 pending;
installed V157/V158/V159 receipts retain their original source identity.
Installation captures query IDs, DDL/grants and unchanged ledger/model/release
baselines. A partial DDL failure stops without automatic replacement or deletion;
inspect its receipt and use only the separately reviewed, object-matched revoke
procedure before an authorized retry. The four views return no rows after expiry;
retain aggregate evidence before scoped revocation/drop. No base-table reader
grants, role memberships, operational image promotion or scientific decisions
are performed. The diagnostic itself continues under OH_LYME_PROD_READ; neither
installation nor this authorization establishes Tier 1 compatibility.


### Retained human diagnostic proposal: V161

Actual V160 execution passed. The read-only comparison then proved equal source
pins, fixed/custom mappings, canonical membership and feature values, but cannot
complete authoritative human row lineage: historical human observations have no
persisted semantic row hash, including legitimate no-county-linked-record cases.
Do not fabricate a historical hash or treat predictor equality as a substitute.
V161 proposes one additional exact-release/version/run/artifact-scoped secure
view exposing retained human record identities, derived payload fingerprints and
bounded geography/year/selection flags. It exposes no payload, frequencies,
sex/age or URI, preserves multiplicity, rejects duplicate pins and expires with
the original diagnostic. Derived fingerprints are explicitly labeled and never
presented as historical hashes. Its new SELECT is only for the existing READ
role; no base-table reader grant or role change is introduced. The protected
workflow installs only V161 after a separate native production approval, keeping
V150 pending, V160 immutable and models/pointers unchanged. Missing dependency
access stops before DDL. The SQL hashes and exact-action request are retained
under operations/validation; V160 approval does not authorize V161 execution.
Full retained human record and absence/aggregation verification must still pass
before a scientific compatibility recommendation or human admission. Final
rollout acceptance explicitly requires Tier 1 and both latent-class models.
