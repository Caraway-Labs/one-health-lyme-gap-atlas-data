# DATA197 minimal native USDM tabular option

Status: proposed engineering qualification for scientific/source review, 2026-10-03.
No source activation, canonical mapping or exposure is approved by this document.
This is a follow-up to [drought qualification](drought-qualification-v1.md), prompted
by independent review of PR585. It changes no runtime code or scientific target.

## Qualification conclusion

The official **native categorical county percent-area table is a defensible bounded
source option**. The inspected vector's invalid D0 polygon and absent nondrought
support mask are blockers for an Atlas vector-intersection calculation, not evidence
that the official tabular product is unusable. The table already publishes None
and D0-D4. Atlas can preserve that publisher-reported breakdown without reconstructing
None from geometry gaps, repairing polygons, or silently reprojecting percentages.

DATA197 explicitly includes county share by class. The proposed target is that
source-reported share for a publisher county AOI and map snapshot. It does not claim
to reproduce the fraction of the full frozen 2025 TIGER legal polygon in each class.
That methodological distinction must be in the measure definition and limitations,
not left implicit in the code or hidden behind a county FIPS join.

## Authoritative facts and bounded recheck

The publisher's [statistics explanation](https://droughtmonitor.unl.edu/About/AbouttheData/StatisticsExplanation.aspx)
separates cumulative from categorical computation and area from population; categorical
area statistics describe one class at a time. The
[REST specification](https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx)
defines CountyStatistics, five-digit county AOI selection, separate percent-area and
absolute-area operations, format 2 for categorical, format 1 for traditional, CSV
output, and None plus D0-D4. The
[comprehensive download](https://droughtmonitor.unl.edu/DmData/DataDownload/ComprehensiveStatistics.aspx)
provides the same product choices; it is not an independently specified county vintage.

Additional rechecks stayed on **48081 / 2025-01-07**, preserving the existing target:

| Official operation | Format | Result |
| --- | --- | --- |
| GetDroughtSeverityStatisticsByAreaPercent | 2 | Original retained fixture: HTTP200, 172 bytes, one row |
| GetDroughtSeverityStatisticsByArea | 2 | HTTP200, 174 bytes, one row; positive sum of the six native category areas |
| GetDroughtSeverityStatisticsByAreaPercent | 1 | HTTP200, 172 bytes, one row; format identity remains explicitly distinct |

The additional requests used the documented CountyStatistics REST URL with the
same AOI and single-day start/end. They matched the original FIPS/MapDate. Native
categorical percentages sum to 100.00; each absolute-area/summed-area ratio agrees
with the corresponding percentage within 0.01 percentage point. Cumulative D0
agrees with the sum of categorical D0-D4 within rounding tolerance. This particular
sample has only None and D0 nonzero, so it cannot alone demonstrate a nontrivial
cumulative-versus-exclusive difference; the authoritative format documentation
establishes that distinction. No source rows are substituted into a semantic release.
The two response projections and the diagnostic comparison remain local evidence
outside the repository; they are not new governed captures or source approvals.

## Minimal contract option

- Product: official USDM CountyStatistics categorical **percent area**, format 2.
  Preserve None, D0-D4 independently; None is nondrought, D0 abnormally dry,
  and D1-D4 drought intensities. Do not select population, DSCI, grids or a cumulative
  workbook as a silent replacement. No numeric mean of class codes is permitted.
- Scope: retain the existing one county/week pilot. Any later expansion is explicit
  and bounded (at most five Tuesday map labels / 64KB per candidate request), with
  a frozen AOI whitelist. Do not request a state/all-county history to establish a
  pilot identity or invent retired/split-county crosswalks.
- Meaning: six source-reported percentages of the **publisher's selected county AOI
  area**, not Atlas-computed percentages over TIGER 2025. The native denominator
  is known at this descriptive level; polygon vintage, precise land/water treatment
  and equivalence to Atlas's analytical area are unestablished and remain explicit
  limitations. No unsupported county source-support fraction is fabricated.
- Time: weekly map snapshot labeled by Tuesday MapDate. A prospective reported
  measure should use the existing POINT_IN_TIME shape, with ValidStart/ValidEnd
  retained as source labels, not a seven-day mean. Thursday release cadence is
  distinct from observed/first available/retrieved timestamps; historical actual
  first availability remains unavailable. SPEI calibration period is not applicable
  to this USDM target. No rolling drought weeks, episodes or max-class summaries.
- Identity/lineage: preserve the complete raw table bytes, source URL/request scope,
  actual retrieval time, available HTTP revision metadata and SHA256. Use the
  existing orchestrator/run/member/V103 capture boundary; keep source response
  revisions distinct from scientific semantic IDs and vintages. A changing table
  may represent statistical/transport/geography drift even when the map is final.
- Missingness/coverage: absent week or field is not zero. Preserve valid zero shares,
  nondrought category, all six partial-county shares and the source's numeric precision;
  enforce format/schema/date/AOI/total checks without renormalization. A county absent
  from a larger source scope cannot establish zero drought or county coverage.
- Compatibility: source-reported native-AOI percentages can be retained and reviewed
  independently. They cannot establish analytical footprint equality with nClimGrid,
  NLCD or frozen TIGER. No county-area pooling, cross-vintage equivalence, pixel
  intersection, causal Lyme interpretation or automatic ML/score admission.

## Existing-contract implementation boundary

1. Add one candidate definition and fixture path to the existing simplified source
   entry point. Reuse HTTP CSV source-faithful acquisition and RAW/STAGING/V103 effects,
   not a second CLI/orchestrator, source-specific workflow or warehouse role.
2. The current generic CSV adapter enforces required headers and maximum rows but
   downloads response content before that row check and does not run the native USDM
   validator. A live implementation must add a narrow streaming byte bound and wire
   format/AOI/date/class/period checks into the existing stages and fresh-process replay.
   Merely adding YAML quality-rule names is insufficient. No live definition is added
   or run by this follow-up.
3. Define six reviewed REPORTED numeric-percent measures with fixed category-specific
   IDs, explicit native AOI denominator, POINT_IN_TIME grain and observed/zero/missing
   value states. Six IDs avoid inventing a USDM-class stratum in the currently frozen
   #188 stratum set. Keep raw precipitation and SPEI under their own measure families.
4. County FIPS must be proven to identify the selected canonical entity through an
   explicit native-source identity mapping. This proof does not assert polygon equality.
   Decide and review whether a COUNTY-native REPORTED measure with denominator limits
   is accepted for the pilot. #191 still needs the real governed source/version/vintage,
   reviewed metadata and limitations; MapDate must not be silently substituted for an
   unspecified source vintage or historical availability date. #192/#193 must bind the
   exact record/run/artifact and metadata revisions; #195 comparison/release gates remain.
5. The existing SOURCE_ONLY_COUNTY escape shape is **not** a numeric fallback: #188
   requires null canonical FIPS and UNKNOWN/null value for that grain. Do not put observed
   native percentages there, weaken that rule, or label raw numeric rows as approved
   semantic assertions. Source-faithful ingestion can precede mapping/publication.

## Remaining exact facts and decisions

The official pages and bounded CSVs reviewed do not identify the county polygon
release used for 48081's denominator, the land/water inclusion policy, or whether
historical statistics are recalculated when AOI boundaries change. The absolute-area
sum establishes an internally consistent numeric denominator for this capture; its
magnitude cannot identify a polygon vintage/CRS. AOI values identify request codes,
not boundary lineage. Population documentation describes an estimation method and
does not resolve the percent-area polygon vintage; a cumulative workbook and a raster
display product likewise do not add that missing evidence.

These unknowns block claims of identical 2025-TIGER area support and unreviewed
longitudinal/cross-source comparisons. They do not invalidate the narrower claim
"the publisher reported this class share for its selected county AOI/map label."
The remaining bounded review is whether that explicit native measure and identity
mapping satisfy the intended contextual use, plus a genuine source-vintage/metadata
binding. If accepted, implement the scope above through existing source contracts.
If the intended target specifically requires a frozen-TIGER fraction, the unresolved
geometry/support facts remain blockers and this native option cannot substitute for it.

## Ready-to-use source question and recommendation

Prepared question for the ticket/reviewer; **not sent to the publisher**:

> For the official CountyStatistics percent-area and absolute-area categorical
> responses for FIPS48081 and MapDate20250107, which county boundary product,
> release/vintage and CRS define the AOI? Is the denominator land only, land plus
> inland water, or another clipped support domain? When county boundaries or
> denominator inputs are updated, are historical weeks recalculated; if so, how
> can consumers identify and retain the version used for each historical response?

Recommendation: retain the source-native option and proceed only after explicit
review of its restricted comparability and source identity/vintage binding. Obtain
the three facts above before claiming a TIGER-equivalent analytical measure or
longitudinal comparability. Do not contact the publisher, activate ingestion, add
native percentages to SOURCE_ONLY_COUNTY, or change the scientific contracts as
an unattended follow-up to this qualification PR.
