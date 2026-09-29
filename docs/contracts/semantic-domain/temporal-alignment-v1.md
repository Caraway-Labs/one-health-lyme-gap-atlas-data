# Temporal alignment and availability v1 (Data #431)

Status: proposed for steward/scientific review. Owner: Atlas data stewardship.
Executable contract: `lyme_gap_atlas_data.temporal_alignment`.
This is a storage-neutral extension of [Atlas semantic domain v1](atlas-semantic-domain-v1.md),
[semantic metadata v1](atlas-semantic-metadata-v1.md), and
[ADR 0035](../../adr/0035-semantic-domain-identity-boundary.md). It describes a
declared analytical use of source evidence. It does not change a #190 observation
key or revision, #191 freshness, #193 lineage, V071/V072, or a source-native row.
There is no migration, new source, ML feature, API field, or public release.

## Distinct times

| Field | Meaning | Never substituted with |
| --- | --- | --- |
| `observation_window` | Source phenomenon/data support, half-open `[start, end_exclusive)` | Publisher availability |
| `availability.first_published_at` | First publisher/source availability for this snapshot, with evidence | Observation year, source `Last-Modified`, Atlas retrieval |
| `availability.retrieved_at` | Atlas acquisition time | Historical publication proof |
| `availability.revision_available_at` | When this exact revision/vintage became available | A later current version's date or mapping year |
| `availability.complete_at` | When all required inputs for this declared aggregate/composite existed | The period label alone |
| `lag` | Declared relationship from observation window to target window | Methodology era or a learned causal effect |
| `target_window` | Outcome/reference period of the analysis | Observation or publication period |
| `decision_cutoff` | Timestamp at which historical input eligibility is tested | Retrieval or evaluation date |

The half-open boundary, Gregorian calendar, and UTC convention are mandatory.
This is compatible with #190 `PERIOD` start/end and #191 freshness state envelopes:
an adapter must convert their inclusive period end to `end_exclusive` explicitly,
and must not turn a #191 `UNKNOWN` publisher date into a known timestamp. The
`source_id`, `measure_id`, source version/vintage, and revision ID reference the
existing semantic/provenance identities; this contract is not a parallel source
registry. It contains no physical run/artifact IDs. Existing unlagged observations
remain unchanged and have no implicit alignment declaration.

## Declaration

`atlas-temporal-alignment-v1` requires:

- `method_id` and `method_version`; `source_id`, `measure_id`, `source_version_id`,
  `source_vintage`, and `revision_id`;
- `observation_window` and `target_window`, each with `start`, `end_exclusive`,
  `calendar: GREGORIAN`, and `timezone: UTC`;
- `lag.kind` (`ZERO`, `FIXED`, `ROLLING`, `SEASONAL`), `anchor` (`START` or
  `END_EXCLUSIVE`), and nonnegative `offset_days`; rolling adds exact
  `window_days`, seasonal adds a `season_id`; every nonzero kind requires an
  HTTPS `rationale_reference`;
- `aggregation.rule` (`NONE`, `SUM`, `MEAN`, `CATEGORY`, `ANOMALY`), explicit
  `denominator`, and coverage `expected`, `observed`, `unit`, `partial_allowed`,
  and a source policy reference when partial support is permitted;
- `availability` with separate first publication, exact revision availability,
  complete-input time, retrieval, and optional source modification. Each positive
  availability claim requires its own HTTPS evidence reference. Unknown facts are
  null, not guessed from another field;
- an ISO UTC `decision_cutoff` and nonempty limitations. `ANOMALY` additionally
  requires a versioned `reference_period` with its own source vintage,
  revision, interval, publication, revision, and complete-input evidence.

`ZERO` requires an explicitly declared identical observation and target window;
omitting lag is invalid. Other lag kinds require the declared anchor and offset
to match the actual windows, with the observation ending no later than the
target start. Rolling duration must equal its declared window. Seasonal windows
may cross calendar years and include leap day without shifting either endpoint.
The validator checks a supplied relationship; it does not select a biological
lag, infer source availability, or endorse the fixture's rationale as science.

Coverage counts are always interpreted against the declared denominator and
unit. For `DAYS`, expected coverage equals every Gregorian date in the declared
window, including leap day; observed coverage may be lower. A QA-filtered MODIS composite or nClimGrid mean may use a source-specific
support policy, but no universal partial-support threshold is invented. The
existing [nClimGrid daily contract](../climate/nclimgrid-daily-v1.md),
[Annual NLCD contract](../land-cover/annual-nlcd-c1v2-v1.md), and source
contracts continue to own completeness and representativeness rules. A monthly
aggregate before month end, incomplete required composite, later climate
revision, later NLCD vintage, or anomaly reference extending past cutoff is
not eligible even if its numeric value can be computed today. A current
cumulative tick status is not silently recast as historical annual evidence.

## Disposition and consumer boundary

| Disposition | Meaning |
| --- | --- |
| `ELIGIBLE` | Complete required support and separately evidenced first publication, exact revision, aggregate completion, and any anomaly reference are no later than cutoff. This is temporal eligibility only. |
| `INELIGIBLE` | Observation/reference extends beyond cutoff, required coverage is incomplete, or evidenced input/revision/completion is later than cutoff. |
| `RETROSPECTIVE_ONLY` | A retrieved snapshot exists, but historical publisher/revision/completion timing remains unproved. Useful only for clearly labeled retrospective analysis. |
| `UNKNOWN_AVAILABILITY` | Timing cannot be proved and no retrieved snapshot is supplied. Strict point-in-time use abstains. |

The result retains reason codes, declared windows/lag, aggregation rule,
coverage and denominator, anomaly reference-period identity/window, cutoff,
method/version and limitations. `project_temporal_alignment()` allowlists those
explanatory fields and excludes source version/revision, availability references,
retrieval timestamps, extra nested fields, physical lineage, and source payloads. API #88 requires
its own reviewed propagation decision. The contract does not imply #430
methodology comparability: a temporally eligible row can still be a cross-era
or unknown-comparability row. #113 must combine both with label state, population
denominator, geography, and ML #23's approved forecast origin.

The tests are synthetic contract fixtures, including zero/fixed/rolling/seasonal
lags, a cross-year leap season, delayed human label, monthly climate support,
revised climate, future NLCD vintage, incomplete MODIS composite, partial
source support, future anomaly reference, current cumulative tick status,
unknown publication time, and consumer projection. They prove validator
behavior, not historical source publication or an eligible DEV panel.
