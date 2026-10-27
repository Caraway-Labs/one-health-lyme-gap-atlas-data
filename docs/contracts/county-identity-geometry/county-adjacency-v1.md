# County adjacency v1

Status: proposed for human review under issue #872 and the amendment to [ADR 0036](../../adr/0036-county-analysis-geometry-and-area-weighting.md). Owner: Atlas data stewardship. This contract adds a neighbor list. It does not change the 3,144 county identities, the analysis geometry, or the display geometry.

## Source

The source is the U.S. Census Bureau County Adjacency File, 2025 vintage.

| Item | Value |
| --- | --- |
| Landing page | https://www.census.gov/geographies/reference-files/time-series/geo/county-adjacency.2025.html |
| File URL | https://www2.census.gov/geo/docs/reference/county_adjacency/county_adjacency2025.txt |
| File name | `county_adjacency2025.txt` |
| sha256 | `8233d2aed342f62eb02bae9f9002ad1d8fc6bd82d739185eba8bad832bf8fc87` |
| Header | `County Name\|County GEOID\|Neighbor Name\|Neighbor GEOID\|Length` |
| Delimiter | pipe |
| Encoding | UTF-8 |

The release id is `census-county-adjacency-2025-8233d2ae`. It is the vintage plus the first eight characters of the pinned sha256. The same bytes reuse that release id. A different digest is a new reviewed release, not an edit of this one. The 2026 file was compared while writing the story and matched these in-scope pairs; it is not the pinned vintage.

Census materials may be reproduced with citation under the federal-government-work rule. The license basis recorded with the source is: U.S. federal government work, public domain. Cite the U.S. Census Bureau. Same basis as ADR 0036.

## Semantics

Adjacent means the counties share an edge or a point, including a boundary in water. The file lists each relationship in both directions. From 2025 on, a county is not listed as adjacent to itself. `Length` is the shared boundary in meters. Zero means point contact only.

The governed table keeps one undirected pair. `FIPS_A` is the smaller five-character FIPS and `FIPS_B` is the larger. `CONTACT_TYPE` is `EDGE` when length is greater than zero and `POINT` when length is zero. `SHARED_BOUNDARY_M` is that length. A consumer that wants rook neighbors keeps `EDGE` (8,938 pairs). A consumer that wants queen neighbors keeps every pair (9,286).

The raw landing table keeps every published row, including Puerto Rico and the island areas. The governed table and `PRESENTATION.COUNTY_ADJACENCY_V1` keep pairs whose two counties are both in the frozen 3,144-ID project reference. State FIPS 60, 66, 69, 72, and 78 are excluded. A pair with one county inside that reference and one outside fails the load.

Counties with a blank neighbor are legal published rows. They are not stored as pairs. Inside the project reference the only such counties are `15001` Hawaii, `15003` Honolulu, and `15007` Kauai. `15005` Kalawao and `15009` Maui are neighbors of each other. Nantucket, Dukes, and San Juan County, Washington have neighbors across water and are not islands. The District of Columbia and Alaska are not islands. Alaska is its own connected component.

Connecticut uses the nine planning regions `09110` through `09190`. Alaska includes the Valdez-Cordova split `02063` and `02066`. Legacy Connecticut county codes are out of scope. Joins use the five-character FIPS only. Names are not join keys.

The governed table and the presentation view have no geography, geometry, or GeoJSON column.

## Relations

| Object | Role |
| --- | --- |
| `RAW.CENSUS_COUNTY_ADJACENCY_2025` | Published rows, including areas outside the project reference, with run id, URL, file name, vintage, license basis, retrieval time, and sha256. |
| `CONFORMED.COUNTY_ADJACENCY` | Undirected in-scope pairs for one release id. |
| `PRESENTATION.COUNTY_ADJACENCY_V1` | The columns of the governed table for release `census-county-adjacency-2025-8233d2ae` only. |

`OH_LYME_{ENV}_READ` receives `SELECT` on the view. The loader role receives the table DML required by MERGE. This contract does not grant `OH_LYME_PROD_ML_EDA_READ`. A future grant on presentation views is a separate check owned by the ML read acceptance scenario.

## Load rules

The HTTP CSV adapter reads the configured delimiter. The default remains comma. This source sets `delimiter: "|"`. A download whose sha256 is not the pin fails closed. An asymmetric direction, unequal lengths, a self pair, a FIPS that is not five digits, or a pair that crosses the project reference fails closed. A second load of the same bytes and the same release id inserts, updates, and deletes zero governed rows.

Provenance for the run is the source definition plus `GOVERNANCE.RAW_ARTIFACTS` and `GOVERNANCE.INGESTION_RUNS`: URL, file name, vintage 2025, license basis, retrieval timestamp, and sha256.

## Evidence boundary

The pair counts were computed from the pinned file against `canonical-county-fips-2022.txt`. That computation is local. It is not a governed artifact registration, a DEV load, a PROD publication, or proof that an ML role can select the view. Those steps remain on the protected path.
