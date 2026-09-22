# NSF NEON active-surveillance source qualification

Status: **SELECTED for contract-preparation only**
Decision date: 2026-09-21
Decision owner: Atlas product owner (approved in the Story #383 goal review)
Story: [#383](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/383)
Parent: [#156](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/156)

## Decision

Select the following paired NSF National Ecological Observatory Network (NEON)
Level 1 products as the approved candidate scope for the first site-based active
tick-surveillance implementation:

| Role | Frozen product and version | Included native tables/resources |
| --- | --- | --- |
| Collection abundance | `DP1.10093.001` — *Ticks sampled using drag cloths*, `RELEASE-2026`, DOI [10.48443/5e20-3763](https://doi.org/10.48443/5e20-3763) | `tck_fielddata`, `tck_taxonomyProcessed`, `tck_taxonomyRaw`, `tck_identificationHistory` when present, package `variables`, validation, categorical-code, and readme resources |
| Pathogen testing | `DP1.10092.001` — *Tick pathogen status*, `RELEASE-2026`, DOI [10.48443/n2yp-5a62](https://doi.org/10.48443/n2yp-5a62) | `tck_pathogen`, `tck_pathogenqa`, and package `variables`, validation, categorical-code, and readme resources |

The selection expressly excludes:

- any `PROVISIONAL` NEON record, floating/latest download, or data from a later
  release without a new source-version review;
- a NEON production adapter, source-definition implementation, source
  acquisition, DEV/PROD load, promotion, county aggregation, public metric, or
  risk interpretation;
- treating a NEON site, plot, or event as county-representative evidence.

This decision authorizes the contract-preparation handoff to #385 and #386. It
does **not** authorize #162 until their applicable reviewed contract decisions
are complete.

## First-party evidence and access conditions

NEON's live product metadata retrieved on 2026-09-21 lists 46 collection sites
for `DP1.10093.001` and 19 pathogen-testing sites for `DP1.10092.001`.
Availability is site- and month-specific; an implementation must obtain the
static `RELEASE-2026` availability manifest at capture time rather than infer
that every collection site has pathogen observations.

The data products are currently licensed under [CC BY 4.0](https://www.neonscience.org/usage-policies).
NEON requires an authenticated account/API token for downloads. The token is a
secret: it must be held only in the approved runtime secret manager, never in a
source definition, GitHub, an artifact manifest, logs, or a browser. An
authentication/authorization failure is a non-retryable acquisition event until
the owner repairs access; it is not a reason to fall back to an interactive
login.

`RELEASE-2026` is a static, citable release. NEON documents that provisional
data can change while quality control is active, and its issue logs record
material corrections and method changes. The release identifier, product DOI,
availability manifest, product metadata response, documentation snapshots, and
every returned package file are therefore required source-version evidence.

### Authenticated schema/manifest probe

On 2026-09-22, an authenticated, read-only `RELEASE-2026` expanded-package
probe selected the first shared released site/month, `BLAN` / `2016-05`. No
source payload was retained by this qualification step. The API returned the
expected file manifest and checksums, including the following data files:

| Product | Native file | MD5 |
| --- | --- | --- |
| `DP1.10093.001` | `tck_fielddata` | `f162ff47c27fd162f086df6fedfe93d5` |
| `DP1.10093.001` | `tck_taxonomyProcessed` | `a48f436ae9412e316ed34fdad7d4a32a` |
| `DP1.10093.001` | `tck_taxonomyRaw` | `0b4ccfd40a5746c6c2700c0ab0f22139` |
| `DP1.10092.001` | `tck_pathogen` | `3a513342edce431e00149e7f1c192198` |
| `DP1.10092.001` | `tck_pathogenqa` | `88137973d20baf494732e1f50399fa8e` |

The observed headers confirm the native join and semantic fields. In
`tck_fielddata`: `siteID`, `plotID`, `decimalLatitude`, `decimalLongitude`,
`coordinateUncertainty`, `samplingImpractical`, `collectDate`, `eventID`,
`sampleID`, `samplingMethod`, `totalSampledArea`, stage counts, protocol, and
`dataQF`. In `tck_taxonomyProcessed`: `sampleID`, `subsampleID`,
`scientificName`, `acceptedTaxonID`, `sexOrAge`, `individualCount`,
`identificationHistoryID`, and `dataQF`. In `tck_pathogen`: `subsampleID`,
`testedDate`, `testingID`, `batchID`, `individualCount`, `testResult`,
`testPathogenName`, test protocol, and `dataQF`. The package-level `variables`
files provide the current data dictionary. The selected monthly package did not
contain a separate `tck_identificationHistory` file, so that file is correctly
treated as conditional on the presence of identification revisions.

## Native grain, joins, and intended canonical shapes

| Native resolution | Stable native identity and relationship | Intended canonical use | Guardrail |
| --- | --- | --- | --- |
| Collection event at a plot | `siteID` × `plotID` × `eventID`; a field record has a `sampleID` when ticks are present | Establish a sampling-event/effort record and source-faithful collection context | A field event with zero ticks is not a missing event. `samplingImpractical` records a different missingness condition. |
| Taxonomic collection result | `sampleID` → `subsampleID` for a species × life-stage result | `COLLECTION_ABUNDANCE`, retaining reported collection count, taxon, life stage, method/effort evidence, and source quality flags | Do not derive a normalized abundance unit unless the selected denominator and compatible method are explicitly documented. |
| Individual pathogen test | `subsampleID` → `testingID` × `testPathogenName`; laboratory QA links by `batchID` | `PATHOGEN_TESTING`, retaining individual-test result and laboratory quality context | A prevalence denominator is one eligible, nonblank test result for one pathogen and compatible stratum; it is not all collection ticks. |

NEON's documentation specifies one expected collection record for every plot per
event, multiple taxonomy records per sample, and a unique testing identifier for
each selected tick. The collection and pathogen products join at `subsampleID`.
The native spatial grain is a single plot. The verified `RELEASE-2026` schema
uses `collectDate` for the collection date and `testedDate` for pathogen
testing; no event-end field was present in the captured package. Source
coordinates are WGS84 plot centroids with documented uncertainty. The complete, authenticated
`variables` files remain the authority for exact field names, domains, and
current package schemas; #162 must capture and fingerprint them before it
encodes a mapping.

## Pathogen-testing interpretation

The selected pathogen product is **individual-tick testing**, not pooled
testing. NEON selects individual nymphs for testing and reports one record per
individual tick/pathogen combination. The same `testingID` may have multiple
pathogen rows. The source documentation requires a denominator calculation to
filter on `testPathogenName` and a nonblank `testResult`; blank is not a
negative result. `tck_pathogenqa` supplies batch-level control context and
should not be naively joined in a way that duplicates testing rows.

NEON's `RELEASE-2026` notice states that untested pathogen rows with blank or
`NA` results were removed. #162 must assert that this frozen release contains
no such row; its presence is a schema/revision or acquisition-quality failure,
not a negative test.

Accordingly, no pooled-testing extension is required for this selected scope.
If a later NEON product or release introduces pooled results, it is out of scope
for this decision and requires a new qualification and an explicit canonical
extension before any prevalence calculation.

## Contract deltas and required handoff

### #385 — geography and identity (blocking #162)

The current v1 schema requires `county_fips` for every observation and has no
reviewed site/event identity. #385 must define backward-compatible site,
sampling-event, and replicate identities; preserve `siteID`, `plotID`, native
coordinates/precision, `eventID`, `sampleID`, `subsampleID`, and `testingID`;
and represent source-to-county mapping as a separately versioned derived
relationship. An unmapped or ambiguous site must remain so. County aggregation
must retain site/event lineage and must not imply county-wide representativeness.

### #386 — governed vocabularies (blocking #162)

#386 must provide versioned mappings for NEON taxon names/aliases, life stages,
pathogen targets, collection method, effort units, result values, quality flags,
and source-to-canonical mapping provenance. A source adapter may not embed its
own method-equivalence, taxon synonym, unit conversion, or pathogen-name guess.

## Required quality and lineage rules for #162/#163

- Retain every source response unchanged as a private immutable artifact with
  SHA-256, byte count, media type, request/run, product/release/DOI, site/month,
  and retrieval metadata. Retain a package manifest and snapshots of product
  metadata, release metadata, license/terms, user guides, variable dictionary,
  validation rules, and issue log.
- Use the publisher identities above plus release/package/file context as the
  source-record identity. Preserve a source-row checksum and publisher revision
  metadata; never infer a natural key from county, date, taxon, or result.
- Treat duplicate identities, an unexpected one-to-many join, blank testing
  results, missing native join keys, incompatible collection methods, changed
  schemas, and undocumented release changes as blocking review/quality events.
- Enforce `ticks_positive <= ticks_tested` only after the source-native test
  eligibility filter and compatible stratification. Never set `ticks_tested`
  equal to `ticks_collected`: only a subset is selected for pathogen testing.
- Preserve numeric zero, null, unknown, not-reported, and impractical/missed
  sampling separately. A no-tick collection may be a valid zero only when the
  completed collection effort is retained.
- Keep reported, harmonized, and derived values distinct. Any cross-event,
  cross-plot, or county aggregation is a later, explicitly versioned derived
  transformation with full source lineage.

Known limitations that must remain consumer-visible include site-only coverage,
partial county coverage, variable sampling intensity (three- versus six-week
intervals), the Guanica transect exception, pre-2019 collection/taxonomy
counting changes and potential subsampling, impractical/missed collections,
publication latency, revision history, and the non-random subset selected for
pathogen testing.

## Acceptance-criterion disposition

| Story #383 criterion | Evidence/disposition |
| --- | --- |
| Exact products, release, terms, access, artifacts, coverage, cadence, revisions | Frozen above. An authenticated `BLAN`/`2016-05` manifest and headers now verify actual expanded-package files/schema; implementation must capture its own retained site/month manifests and artifacts. |
| Native grain and canonical mapping | Documented above using NEON's product relationships and the existing contract shapes; no fixture is treated as source proof. |
| Site/county relationship and contract deltas | Explicitly delegated to blocking #385; county representativeness is prohibited. |
| Individual versus pooled testing | Individual only; no pooled extension for this selected scope. |
| Consistency, revision, missingness, and limitations | Required quality/lineage controls listed above; historical design changes remain visible. |
| Immutable provenance | Package-level and record-level requirements listed above, compatible with the existing governed ingestion ledger. |
| SELECT decision and handoff | User-approved SELECT recorded here; #385/#386 precede #162. |

## Evidence links

- [NEON product metadata API: DP1.10093.001](https://data.neonscience.org/api/v0/products/DP1.10093.001)
- [NEON product metadata API: DP1.10092.001](https://data.neonscience.org/api/v0/products/DP1.10092.001)
- [NEON tick collection user guide](https://data.neonscience.org/api/v0/documents/NEON_tick_userGuide_vH?inline=true)
- [NEON pathogen-testing quick-start guide](https://data.neonscience.org/api/v0/documents/quick-start-guides/NEON.QSG.DP1.10092.001v1?fallback=html&inline=true)
- [NEON pathogen-testing user guide](https://data.neonscience.org/api/v0/documents/NEON_tickPathogen_userGuide_vE?inline=true)
- [NEON releases API documentation](https://data.neonscience.org/data-api/endpoints/releases/)
- [NEON data use policy](https://www.neonscience.org/usage-policies)
