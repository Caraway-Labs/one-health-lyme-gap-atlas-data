# DATA #429 CDC county consumer review package

Status: **PENDING scientific/data review; not production admission.**
Owner: Atlas data stewardship. Engineering authorization is the October 11
DATA #429 consumer admission vertical slice. This package uses #190 measure,
#191 metadata, #193 lineage and #194 consumer contracts; it adds no persistence,
source registry, ontology, public view or deployment workflow.

## Documents and exact scope

- `scapularis_status.metadata.json`: proposed measure `scapularis_status:1.0.0`,
  metadata revision 1; CDC Ixodes scapularis county status.
- `burgdorferi_status.metadata.json`: proposed measure `burgdorferi_status:1.0.0`,
  metadata revision 1; CDC Borrelia burgdorferi county status for that tick.
- `release-binding.json`: the two exact resource/dataset/source-version tuples
  and the existing canonical release/bundle. This binding is scope, not consent.

Each metadata document validates with `semantic_metadata.validate_metadata` and
carries an immutable content hash and meaning signature. The synthetic #191
examples are not prior live definitions or scientific approval. These are new
live-source candidates, not replacements for an applied measure revision.
The metadata visibility describes the proposed safe projection, while PENDING
review prevents publication. No reviewer identity or date has been invented.
Unknown publisher dates, retrieval freshness, uncertainty and unverified quality
references retain explicit unknown/unavailable states rather than guessed facts.

## Exact authorized-reviewer decision

Approve or reject both candidate scientific definitions, unit `status`, no
denominator, county grain, cumulative period through 2025-12-31, source/version
binding, restrictions, limitations, original-status preservation and these rules:

| Publisher/evidence | Additive normalized_state | Interpretation |
| --- | --- | --- |
| Tick Established | established | Publisher category; no invented threshold |
| Tick Reported | detected | Establishment criteria not documented as met |
| Pathogen Present | detected | Publisher-backed positive detection |
| Publisher No records | unknown | Preserve NO_RECORDS, never infer absence |
| Missing/unsupported | unknown | Preserve canonical state; never infer negative |
| UNKNOWN_SOURCE_COVERAGE parity placeholder | unknown | No publisher lineage or admission |

The decision must authorize only the existing allowlisted semantic/evidence
projection for the exact release slice. Raw workbook, derivation/evidence run
IDs, artifacts, row/workbook hashes, physical record IDs and final-copy details
remain restricted. A source approval or final-copy attestation alone is not
approval of these semantic definitions or consumer exposure.

On approval, retain revision 1 PENDING unchanged. Create metadata revision 2,
record the actual review date in `steward_review.reviewed_at`, set REVIEWED,
and set field authority to STEWARD_REVIEWED only for fields actually reviewed.
Recompute `revision_id`; keep the meaning signature if the meaning is unchanged.
A scientific definition change requires the existing #190 version review rather
than silently replacing version 1.0.0. Retain the actual reviewer and signed
decision/reference in the existing governed review/release packet; the #191
document has no reviewer-name field. Bind only the accepted immutable revisions
to that reviewed packet's release authority. Engineering tests use fabricated
reviewed revisions and attestations, explicitly labeled synthetic.

## Existing authority snapshot and narrow CDC joins

The trusted server-side adapter supplies the existing #193 `source_versions`,
`runs`, `artifacts`, `records` and `releases` snapshot. It must derive the source
`approved` field from the existing source decision and applicable conditions,
never from a caller request. No new caller-selected approval argument exists.

For these exact CDC tuples, a record retains `evidence_run_id`,
`workbook_sha256`, `resource_key`, `source_definition_version`, `county_fips`,
publisher status under its measure ID, and `coverage_state`, in addition to
the existing generic record IDs, hashes, derivation run and source version.
The artifact belongs to the evidence run and its source version; the evidence
version must be approved and match the derivation source's publisher, source,
dataset, resource and vintage. The generic record join still requires exact
derivation run, artifact, source version, source record, row hash, canonical
record and revision. CDC additionally verifies workbook hash, county and status.
Missing row hashes and parity placeholders cannot enter as publisher records.
Non-CDC generic lineage and the approved climate path remain unchanged.

For consumer admission, the existing exact release authority additionally carries:

- `metadata_revision_ids`: immutable revisions admitted by the reviewed release
  packet, not a user-selected allowlist or metadata PENDING hash.
- `observation_records`: physical release observation ID to authoritative record
  ID, assembled from the validated V148 join, preventing unrelated memberships
  from being combined into one claim.
- `restricted_source_publication_attestations`: retained V087 attestation rows
  with exact release/resource/source-version, attestation ID, actual attester,
  delivery reference and delivered timestamp. These private rows stay internal.

Existing release bundle, observation IDs and semantic revision membership remain
mandatory. CDC admission is recalculated by the lineage validator as well as
the mapper, so changing a visibility value cannot bypass it. PENDING metadata
can map to INTERNAL for technical validation, but the consumer rejects it.
Reviewed yet unadmitted metadata also remains INTERNAL. No climate admission is
reused for CDC. Consumer record references use semantic observation keys rather
than restricted physical CDC record IDs.

## API #88 handoff and remaining production action

API PR #224 has merged the compatible optional resolver seam. Its source is
Data's existing `surveillance_evidence_mapping.project_surveillance_evidence`
(`atlas-surveillance-evidence-consumer-v2`), containing the existing semantic
consumer v1 and evidence v3 with additive `normalized_state`. The API consumes
the Data field and preserves source label, canonical state, county, period,
source/version, metadata revision and exact release/bundle. It must not classify
raw labels independently or use restricted proof tables as public output.

This increment adds no production materialization, API credentials or resolver
activation. After actual review, the approved release packet's intended-role
adapter can call the existing writer with its authoritative snapshot. Before
activation, repeat genuine intended-role consumer readback for the previously
verified tick Reported, positive pathogen Present and publisher No records
records; retain private proof locally. The originally requested pathogen
unknown-coverage placeholder is not a positive source record. Missing evidence
remains unavailable/unknown under the API's existing fail-closed contract.

Protected action: merge the independently reviewed, Quality-passing engineering
PR only when authorized; deploy that exact reviewed commit through `quality.yml`
with `deploy_dev=true`; verify DEV and promote its immutable image digest using
`promote-prod.yml` with required production approval. No digest exists for this
increment yet. V148 is already applied; this increment introduces no migration.
Scientific admission and protected deployment are separate decisions. Neither
is performed by these functions or this PR. Reverting this increment preserves
all source records, migration history and the production release pointer.

## Runtime delivery (DATA #429 follow-on)

`cdc_consumer_runtime.read_cdc_consumer(measure, county, environment="prod")`
uses the existing Snowflake connector/settings and requires exactly
`OH_LYME_PROD_READ` / `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, with secondary roles
NONE and a 30-second statement timeout. It reads at most two rows from the
existing secure `LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V`; zero or multiple
matches fail closed. The operator CLI uses the approved named PAT connection
`ATLAS_PROD_READ` and explicitly selects `COMPUTE_WH`.

V149 extends that existing internal view because the intended reader cannot
select the underlying governance/restricted tables. It preserves V148 joins,
secure classification and existing grants (`COPY GRANTS`), adds no grants,
and changes no sources, decisions, release pointers or publication state.
Its private `cdc_runtime_authority` object must never be returned by an API.
Ownership must remain with the migration deployer after protected deployment.

The adapter checks the actual legacy release values `COUNTY_FIPS_5`,
`through 2025-12-31`, `semantic_county_assembly_v1`, and completed
`RESTRICTED_FULL_PROD` derivation / `EVIDENCE_ONLY` capture runs. It translates
only that exact cumulative vintage into the existing 2025 semantic mapping.
The stored source approval is resource/version scoped (there is no separate
capture DSV column in these CDC ledgers). Both distinct completed runs are
associated with the release's existing approved version; no capture version
or run identity is invented. Artifact-to-evidence-run and workbook/row hashes
remain independently reconciled.

Canonical metadata and mapping resources are packaged in the wheel/container.
Revision 1 identities are pinned and remain PENDING. The runtime looks only for
`scapularis_status.revision-2.metadata.json` and
`burgdorferi_status.revision-2.metadata.json` alongside them. Neither file exists
in this engineering increment. Adding them requires the actual scientific
review; a metadata REVIEWED flag alone cannot authorize the writer.

### Required retained authority, after actual scientific review

The existing `GOVERNANCE.MANUAL_REVIEW_DECISIONS` decision must retain its real
active global steward identity, actual decision date, rationale, exact source
version/resource, decision reference, and reviewed release packet. The adapter
reads unsuperseded decisions only. Its existing `conditions` array must retain
one `cdc_consumer_admission` object with:

- `release_id`, `bundle_sha256`: the exact values in `release-binding.json`.
- `scope`: the exact corresponding entry in that file's `slices`.
- `metadata_revision_id`: the accepted immutable revision-2 content hash.
- `decision_reference`: the actual retained scientific decision reference.
- `observation_bindings`: private physical release observation ID mapped to
  `{ "record_id": "<verified canonical record>",
     "semantic_revision_id": "<existing #190 deterministic revision>" }`.

These fields are an assembly of the existing metadata/release/lineage contracts,
not another approval registry. Physical IDs and binding proof stay in the
private governed packet, not GitHub, public consumer output or this document.
The retained packet must be authored through authorized stewardship/release
controls; this adapter has no write or registration command. Do not call
`SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD` merely to register semantic review:
it retires/allocates source versions and would invalidate this pinned slice.
A metadata/release decision must retain the existing source versions. If the
available stewardship control cannot append that decision without changing
source identity, that is an exact unmet authority prerequisite, not permission
for the runtime to write or invent it.

The semantic revision is the existing #190 content identity over the verified
canonical input and accepted metadata, not the physical release observation
ID. Assemble it with `semantic_source_mappings.map_record` on the retained
source snapshot without a release/exposure claim, then bind that revision and
the verified V148 physical observation/record pair in the governed packet.
Runtime readback recalculates and compares that identity; it never populates
membership from successful projection. Retain the V087 final-copy attestation
for the exact release/resource/version separately. Source approval and final
copy do not replace this metadata review decision.

### Bounded production acceptance and API #88 binding

After the reviewer has approved the two definitions/version 1.0.0, record actual
review evidence, preserve PENDING revision 1, create immutable REVIEWED revision
2 with its real date/field authorities, and retain/bind the private packet above.
Deploy the independently reviewed engineering artifact and later accepted
metadata artifact through `quality.yml` (`deploy_dev=true`) and protected
`promote-prod.yml` with the exact approved immutable DEV digest. Recheck the
entire pending migration inventory; promote only the reviewed batch. No runtime
command performs deployment or publication.

With those prerequisites satisfied, run from the approved packaged artifact:

```powershell
atlas-data pipeline cdc-consumer-readback scapularis_status 13081 --environment prod
atlas-data pipeline cdc-consumer-readback burgdorferi_status 19135 --environment prod
atlas-data pipeline cdc-consumer-readback burgdorferi_status 12047 --environment prod
```

Each invocation validates reader identity, loads accepted revision 2, assembles
real authority, calls the existing `project_surveillance_evidence` writer and
its semantic consumer validator, and emits only the allowlisted consumer v2
(JSON semantic v1 / evidence v3) envelope. Check original labels and states:
Reported / OBSERVED -> detected; Present / OBSERVED -> detected;
No records / NO_RECORDS -> unknown. Validate both schema contracts as well as
these expected values. Confirm exact release/bundle/source/version/metadata
revision, cumulative period and limitations. Consumer output must exclude raw
workbook paths, physical observation/record IDs, derivation/evidence run IDs,
artifact IDs, row/workbook hashes and private review/final-copy proof.

Missing/unsupported data are never biological negatives. Coverage placeholders
have no authoritative publisher row and are rejected from this admitted slice;
API's existing unavailable/unknown behavior applies. Synthetic regression tests
prove engineering behavior only, never this production acceptance gate.

Provide API #88 the verified release/bundle, accepted metadata revision IDs,
source/version scope, this Data-owned `read_cdc_consumer` callable and validated
consumer envelope. The resolver must use an authorized intended-reader service
identity; ordinary API/runtime credentials are not silently elevated to this
reader. Use the merged API PR #224 optional resolver seam without classifying
labels again. Actual credential/access binding and API activation remain
API-owned actions after genuine governed consumer acceptance; this PR does
neither. DATA #429 remains open until all three real readbacks succeed.
