# CDC Ixodes pathogen county workbook: source review

Status: Proposed — human stewardship decision required  
Owner: Atlas product and engineering leads  
Issue: #256

## Purpose and boundary

This review records the evidence required to decide whether the distinct CDC
ArboNET pathogen-status workbook may enter a governed Atlas path. It does not
approve the source, authorize raw acquisition, create a `SourceDefinition`, or
permit a DEV or PROD load.

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

Those terms make this a Tier D restricted source under ADR 0027. Neither a
pipeline runtime nor an engineering agent can interpret the terms as permission
to copy raw bytes to object storage, Snowflake, GitHub, a shared workspace, or
the public API.

## Required human decision

The product/data steward must record one of the following outcomes on #256.

### Option A — pursue an authorized governed path

Obtain and record CDC's written permission that specifically allows Atlas to:

1. retain the identified workbook in private governed storage;
2. process it with the named service identities;
3. derive and publicly display the county-level `burgdorferi_status` field;
4. satisfy the required ArboNET attribution and final-copy obligation.

Only after that evidence is attached may engineering propose a separate source
definition, a new versioned canonical status-observation contract, a bounded
DEV evidence run, and later a protected Tier C promotion.

### Option B — retain it as a release blocker

Record that the terms do not authorize the governed/public use above. The
workbook stays on the requestor's workstation, no raw data is loaded, and the
unreproduced Alpha pathogen field remains an explicit blocker for full parity
and #277.

## Engineering gates after Option A

1. Review the written permission and publisher metadata against this checksum
   and an explicitly identified source version.
2. Define a source-native, status-only observation contract; do not relabel it
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
- Run Tier B/C ingestion or publish a semantic release before Option A is
  documented.

## References

- CDC Tick Data / Tickborne Pathogen Surveillance
- `docs/adr/0023-dev-operator-captured-restricted-evidence.md`
- `docs/adr/0027-tiered-ingestion-operating-model.md`
- `docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md`
- `docs/contracts/alpha-parity/alpha-2026-08-06-baseline.json`
