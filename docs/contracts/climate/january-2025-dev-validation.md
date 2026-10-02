# Bounded DEV validation and real review packet

PR #551 merged at `4b2fb225d7c8ca1e005b60d93301f46ad3c410a8` after exact-head
Quality passed all 1,901 tests. PR #550 is closed as superseded. DATA #443 / #496
and API #84 remain open for separate live publication gates.

## Historical pre-apply preparation

The pending set and access questions here describe preparation before V136 was
applied. Completed application and service verification are recorded below;
V136 is no longer pending in DEV.

Reserved `V136__dev_january_climate_consumer_views.sql`. Main/open PRs showed no
collision at preparation. DEV-only registration excludes V136 from PROD plans.
Its body is the exact reviewed two-view SQL from #551, with no grants, source
admission, release records or pointer changes.

A successful read-only DEV ledger query through V135 yields exactly:

```json
[{"version":"V136","filename":"V136__dev_january_climate_consumer_views.sql","sha256":"f3a33d21cba33f27a4e1683b65f9295f33c796f445c8c9ed82c84bd16948b2c2"}]
```

SHOW GRANTS reports that the existing DEV migration role owns PRESENTATION and
inherits DEV OWNER. V099/V103 define release-table/revision SELECT dependencies;
effective service-session access was unproved at preparation. Missing visibility never
authorizes grants or proves missing data.

This exact set, reviewed head and passing checks were presented before the
protected `deploy-dev.yml` dispatch coordinated with topology owner `01a0f0b0`.
The refreshed ledger and strict pending-set guard permitted only V136. It has
since been applied; no reader grants were added.

Read-only replacement preflight on 2026-10-02 used ATLAS_DEV_OWNER. The successful
identity query returned MATTHEWCARAWAY / OH_LYME_DEV_OWNER /
ONE_HEALTH_LYME_GAP_ATLAS_DEV / OH_LYME_DEV_INGEST_XS_WH. Successful
`SHOW VIEWS LIKE 'CURRENT_CLIMATE_%' IN SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.PRESENTATION`
returned zero visible rows for both exact target names:
`CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V` and
`CURRENT_CLIMATE_MEASURE_METADATA_V`. Postapply evidence established that this
OWNER role cannot inspect the migration-owned views: its SHOW remained empty
and GET_DDL returned 002003. The original observation was privilege-filtered,
not catalog-complete absence proof. Future replacement preflight must use the
effective protected service/view-owner identity; inspect existing DDL and grants
and review an exact preservation plan before CREATE OR REPLACE.

V136 was applied alone by protected run `36946561555`, with checksum
`f3a33d21cba33f27a4e1683b65f9295f33c796f445c8c9ed82c84bd16948b2c2`.
Read-only protected service run `36948833775` then verified the ledger checksum,
GET_DDL and DESCRIBE for both views, both complete AS bodies against the reviewed
SQL (preserving string literals), and successful COUNT(*) = 0 for each.
Observations has 45 columns; metadata has 14. Existing grants show OWNERSHIP
only, with no SELECT grant on either view. API reader proof remains unresolved;
this diagnostic grants nothing and does not establish PROD availability.

Bounded service-user history returned just the two successful V136 CREATE_VIEW
statements, at 00:35:08.625 and 00:35:09.140 UTC on 2026-10-02. Current catalog
creation times agree. There is no evidence of earlier definitions or grants in
that scope, but CREATE OR REPLACE resets creation metadata and can drop grants.
The current user's latest 10,000 queries over seven days (up to 100 returned
matching statements) are not account-complete history. Earlier objects/grants
outside that scope cannot be ruled out; no restoration is proposed without real
prior definitions/grants. No validation tables were visible in the diagnostic
session; fixture run `36946156651` separately confirmed successful DROP cleanup.

## Prepared fixture-only live checks

Explicit workflow mode `diagnose_climate_dev=true` runs
`scripts/verify_climate_dev.py` and exits before migration apply. It requires
the existing protected DEV migration service user/role/database/warehouse and
uses existing secrets. It does not switch roles or create credentials.

It executes actual reviewed view expressions for DOUBLE nonzero/zero/negative,
INTEGER zero/nonzero, precise DECIMAL/zero, JSON null and missing SQL-null
fields across all seven numeric quantities, including SQL IS NULL/API JSON
null and guarded native-DOUBLE codec parity. Then it stores/retrieves a roughly
26 MB document with 389,856 explicitly fictitious IDs through one randomly named
session-temporary VARIANT table and removes the table in `finally`. The document
states NOT_PUBLISHABLE_FIXTURE, PENDING review and no approved source versions.
It never enters semantic release storage or actual source/review authority.

After V136 apply, retain successful SELECT/describe evidence for both views
under the effective service/view owner. A release without the extension should
expose zero climate rows; prove this with a successful query. Separately prove
the actual API-reader identity's view-only access and connector decoding.
Failed SELECT is not an empty result. Fixture parity/storage proof is separate
from actual source/capture/publication and reader authority.

## Real source and four-definition review requirements

The four exact `/2`, semantic `2.0.0` definitions are generated by
`climate_semantics.january_measure_definitions`; historical `/1` is unchanged.
Review the full definitions with native NOAA TAVG, zero/negative temperatures,
explicit unavailable AK/HI, valid/source-supported 95% completeness and separate
monthly spatial support, 2022 canonical identities / 2025 geometry, and labeled
early-morning-ending 24-hour periods. Historical publication time stays unknown;
upstream modification time is distinct. No new product/version choice is needed.

A bounded DEV OWNER query succeeded and found both selected-run artifacts:

| Input | Artifact suffix | SHA256 | Bytes |
| --- | --- | --- | --- |
| NOAA | `658d13370fbec2095b1d601473cc5ce3` | `809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31` | 61,013,299 |
| TIGER | `510b7bc9e094d24e9094b19ba3b961ab` | `9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763` | 83,989,800 |

Full artifact IDs have prefix
`noaa_nclimgrid_daily_202501:c2eb2146-005d-44d2-bac4-e2805ca42577:`.
The same owner's DATA_SOURCE_VERSIONS query succeeded with zero rows bound to
this selected run. This is a specific catalog-linkage gap, not a statement
about other runs or PROD. Earlier DEV READ queries returned 002003 and were
not used as absence evidence.

Actual NOAA/TIGER source-version IDs, governed TIGER resource identity, active
approval decision joins and REVIEWED metadata are unresolved. No fixture or
guessed ID may fill those fields. DATA stewardship must identify existing
resource identities and register/review retained input relationships through
its authorized catalog process, without source activation or historical
ingestion. Retain real reviewed metadata revision objects and review evidence.

The [metadata/source review packet](january-2025-metadata-source-review-packet.json)
contains the four exact definitions and retained-input evidence. Its unknown
source-version IDs and PENDING reviews deliberately fail publication validation.
This packet is review material, not approved publication authority.

Merged PR #551 can be deployed dormant: annual release behavior remains unchanged,
and climate authority is issued only after strict extension verification. Its SQL
file is not an automatic migration. V136 is DEV-only and is needed for these DEV
consumer views, not for code-only deployment of #551. PROD publication still needs
an independently governed target migration and verified authority; V136 cannot
create PROD views or authorize a PROD pointer movement.

Target publication additionally requires canonical partition/revision read
proof, complete strict candidate reconstruction, frozen membership/digest and
intended-reader proof. If the publication identity lacks canonical-partition
SELECT, the owner must choose an already authorized identity or separately
review a bounded solution. This draft grants nothing.

## Supported adapter boundary

Use the reviewed explicit-authority path only:
`map_record` / `map_records` -> `validate_lineage` -> `project_consumer`, with
authority issued after `verified_climate_metadata_revisions` succeeds.
Broader #195 metadata/lineage validation wrappers do not propagate climate
authority and still fail closed. `page_consumer` accepts already projected
payloads and does not propagate or recheck approval authority.
API #84 remains with `01a0f63b`, feed release
with `01a0f5c6`, and topology with `01a0f0b0`. No Web work is included.
