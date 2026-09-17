# Governed county identity and geometry contract v1

## Scope

This contract is the Epic #252 replacement boundary for the county identity
and geometry fields in the frozen `alpha-2026-08-06` baseline. It does not
choose a map vendor, alter the public API, or make a claim about individual
risk.

## Authoritative source and use review

| Field | Recorded value |
| --- | --- |
| Publisher | CDC/ATSDR Geospatial Research, Analysis, and Services Program |
| Dataset | CDC/ATSDR Social Vulnerability Index 2022, United States county layer |
| Endpoint | `CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer/1` |
| Vintage | 2022; source population and vulnerability fields use the 2018-2022 ACS period |
| Publisher documentation | https://www.atsdr.cdc.gov/placeandhealth/svi/data_documentation_download.html |
| Geometry delivery | GeoJSON from the publisher FeatureServer |
| CRS | EPSG:4326 |
| Generalization | Publisher request parameter `maxAllowableOffset=0.01`; no Atlas-side geometry transformation |
| Use fact | The publisher makes SVI data and documentation available for download and identifies the source for citation. No separate license field was supplied by the FeatureServer response; release use remains conditional on retaining the publisher citation and re-reviewing changed publisher terms or methodology. |

The SVI is a place-based contextual index. It is not a causal driver, an
individual risk estimate, a diagnosis, or a substitute for the separate
surveillance evidence contributions.

## Immutable DEV evidence

The accepted evidence run is the Tier-B SVI ingestion run
`9c13471a-e763-4864-bb69-5264b4800e34`.

| Check | Result |
| --- | --- |
| Source definition | `cdc_atsdr_svi_2022_county` v1 |
| Retained artifact SHA-256 | `dc042342a2e5abc108af67b439ec04c86da8b61f9bdd1cf1b1e5ee0462dea7b2` |
| Source version | `86bed331-992b-4627-a992-ca4c5da7f392` (`CONDITIONAL`) |
| Source review decision | `8613aa09-55ab-4d2e-a1a6-a427e965cd4a` |
| Coverage | 3,144 unique five-digit county FIPS identifiers |
| Geometry check | Blocking `svi_geometry_valid` passed; publisher GeoJSON `Polygon` or `MultiPolygon` geometry is retained in the source row |
| Join fields | `STCNTY` is the canonical five-digit FIPS join; `COUNTY`, `ST_ABBR`, and `STATE` are display metadata, never identity |
| Scope | 51 states or districts; 3,109 contiguous-scope and 35 non-contiguous-scope county records, matching the frozen Alpha baseline |

The generic ingestion run preserved the source row, geometry, source row hash,
retrieval timestamp, artifact checksum, source definition version, and
ingestion run ID through `RAW`, `STAGING`, and `CONFORMED`.

## Release and API rules

1. A semantic-release manifest must pin the source version, ingestion run,
   artifact ID, and artifact SHA-256 above or a later separately reviewed
   replacement.
2. The semantic builder must reject duplicate FIPS, any missing FIPS, any
   geometry other than a publisher `Polygon` or `MultiPolygon`, or any coverage
   other than 3,144 unique FIPS. It must not flatten, simplify, or otherwise
   transform the publisher geometry.
3. Geometry unavailability must not remove the API or web table/text path.
   The non-map result remains a required accessible alternative.
4. A publisher revision, changed simplification, CRS change, changed
   methodology, or changed publisher terms blocks reuse until this contract
   and the source decision are reviewed again.

## Alpha comparison disposition

The frozen Alpha baseline records 3,144 county polygon geometries sourced from
the same CDC/ATSDR SVI 2022 county layer. This contract classifies the current
identity and geometry mapping as `GEOMETRY`/`GEOGRAPHY_SCOPE` parity evidence,
not as a new analytical source or score input. A later semantic-release
comparison must still classify every byte- or shape-level difference before
public publication.
