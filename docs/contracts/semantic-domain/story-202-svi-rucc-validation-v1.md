# DATA202: SVI/RUCC validation contribution

This bounded contribution reuses #188 baseline contracts, #190 value states,
#191 metadata, #192 mappings, #193 lineage, #195 compatibility governance and the
existing semantic release gates.
It adds fixtures, not a source, monitoring system, migration or deployment. It depends
on DATA199 reconciliation and merged DATA200. It does not close all of DATA202.

## Selected-source compatibility matrix

| Dimension | CDC/ATSDR SVI | USDA ERS RUCC | Join rule |
| --- | --- | --- | --- |
| Selected vintage | 2022, ACS 2018–2022 | 2023 | Retain both; no silent vintage substitution |
| County identity | Five-digit FIPS, unique county | Five-digit FIPS, unique county | Match identities, not row counts |
| Observation time | PERIOD, 2018-01-01 through 2022-12-31 | VINTAGE_YEAR, 2023, in reviewed semantic version 2.0.0 | Descriptive mixed-vintage context; contemporaneity is not established; no exact RUCC observation day is asserted |
| Meaning | Overall SVI percentile; uninsured percentage/percentile; E_TOTPOP population estimate | Classification codes 1–9 | Percent, percentile, people and code remain distinct |
| Denominator/reference | E_TOTPOP is a population estimate used by legacy incidence as its denominator; EP_UNINSUR uses the civilian noninstitutionalized population; percentile has its source reference population | No numeric population denominator | Preserve each denominator; no pooling ranks or treating RUCC as a continuous quantity |
| Geography | Source county polygon displayed in EPSG:4326 with existing 0.01 simplification | County identity classification | Display geometry does not establish TIGER 2025 analytical equivalence |
| Availability/retrieval | Publisher publication may remain UNKNOWN; retrieval is a timestamp | Same distinction | Neither vintage nor retrieval proves publisher availability |
| Provenance | Its own exact version/run/artifact/record/proof | Its own exact version/run/artifact/record/proof | Cross-source borrowing is rejected |
| Value states | Sentinel/null → MISSING, zero retained; per-measure reviewed policy required | County release requires a valid ordinal code 1–9 for every SVI county; missing/null/suppressed RUCC blocks release | Generic semantic state policies do not relax county-release coverage; SVI partial missingness does not erase valid RUCC values/lineage |

SVI is area-level context, not individual vulnerability, causation, exposure or
diagnosis. RUCC is a county classification, not an exposure or individual risk
score. Annual configured cadence does not select a new vintage. Mixed vintages
may be displayed descriptively; predictive eligibility and availability ordering
require separately verified publication evidence and an approved modeling policy.

## Executable acceptance evidence

All additions are in `tests/test_population_context_compatibility.py` and call the
existing production validators rather than reproducing their implementation.

| DATA202 concern | Concrete fixture evidence | Boundary |
| --- | --- | --- |
| Join/time/unit/denominator compatibility | Full paired map_records plus validate_cross_contract; compare_measure and compare_mapping; different-vintage rejection | No assertion that unequal vintages become contemporaneous |
| Provenance and immutable revisions | Borrowed run/artifact/record rejection; duplicate rejection; corrected value requires new revision while old observation remains intact | Synthetic authorities are explicitly namespaced |
| Freshness versus old valid source | Passing gate accepts selected older vintage; metadata preserves UNKNOWN publication with known retrieval | No invented publication date, freshness threshold or quiet-period monitor |
| Metadata temporal boundaries | Publication, retrieval and observation fields reject incompatible value shapes | Shape validation is not chronological availability validation |
| Grain, zero and partial missingness | Two-county assembly preserves SVI ZERO, missing population/derived incidence, human counts and RUCC; equal-count mismatched counties fail | Historical derived incidence requires both human and population inputs under the existing adapter |
| Failure isolation | Missing/failed blocking quality aborts real build gate, rolls back, makes no presentation writes and never moves pointer | No real release pointer was touched |

Existing SVI and RUCC field/domain tests remain the selected-source baseline.
Existing climate, MOD13 and NLCD lanes retain their owners and tests. Monitoring
and quality infrastructure from #250/#278 is reused conceptually through existing
source gates; this contribution creates no competing monitor or loader.

The explicit synthetic SVI metadata candidate used for MISSING/ZERO tests remains
PENDING. Restricted checked-in metadata still rejects undeclared states. These
fixtures do not widen or approve live metadata.

## Runtime evidence and remaining gates

Read-only DEV baseline evidence for #199/#200 reports 3,144 unique valid county
FIPS, valid selected-source value domains and published metadata retaining
vintages/limits. This is existing consumer SQL evidence, not execution of the new
head, live REST/UI evidence or PROD acceptance.

The default DEV read role cannot read internal semantic authority tables (002003).
Exact live version/run/artifact/checksum lineage, reviewed metadata state admission,
publisher availability and availability ordering therefore remain unverified.
Authorized release/audit owners must supply those proofs before claiming full
runtime acceptance. No grants, credentials, reingestion, release or topology change
is requested by this contribution. Parent owns independent review, merge and
release coordination.
