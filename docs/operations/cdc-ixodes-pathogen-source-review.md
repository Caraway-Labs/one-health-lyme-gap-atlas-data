# CDC Ixodes pathogen county workbook: source review

Status: Approved for restricted governed DEV path — 2026-09-16
Owner: Atlas product and engineering leads  
Issue: #256

## Purpose and boundary

This review records the evidence and product/data-steward decision for the
distinct CDC ArboNET pathogen-status workbook. It authorizes the restricted,
private DEV evidence path described in ADR 0029 and the owner-rights DEV
derivation boundary in ADR 0031. It does not make the workbook public,
authorize unrestricted redistribution, or authorize a PROD load.

The workbook is not the CDC county-status workbook for *Ixodes scapularis* and
*Ixodes pacificus*. It must never be used as a substitute for that source, and
the county-status workbook must never be used to infer pathogen status.

## Reviewed local evidence

The operator-supplied file is named
`Public_Use_Ixodes_Pathogens_County_Table_2026_04292026.xlsx`.

- SHA-256: `68baef5f20b1e41821d0e6955cbb1809262e0f3624e387e88c04f6ddb0266f2f`
- Publisher title: *Tickborne Pathogens Identified in Host-Seeking Ixodes spp.
  Ticks: Status by Contiguous United States County (through Dec. 31, 2025)*.
- Publisher attribution: CDC ArboNET Tick Module.
- Workbook structure: data-use agreement sheet, classification-terms sheet,
  and county data sheet.
- County sheet: 3,117 rows, 3,111 valid five-digit FIPS values, and six blank
  FIPS rows. There are no duplicate nonblank FIPS values.
- The Alpha baseline requires only
  `burgdorferi_status`. Its frozen profile is 689 `Present` and 2,455
  `No records` across 3,144 county-equivalents. The reviewed workbook also
  reports 689 `Present` for *Borrelia burgdorferi sensu stricto*; scope and
  missing-row differences still require an explicit parity classification.

The workbook includes seven pathogen status/source pairs: *Borrelia burgdorferi
sensu stricto*, *B. mayonii*, *B. miyamotoi*, *Anaplasma phagocytophilum*
human-active variant, *Ehrlichia muris eauclairensis*, *Babesia microti*, and
Powassan virus.

## Meaning and public-health limits

For the Alpha-equivalent field, the candidate source is the reported county
classification for *Borrelia burgdorferi sensu stricto*:

- `Present` means the pathogen was identified in one or more host-seeking
  *I. scapularis* or *I. pacificus* ticks using species-specific molecular
  methods.
- `No records` means no published county record has been documented. It can
  reflect absent sampling, collection, testing, reporting, or publication; it
  is not pathogen absence, a prevalence estimate, human infection incidence,
  individual infection risk, or a diagnosis.
- The workbook supplies no tested-tick count, positive-tick count, sampling
  effort, or laboratory-method detail. It therefore cannot be modeled as the
  existing `PATHOGEN_TESTING` observation type and cannot support a prevalence
  calculation.

Any future mapping must retain the source category for each classification,
the cumulative-through-date temporal meaning, the host-seeking Ixodes scope,
and the distinction between the reported `No records` status and missing data.

## Data-use restriction

The embedded agreement says access is limited to the requestor who downloaded
the file and the data must not be provided to other persons. It also requires
ArboNET attribution in derived publications/presentations and provision of a
final copy to CDC's Division of Vector-Borne Diseases.

Those terms make this a Tier D restricted source under ADR 0027. Raw bytes are
handled only by the requestor-controlled private evidence path and the named
governed service identities that verify and retain the artifact. They must not
be committed to Git, uploaded as a GitHub/CI artifact, exposed in logs, or
served by Streamlit, the API, or a public web page.

## Recorded product/data-steward decision

On 2026-09-16, the product/data steward confirmed that they personally
downloaded the workbook through the official CDC Tick Surveillance Data Sets
page, accepted the data-use terms, and authorized the restricted governed path
to proceed. This is a recorded product and data-governance decision, not an
independent legal opinion about the CDC terms.

The decision requires all of the following controls:

1. Retain the raw workbook only in the requestor-controlled private evidence
   transport and private governed artifact store; never in source control,
   GitHub artifacts, public registries, logs, Streamlit, API responses, or the
   public web application.
2. Include the official CDC dataset page in source/release provenance:
   <https://www.cdc.gov/ticks/data-research/facts-stats/tick-surveillance-data-sets.html>.
3. Attribute the CDC ArboNET Tick Module in derived publications or
   presentations.
4. Before a resulting publication or presentation is finalized externally,
   prepare and provide its final copy to CDC Division of Vector-Borne Diseases
   at `ticksurveillance@cdc.gov`. No external transmission is authorized by
   this engineering decision.
5. Keep the source as Tier D. The DEV evidence capture and ADR-0031
   derivation must be bounded and private; any PROD write or public semantic
   release requires separate protected Tier C approval.

## Engineering gates after this decision

1. Bind the private evidence run to this checksum and an explicitly identified
   source version.
2. Define and test a source-native, status-only observation contract; do not relabel it
   as pathogen testing.
3. Add fixture-based mapping and regression tests for FIPS format, six blank
   rows, 3,111 valid source FIPS, `Present`/`No records`, source categories,
   cumulative date, and no-records semantics.
4. Run a bounded DEV evidence path that keeps raw bytes private and produces
   immutable lineage, quality results, and a comparability report.
5. Classify every difference from the 3,144-county Alpha baseline before a
   protected PROD source/release approval.

## Explicitly prohibited

- Infer pathogen status from the tick county-status workbook.
- Treat `No records` as absence, zero prevalence, or a negative test.
- Convert the seven status fields into `PATHOGEN_TESTING` observations.
- Upload the reviewed workbook to GitHub, a public endpoint, or an unapproved
  shared system.
- Run generic Tier B/C ingestion or publish a semantic release before the
  dedicated DEV derivation/parity proof and protected Tier C approval.

## Private DEV evidence capture

The repository command `scripts/publish_tick_operator_evidence.py` uses the
explicit `--source-kind pathogen` option for this workbook. It validates the
private landing-page PDF and workbook locally, creates a checksum-bound,
short-lived private image envelope, and dispatches the protected DEV workflow.
The workflow requires the tag, source-kind input, retrieval UUID, base-image
digest, and envelope digest to agree before it starts the
`cdc-pathogen-surveillance-sample` command. The temporary envelope tag is
removed and the prior DEV topology restored whether capture succeeds or fails.

The evidence capture stores a private raw artifact, its manifest, metadata,
schema fingerprint, and a 25-row review sample. Evidence-only operation
creates a `PENDING_REVIEW` candidate only. With the explicit protected
`derive` operation after an approved source version, ADR 0031 permits the
private DEV procedure to retain source-faithful restricted RAW/STAGING rows
and create only the derived *B. burgdorferi sensu stricto* county-status
CONFORMED projection. That projection is not public and remains blocked from
semantic release until the 3,144-county parity delta is classified.

## References

- [CDC Tick Surveillance Data Sets](https://www.cdc.gov/ticks/data-research/facts-stats/tick-surveillance-data-sets.html)
- [CDC Tickborne Pathogen Surveillance](https://www.cdc.gov/ticks/data-research/facts-stats/tickborne-pathogen-surveillance-1.html)
- `docs/adr/0023-dev-operator-captured-restricted-evidence.md`
- `docs/adr/0029-cdc-pathogen-status-restricted-ingress.md`
- `docs/adr/0027-tiered-ingestion-operating-model.md`
- `docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md`
- `docs/contracts/alpha-parity/alpha-2026-08-06-baseline.json`
