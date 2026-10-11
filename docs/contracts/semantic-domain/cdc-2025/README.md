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
