# DATA #698 / #702 release integrity

This implementation is pending review and DEV validation. No migration installation,
compatibility approval, Tier 1 restoration or latent-class PROD publication is implied.

## Current findings, 2026-10-18

Named PAT contexts were checked before reads. PROD runtime audit confirms current
`governed-2026-10-15-january-climate-prod`, bundle
`53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d`,
3,144 counties, 44,030 semantic observations and zero missing observation lineage.
Human READ-role SQL confirms Tier 1 has 3,144 stored rows: HIGH 315, MEDIUM 628,
LOW 2,201. Excluding AK/HI: 3,109 = HIGH 315, MEDIUM 593, LOW 2,201. All 3,144
model rows retain September 18 release identity; zero match the current release.
Do not confuse the all-county 628 MEDIUM with supported CONUS/DC 593 MEDIUM.

The real public API returned HTTP 200 and authoritative HIGH/MEDIUM/LOW for
36001/01003/01001, each with September model lineage. Web
`present-tier1-surveillance-priority.ts` rejects differing release IDs. The Data
V141 view contains no release compatibility condition. `semantic_release.py`
previously gated county/observation counts, restricted final-copy, climate and CDC
authority, but did not reconcile model consumers. This is an orchestration and
consumer-compatibility defect; stored output loss is not the observed failure.

READ-role current observation queries show four context SVI measures and RUCC
with 3,144 rows each, three human measures with 3,144 rows each, and seven NLCD
measures with two rows each. NLCD covers only 09110 and 51013. Climate has 389,856
rows (four measures x 31 January 2025 days x 3,144 county identities). A row is
not necessarily source-supported: preserve its coverage_status/value_state;
do not extrapolate observations to AK/HI or fill missing support.

The local ATLAS_PROD_READ connection authenticates MATTHEWCARAWAY, not the API
service. Its successful SELECT is role evidence only. Runtime audit lacks SELECT
on Tier 1/base semantic observations; this was not worked around with ACCOUNTADMIN.
The subsequent checksum-bound input comparison proved equality of all six Tier 1
predictors across 3,144 counties (18,864 cells), with zero changed evidence/context
fields and identical membership. See
[`tier1-input-comparison-2026-10-18.json`](tier1-input-comparison-2026-10-18.json).
The original CSV SHA is `84caef339dd87ad85e2b72be4bddfee6ec40412e803cdf926fc3c3e104b98bf2`;
the ML projection is byte-equivalent to approved source 024bbbf. The read checked
the current release before and after capture and retained all row identities.
Only the aggregate receipt is committed. This supports proposed carry-forward;
it neither approves it nor replaces the owner procedure's independent source
lineage/mapping/hash comparison. Service-user permission proof remains pending.

## Frozen handoff

ML source c186e0bdc9ee096a15284bc848de034981fe634b contains the approved handoff,
manifest, schema, approval and dictionary. The reviewed assembly script replays
stored assignments without refitting. Its county file is 5,170,756 UTF-8 bytes;
SHA-256 `02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b`.
Data's verifier independently checked frozen bytes and both 3,144-county fits.
Class distributions are primary 801/35/112/2196 and secondary 1325/1687/97/35.
Unknown is exactly the 35 AK/HI rows and is a genuine class.
Public metadata copies under `docs/contracts/surveillance-situations/` retain
the upstream bytes. County assignments remain outside Git.

## Implementation and approvals

1. Review ADR 0047, V157/V158, frozen pins and release guard. V157 installs an
   empty compatibility ledger; it grants only OWNER the admission procedure.
   V158 installs empty latent-class batch tables and publisher procedures.
2. After review/merge, use existing checksum-validated DEV migration workflow.
   Verify procedure owner dependency reads, exact replay, partial failure, changed
   bytes, duplicate FIPS, invalid probabilities, class counts, writer serialization,
   rollback and publisher/base-table denial. DEV acceptance must use the frozen
   release identity; do not move DEV's live pointer or manufacture its approval
   simply to make a test pass. Record the concrete DEV prerequisite if absent.
3. Reuse the reviewed DEV-tested image digest through protected PROD promotion.
   Obtain explicit approval of exact migration checksums and added view/procedure
   grants. Do not call production procedures from this preparation session.
   Select `release_integrity_only=true` in existing `promote-prod.yml`, with exact
   `reviewed_commit`, DEV-tested `image_digest` and the complete reviewed
   `expected_pending_json` (including unrelated deferred entries). It installs only
   V157/V158. V150, V154 or other pending DDL is preserved, not implicitly approved.
   The runner verifies current release/bundle and every unrelated ledger row before
   and after. A partial retry requires exact source checksums and the same reviewed
   deployment commit. Contradictory operation flags fail before DDL.
4. Owner reviews full feature/lineage comparison and approves a specific Tier 1
   compatibility decision. The procedure independently rejects changed values,
   membership or scientific source lineage. It never edits original model rows.
5. After explicit Data production authorization, OWNER records a separate
   `SP_AUTHORIZE_SURVEILLANCE_SITUATION_PUBLICATION` decision naming the reviewed
   V158 deployment commit, DEV-tested image digest, DEV evidence and approval
   reference. The procedure requires the real V158 ledger receipt and frozen
   current release identity. ML handoff approval alone cannot stage or activate
   this batch. ML_PUBLISHER cannot record the Data owner decision.
   Publish approved ML138 chunks/documents using the service publisher's named
   PAT connection only after the production operation is approved:
   `uv run python scripts/publish_surveillance_situations.py <frozen-ML-root> --publish --environment prod --connection <named-PAT> --authorization-id <owner-decision>`.
   Default without `--publish` is entirely offline. No PAT values enter arguments.
6. Reconcile a reviewed new candidate's `release_completeness` manifest. Do not
   modify the current release manifest in place. Pre-pointer and transaction-local
   post-pointer checks are mandatory for both publication and rollback. A retained
   release may receive a forward, owner-only `SP_ADMIT_RELEASE_COMPLETENESS`
   record bound to its exact bundle. This preserves its original source manifest.
   Review and record any degraded-release exceptions separately before admission.

## Downstream contract and remaining acceptance

API #253 may consume `PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V`:
county_fips, model_id/version, version-scoped class_id, ordered probabilities,
class_name/description, limitations, batch_id/version, county/dictionary digests,
active release/bundle, original input release/bundle, fit Git SHA, feature contract,
handoff approval, original source vintages/limitations and activation time. Both
variants remain independent. The companion
`PRESENTATION.COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V` provides per-county,
per-fit AVAILABLE/UNAVAILABLE and NOT_PUBLISHED, DEACTIVATED, UNAPPROVED_BATCH,
INCOMPATIBLE_RELEASE or MISSING_ASSIGNMENT reasons. Genuine Unknown retains
AVAILABLE with its real class ID. Empty
view means no eligible batch; it never means Unknown or zero. This is descriptive
surveillance evidence, not risk, incidence, pathogen absence or Tier 1 priority.

Tier 1 API/Web owners must consume the explicit
`PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V` relation or an additive reviewed API
projection. Existing Tier 1 release_id remains the immutable input release.
The current Web equality check will continue to reject it until that downstream
contract is implemented. Data alone cannot claim UI restoration.

Post-deploy canary must run as OH_LYME_API_SVC/OH_LYME_PROD_READ, select every
required presentation view and prove base-table/publisher access denied. Record
full Tier 1 stored vs eligible scope, samples, both latent-class distributions,
probability sums, class dictionary, AK/HI, and missing/incompatible/deactivated
behavior. Reconcile actual geographic/time support for all inventory artifacts.
Do not close #698/#702/#703 until their production acceptance is demonstrated.

## Rollback and failure

Identical chunk replay recovers interruption; modified bytes fail. Publication is
staged under an immutable attempt ID. If a wrong chunk has already occupied an
attempt, select a new `--staging-attempt` before approval; retain the failed parts
as evidence. Never delete or overwrite them to recover publication. The approved
batch records which attempt supplied its exact frozen bytes. Up to eight attempts
are retained; exhaustion requires owner review, not deletion of evidence. Publication is
one transaction and retains the previous pointer on failure. OWNER may call
`FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(FALSE,<reviewed-reason>)` to
withdraw the new model; TRUE restores v1 only while its exact release/bundle
matches. Both actions append an actor/time/reason event. No historical assignment
is changed. Coordinate expected unavailable API/UI behavior before withdrawal.

Intentional degraded releases require a separate owner-recorded decision through
V157's `SP_APPROVE_RELEASE_COMPLETENESS_EXCEPTION`, binding the exact candidate
release/bundle, artifact, expected reduced count, reason, consumer implications
and rollback plan. This version rejects all manifest-only exceptions. Installation
records no exception. Publishers cannot execute the owner procedure.

Production service canary provisioning requires protected environment secrets
`ATLAS_API_CANARY_PRIVATE_KEY_PEM_B64` (complete PEM encoded as base64) and,
if encrypted, `ATLAS_API_CANARY_PRIVATE_KEY_PASSPHRASE`, for OH_LYME_API_SVC.
The production environment currently has neither. The account/security owner must
provision these directly; never copy them into chat, local files or Git. The
protected workflow checks provisioning before any publish/rollback pointer write
and runs the real service-identity verification afterwards.
It consumes the exact current release's reviewed completeness projection, including
separately retained owner exceptions; it does not apply a hardcoded full-coverage
profile to an intentionally degraded release. The completeness manifest must
contain only non-secret lineage references, never private artifact URLs or tokens.

DEV currently points to `governed-2026-10-09-january-climate-dev`, bundle
`67cdf470a8c39973251d8325777132a840f63ee42b67f129973936c30e66d9f4`.
That differs from the approved ML138 frozen input. Positive server publication
validation therefore needs a reviewed DEV validation plan with the frozen release
identity; the existing DEV pointer was not changed to satisfy this prerequisite.

## 2026-10-18 exact-head follow-up

See `release-integrity-acceptance-2026-10-18.md` for the review disposition,
actual read-only Snowflake query receipts and remaining installed DEV gates.
`verify_model_source_lineage.py` is a read-only pre-approval verifier: it checks
retained source metadata and complete manifest mappings first, then compares
all model-source observation lineage with multiplicities in bounded state
partitions. Each CLI statement has a 60-second timeout; receipts remain
incomplete on failure. Audit row counts must equal base observation counts,
so inner joins cannot silently hide missing provenance. No approval is recorded.
The current READ role cannot access retained manifests; do not grant broad base
access or substitute sampled lineage. Use a separately authorized, least-privilege
protected diagnostic with those existing dependency reads. V157 independently
repeats source/mapping and bidirectional per-state observation-lineage checks
before an OWNER can record compatibility. Its result reports partitions/rows.


## Isolated DEV and human review preparation

The current gate-by-gate package is
[release-integrity-human-review-package.md](release-integrity-human-review-package.md).
It includes fresh named-READ access probes, exact minimum diagnostic grants,
fixture-only migration rendering/checksums and an installed acceptance matrix.
The proposal renderings are not an executable/deployed scoped migration mode.
Do not run the generic DEV migration entry point: its observed pending set also
includes V155. No GitHub environment reviewer restriction was inferred; the
blocker is the absence of a reviewed scoped DEV fixture mechanism.
