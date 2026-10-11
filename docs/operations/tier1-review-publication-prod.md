# DATA #627: pinned Tier 1 PROD publication

V141 is the PROD-only counterpart of DEV V140. It admits only the final ML #104
post-merge batch `tier1-review-priority-5536b5caad95cf47` with canonical digest
`45e711465c2176b5a5b88f7eb23993a4e824a005f03b45e6abdf6171c81aca12`.
It leaves DEV feature v1 and its migration unchanged. This is a surveillance
review priority output, not a disease-risk or incidence estimate. The selected
model, evaluation, tier policy, and six predictors are unchanged. The PROD vector
context differs from DEV and is not a selected-model predictor.

## Source and admission

The operator-preserved files are in
`C:\Users\caraw\Documents\Codex\2026-10-06\ml-104-final-prod-publication-artifacts`.
Before a Snowflake call, `scripts/publish_tier1_review_prod.py` verifies every
physical hash recorded in `handoff-status.json`, the status identity, manifest,
lineage, 3,144 sorted unique county FIPS, the sorted-LF FIPS digest
`4a74ab4f8638b4a02a18b0db4abe9597fc2a6bf364a103314de346338015c690`,
materialized HIGH 315 / MEDIUM 628 / LOW 2,201, SUFFICIENT 651 /
INSUFFICIENT 2,493 / NOT_ESTIMABLE 0, and canonical output digest. Do not
regenerate or substitute an ML batch. The operator stages at most 200 rows per
call using the original canonical Python row strings; V141 validates those
strings and hashes them without VARIANT reserialization.

The exact PROD admission is ML source commit
`024bbbf74a7da8e54566bd60e8e762d85a51e24f`, generated UTC
`2026-10-07T02:14:24Z`, feature `tier1-county-features-v2`, model
`tier1-statistical-reference-v1`, evaluation `tier1-selection-evaluation-v1`,
tier policy `tier1-review-percentile-v1`, governed release
`governed-2026-09-18-unknown-coverage`, and bundle SHA-256
`038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026`.
V141 independently requires exactly that published release and 3,144 unique
source FIPS in `PRESENTATION.SEMANTIC_COUNTY_ATLAS`, comparing both FIPS-set
directions before activation.

## Protected security and migration

1. Review and merge the exact PR head after hosted Quality and human peer review.
   Confirm the merged `origin/main` commit and the DEV-tested immutable image
   digest required by `.github/workflows/promote-prod.yml`.
2. A separately authorized account owner reviews the exact grants and executes
   `scripts/bootstrap_tier1_review_roles_prod.sql` after recording effective
   user, role, database, and warehouse. Inspect any pre-existing role and grants;
   stop on drift. The non-login `OH_LYME_PROD_TIER1_PUBLICATION_OWNER` gets only
   the object creation, semantic source reads, temporary migration-ledger rights,
   and warehouse rights needed for V141. The migration service user temporarily
   receives this role. The distinct `OH_LYME_PROD_ML_PUBLISHER` gets database,
   FEATURE_STORE schema, and warehouse usage only at bootstrap; V141 grants it
   usage on the three publication procedures. No DEV credential is reused.
3. A separate security onboarding action mirrors accepted DATA #625 with one
   PROD `SERVICE_AGENT`, proposed name `OH_LYME_PROD_TIER1_ML_PUBLISHER_SVC`,
   holding only `OH_LYME_PROD_ML_PUBLISHER`, a dedicated PAT-only policy, and
   exactly one PAT restricted to that role. Use a distinct named connection,
   proposed `ATLAS_PROD_TIER1_ML_PUBLISHER`, with `secondary_roles=NONE`. Verify
   its effective user, role, database, warehouse, and role assumption denial.
   Revoke any temporary operator publisher-role and user-scoped PAT-mint grants
   before acceptance. Never put PAT bytes in files, workflow logs, or this
   runbook. No owner/admin identity may substitute for the publisher during
   batch calls.
4. Before protected deployment, inspect the PROD migration ledger and exact
   pending checksum set. Dispatch `.github/workflows/promote-prod.yml` only
   with an approved DEV-tested image digest. Confirm V141 ledger entry, the four
   tables, three procedures, current view, ownership, and explicit grants.
   Retire the owner's temporary `CREATE TABLE`, `CREATE PROCEDURE`, `CREATE VIEW`,
   migration-ledger `SELECT, INSERT`, GOVERNANCE schema usage, warehouse usage,
   and migration-service role assignment after the ledger receipt, following
   the reviewed DEV V140 pattern. Preserve the owner's semantic source reads
   and object ownership for owner-rights procedure execution.
5. Recheck the PROD release, bundle, and county population immediately before
   publication. Run the offline check, then publish through the named PROD PAT:

   ```powershell
   uv run python scripts/publish_tier1_review_prod.py 'C:\Users\caraw\Documents\Codex\2026-10-06\ml-104-final-prod-publication-artifacts'
   uv run python scripts/publish_tier1_review_prod.py 'C:\Users\caraw\Documents\Codex\2026-10-06\ml-104-final-prod-publication-artifacts' --publish --connection <reviewed-prod-ml-publisher-connection>
   ```

The three procedures serialize writers by updating a precreated lock row.
Identical stage bytes and an approved same-digest retry are idempotent;
changed rows or digest, incomplete batches, duplicate FIPS, invalid lineage,
reasons, or tiers fail closed. The approved state and active pointer commit in
one transaction. Informational Snowflake uniqueness constraints are not used
for enforcement. Failed publication keeps the prior approved pointer and rows.

## Acceptance and least privilege

Under the intended production read role `OH_LYME_PROD_READ`, record
`CURRENT_USER()`, `CURRENT_ROLE()`, `CURRENT_DATABASE()`, and
`CURRENT_WAREHOUSE()`; prove view SELECT and representative HIGH, MEDIUM, and LOW
FIPS with all 20 API #10 fields. Prove base FEATURE_STORE SELECT, publication
procedure usage, and mutation denied. Under the PROD publisher, prove direct
base-table DML denied. Verify the active pointer, exact approved batch digest,
governed FIPS set, versions, and tier/sufficiency counts with bounded queries.
Preserve query IDs and redacted results in DATA #627. This is data access proof,
not the deployed API runtime canary; API #197 owns that canary.

Use accepted DEV V140 evidence for adversarial cases that cannot safely be
exercised against the authoritative PROD batch, and label it as DEV evidence.
Safe PROD probes include an incomplete finalize before publication and
same-digest retry after approval. Never stage a synthetic county into the
authoritative PROD batch.

## Rollback

Before V141 publication, the active pointer is empty. After publication, retain
the approved batch and all historical rows. If a later separately approved batch
replaces it, restore the previous approved batch only through a reviewed,
forward-only migration or explicitly governed owner-rights activation procedure
that validates its retained digest, approved state, and governed source lineage,
then changes the active pointer transactionally under the publication lock.
Do not directly update the pointer, delete rows, rewrite the migration ledger,
or call a publisher procedure with a substituted batch. If API rollout fails,
API #197 can roll back its runtime independently while Data retains this batch.
