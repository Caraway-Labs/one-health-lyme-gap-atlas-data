# Source Onboarding Specification: Catalog Discovery to CDC/Socrata Pipeline

## Summary

Build the first governed pipeline as a two-stage system:

1. Discover datasets by independently searching Data.gov, HealthData.gov, and Socrata/Open Data Network (ODN) with version-controlled terms from [`catalog-search-terms.json`](catalog-search-terms.json).
2. Classify every discovered resource, collect its metadata/documentation and a small sample, score it, require data-steward approval, then fully ingest only approved authoritative resources. The CDC Lyme Socrata family is the first reference source family for this full path.

The three discovery catalogs are not interchangeable data stores. They produce catalog metadata and resource links. The pipeline must query the actual publisher resource only after catalog results are registered and assessed.

## Scope and release boundary

### In scope

- Discovery from the three catalog APIs defined in [`catalog-search-terms.json`](catalog-search-terms.json).
- Catalog-result registration, deduplication, metadata/document/sample retrieval, deterministic scoring, data-steward approval, and full ingestion of approved public sources.
- Connector support for Data.gov-result direct files and Socrata/SODA resources in the first release.
- CDC Lyme Socrata as the first fully implemented source family, including the three public surveillance eras.

### Out of scope for this release

- Direct portal-specific discovery crawls for CDC, CMS, Census, NOAA, NEON, USGS, EPA, or state portals. These are downstream publisher systems or later catalog adapters, not initial discovery catalogs.
- Full retrieval of every search result, blind crawling of landing pages, and automated onboarding of controlled/restricted sources.
- Automatic approval of newly discovered resources.

## Catalogs to query

| Catalog ID | Catalog | Role | Current API contract | Credential environment variable |
|---|---|---|---|---|
| `DATA_GOV` | Data.gov Catalog API v4 | Federal metadata discovery and publisher/terms validation | `GET https://api.gsa.gov/technology/datagov/v4/search`; cursor pagination using `after` | `DATA_GOV_API_KEY` |
| `HEALTHDATA_GOV` | HealthData.gov HHS catalog | HHS-focused metadata discovery, scoped to `healthdata.gov` through Socrata discovery | `GET https://api.us.socrata.com/api/catalog/v1` with `search_context=healthdata.gov` | `SOCRATA_APP_TOKEN` (optional) |
| `SOCRATA_ODN` | Socrata Open Data Network / Discovery API | Cross-portal Socrata discovery; results must be resolved to original publishers | `GET https://api.us.socrata.com/api/catalog/v1` | `SOCRATA_APP_TOKEN` (optional) |

Use the Data.gov v4 API for new implementation. It replaced the legacy CKAN API, requires an API key for automated use, and uses cursor—not offset—pagination. A `DEMO_KEY` is permitted for local exploration only and is prohibited in committed configuration and scheduled environments.

`catalog-search-terms.json` is the authoritative, complete term list. Every catalog applies every enabled term group plus its catalog-specific terms unless the configuration contains a documented catalog-specific provider-compatibility exclusion. Exclusions must name an otherwise configured term and preserve that term for the other eligible catalogs. The current staged DEV discovery run enables the six Lyme/tick/vector/context groups plus healthcare utilization, public-health capacity/access, and diagnostics/medications/treatment. The remaining six groups stay disabled until the steward reviews candidate volume, relevance, rate-limit behavior, and licensing/access patterns.

## Search-input file contract

The pipeline shall load `catalog-search-terms.json` at runtime and reject the run before any request if:

- `$schema_version` is unsupported;
- a catalog references a missing term group;
- a term group has no terms;
- a required enabled catalog lacks its configured credential environment variable;
- pagination or search configuration is incomplete; or
- the file is not valid UTF-8 JSON.

The pipeline shall make one catalog search per unique enabled term, with terms deduplicated case-insensitively within each catalog. It shall retain the configuration checksum and the exact term used on every discovery request. Compound searches are a later enhancement; they must be declared in this JSON file before execution, never constructed silently in code.

## Discovery workflow

1. Create an `ingestion_runs` record with `run_mode=METADATA_ONLY`, `trigger_type=SCHEDULED` or `MANUAL`, the code version, and the search-configuration SHA-256.
2. For each enabled catalog and enabled search term, request all catalog result pages using the configured immutable query parameters and page cursor/offset.
3. Write one `ingestion_requests` record per request, including the catalog, term, page token, response headers, status, response checksum, and redacted error details.
4. Store the raw catalog response as an immutable `raw_artifacts` metadata artifact.
5. Normalize each returned dataset package into `catalog_datasets`; normalize every linked distribution, API endpoint, documentation link, and landing page into `catalog_resources`.
6. Deduplicate discovery results by catalog identity and then attempt canonical-resource resolution. Preserve all catalog observations even when multiple discovery records resolve to one publisher resource.
7. Classify each resource as `DATA`, `API`, `DOCUMENTATION`, `DATA_DICTIONARY`, `LANDING_PAGE`, or `CONTROLLED_ACCESS`.
8. For a machine-readable candidate, retrieve metadata, governing documentation, and a small source sample. Do not retrieve the full dataset at this stage.
9. Run deterministic automated assessment. Write the assessment and its evidence references to `dataset_quality_assessments`.
10. Route every candidate recommended for full ingestion to the Snowflake Streamlit [`SOURCE_APPROVAL_CONSOLE`](streamlit-snowflake-approval-app-requirements.md). Only an `APPROVED` or `APPROVED_WITH_CONDITIONS` decision recorded by its controlled procedure can activate a source access profile and full ingestion.

## Source classification and routing

| Observed resource | First-release action | Full-data action after approval |
|---|---|---|
| SODA API or Socrata export | Capture view metadata and a small ordered sample | Use the SODA connector with validated endpoint/version, deterministic order, and pagination or source export |
| Direct CSV, JSON, GeoJSON, Parquet, XLSX, or ZIP | Capture headers, media type, size when available, and sample/schema | Download unchanged file, hash it, store artifact, and load a source-specific RAW table |
| API described by OpenAPI/REST metadata | Capture documentation and a sample only when a supported connector exists | Add a source-specific access profile; unsupported endpoints remain pending |
| Documentation, dictionary, release note, methodology, license, or terms | Store immutable document artifact | Link document snapshots to the approved source version |
| Landing page only | Record as a research lead | No automatic full ingestion |
| Restricted, controlled, manual, or approval-gated source | Record access classification and limitation | No full ingestion in this release |

## Automated scoring and approval

Automated scoring occurs in the source-assessment job after sample/document retrieval and before any full-data request. It is deterministic configuration/rule logic, not an LLM decision.

| Assessment dimension | Evidence used | Outcome |
|---|---|---|
| Relevance | Term matches in title, description, tags, publisher, and resource metadata | Score and recommended role |
| Join potential | Geography, time grain, identifiers, population, units, and source resolution | Score and joinability notes |
| Accessibility | Access classification, supported connector, auth mode, sample success, rate limits | Score and access profile recommendation |
| Documentation | Dictionary, methodology, case definition, license, terms, and release notes | Score and missing-evidence flags |
| Quality/readiness | Sample parse, schema presence, required fields, freshness/update evidence, duplicate/mirror signals | Score, limitations, and promotion recommendation |

The job shall populate `dataset_quality_assessments` with each component score, an overall score, recommended role, limitations, and artifact/snapshot identifiers supporting the result. It may recommend `APPROVED`, `CONDITIONAL`, `REJECTED`, or `RETIRED`; it may not authorize ingestion. A designated steward must approve every new resource in `SOURCE_APPROVAL_CONSOLE` before the scheduler can request its complete data payload.

## CDC Lyme Socrata reference family

The first approved source family shall be CDC’s public-use Lyme surveillance datasets hosted at `data.cdc.gov`. The pipeline must retain the surveillance reporting eras as separate source versions and must not perform unqualified cross-era trend comparisons.

| Dataset ID | Source era and intended use | Grain | Required restriction |
|---|---|---|---|
| `84rx-ksgd` | Aggregated geography, 1992–2007 | Annual county × case status × sex × age | Separate pre-2008 reporting era |
| `qtbi-xd4i` | Aggregated geography, 2008–2021 | Annual county × case status × sex × age | Preserve 2008–2021 era semantics |
| `x5j9-wybp` | Aggregated geography, 2022–current | Annual county × case status × sex × age | Do not directly compare with prior eras without reviewed methodology |
| `e2a5-s9pr` | Line-listed, no geography, 1992–2007 | De-identified national records | Must not be joined to county contextual data |
| `abzs-b3gw` | Line-listed, no geography, 2008–2021 | De-identified national records | Must not be joined to county contextual data |
| `9mtj-y2ba` | Line-listed, no geography, 2022–current | De-identified national records | Must not be joined to county contextual data |

The first complete end-to-end implementation shall start with `x5j9-wybp`, the current geographic dataset. It shall then add `qtbi-xd4i` as a separate historical source version. The older and line-listed datasets remain registered candidates until their source-specific mappings and review decisions are complete.

### CDC/Socrata access profile requirements

- Use a source-verified CDC Socrata endpoint. The connector may use SODA query or documented export endpoints, but it must record the actual endpoint/version used.
- Store `SOCRATA_APP_TOKEN` in `.env` for local development and an approved secret store/integration for deployed environments. Never place its value in code, artifacts, logs, or Snowflake `VARIANT` columns.
- Capture view metadata and sample/schema evidence before full acquisition.
- Use a deterministic source order. Offset pagination without an explicit order is prohibited.
- Record every page/export request, response checksum, retrieved row count, and retry.
- Store the unchanged payload and manifest with SHA-256 before loading the dataset-specific `RAW` table.
- Preserve original fields and the distinction between numeric zero, null, unknown, suppressed, and not-reported values.

## Initial `.env` contract

Create `.env.example` in the implementation repository with names only:

```dotenv
# Required for scheduled Data.gov Catalog API v4 discovery.
DATA_GOV_API_KEY=

# Recommended for Socrata/HealthData/ODN discovery and required if source policy requires it.
SOCRATA_APP_TOKEN=

# Snowflake connection values are defined in implementation-decisions.md.
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_ROLE=
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_DATABASE=
SNOWFLAKE_PRIVATE_KEY_PATH=
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=

# DigitalOcean App Platform only: encrypted runtime secret, never a committed value.
SNOWFLAKE_PRIVATE_KEY_B64=
```

`.env` must be ignored by Git. `.env.example` may be committed only with blank values. Production secrets must come from the chosen secret-management mechanism, not a deployed `.env` file.

## Required records and deliverables

- Version-controlled `catalog-search-terms.json` and a documented checksum in every discovery run.
- Catalog adapters for the three named catalogs.
- Normalized catalog dataset/resource records, raw response artifacts, request ledger, and source assessments.
- Data-steward approval workflow that gates full ingestion.
- A CDC/Socrata source profile, source-specific RAW table, schema/quality contract, and STAGING mapping for `x5j9-wybp`.
- End-to-end lineage from discovery term and catalog response through raw artifact, RAW load, source version, STAGING transformation, and one CONFORMED/ANALYTICS consumer.

## Acceptance criteria

- The discovery pipeline loads the JSON configuration, searches all three catalogs for every enabled initial term, paginates fully, and records each request and raw response artifact.
- Search results are deduplicated without deleting their original catalog observations; authoritative publisher resources are identified when possible.
- No full payload is acquired until a sample, schema, documentation snapshot, score, and steward approval exist.
- A Data.gov v4 run fails clearly when `DATA_GOV_API_KEY` is absent; no key value is written to logs or tables.
- A Socrata run logs all pages in deterministic order and retains a failed or partial attempt rather than silently omitting it.
- The CDC `x5j9-wybp` pipeline is traceable from search term through catalog record, resource, approval, artifact checksum, RAW load, source version, STAGING run, and consumer output.
- Tests prove that line-listed CDC data without geography cannot be joined to county-level contextual facts and that surveillance eras remain distinguishable.

## References

- [Data.gov Catalog API documentation](https://resources.data.gov/catalog-api/) — current v4 endpoint, API-key requirement, and cursor pagination.
- [Snowflake Data Provenance Implementation](SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md) — required governance and lineage records.

The complete term taxonomy, catalog list, source-routing behavior, and CDC reference-source requirements needed for implementation are included in this handoff package. The broader originating research corpus is intentionally not bundled because it is context, not an implementation dependency.
