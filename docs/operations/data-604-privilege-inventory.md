# DATA #604 lineage privilege inventory and DEV evidence

Observed 2026-10-05 with named PAT connections. `ATLAS_DEV_READ` resolved to `MATTHEWCARAWAY / OH_LYME_DEV_READ / ONE_HEALTH_LYME_GAP_ATLAS_DEV / OH_LYME_DEV_INGEST_XS_WH`. `ATLAS_DEV_OWNER` resolved to the same user, `OH_LYME_DEV_OWNER`, DEV database and warehouse. `ATLAS_PROD_RUNTIME_AUDIT` resolved to `OH_LYME_PROD_RUNTIME / ONE_HEALTH_LYME_GAP_ATLAS_PROD / OH_LYME_PROD_INGEST_XS_WH`. `ATLAS_PROD_MIGRATOR` resolved to `OH_LYME_PROD_MIGRATION_DEPLOYER` with no default database or warehouse. PROD grant inspection used fully qualified objects and no mutation. No ACCOUNTADMIN session was used.

## Baseline matrix

`SELECT` below is object-level unless noted. `OWNERSHIP` implies owner control and is not an audit grant. Direct grants are from `SHOW GRANTS ON TABLE`/`SHOW GRANTS TO ROLE` where observed; inherited owner membership is noted separately. Historical migration references: V069 (generic conformed table), V071 and V099 (semantic storage and release deployer), V103 (immutable revisions), ADR 0030 (role membership).

| Environment / object | READ | OWNER | RUNTIME | MIGRATION_DEPLOYER | Evidence / reason |
| --- | --- | --- | --- | --- | --- |
| DEV `PRESENTATION.SEMANTIC_OBSERVATIONS` | No SELECT; direct query denied `002003` | Direct SELECT | No source grant | Direct OWNERSHIP | Live grant inspection through DEV OWNER; semantic owner/release operations. |
| DEV `CONFORMED.GOVERNED_SOURCE_RECORDS` | No schema USAGE; direct query denied `002003` | No visible privilege; DEV OWNER `SHOW GRANTS` denied `002003` | V069 SELECT/INSERT/UPDATE, now ADR 0030 RUNTIME | V069 creator/owner path | Source-controlled V069; complete effective grant sweep was unavailable to the configured DEV identities. |
| PROD `PRESENTATION.SEMANTIC_OBSERVATIONS` | No direct SELECT in live table grants | Direct SELECT | No direct SELECT | Direct SELECT/INSERT; ACCOUNTADMIN owns table | Live `SHOW GRANTS ON TABLE`; protected semantic release assembly. |
| PROD `CONFORMED.GOVERNED_SOURCE_RECORDS` | No direct grant | No direct grant | Direct SELECT/INSERT/UPDATE | Direct OWNERSHIP | Live `SHOW GRANTS ON TABLE`; runtime ingestion. |
| PROD `GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS` | No direct grant | No direct grant | Direct SELECT/INSERT | Direct OWNERSHIP and SELECT | Live `SHOW GRANTS ON TABLE`; immutable V103 capture. |
| DEV/PROD current-release presentation views | Existing object-level SELECT | View ownership/creation | No broad semantic base access | Deployment rights | V072/V127/V128 and READ grant inventories; consumer projections cannot prove internal record/artifact hashes. |

`OH_LYME_{ENV}_OWNER` inherits `STREAMLIT_OWNER`, and `MIGRATION_DEPLOYER` inherits OWNER per ADR 0030. That hierarchy does not give READ a base-table right and does not make OWNER an ingestion runtime. The live PROD grant inventory is authoritative for the two named base tables; source-controlled migrations explain why the grants exist. A complete account-wide inherited-privilege sweep would require a separately authorized administrative inventory and was not used as a prerequisite to this bounded change.

## DEV V137 acceptance

Protected [DEV run 37386288817](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/37386288817) on branch SHA `4558338` passed the repository gates and applied V137 only. The DEV migration ledger records `V137__semantic_lineage_audit_view.sql`, SHA-256 `504fa5725f7169a439655b894799d86dbad400bce5a9f9dc749c44f111590ac7`, at 2026-10-05 16:05:52 MDT. `ATLAS_DEV_READ` can SELECT the secure view; its live grant list shows direct USAGE on `LINEAGE_AUDIT` and direct SELECT on `LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V`, both granted by DEV MIGRATION_DEPLOYER. Direct SELECT on semantic and conformed base tables is denied `002003` under READ.

For release `governed-2026-09-17-unknown-coverage`, READ returned 22,008 SVI/RUCC audit rows representing 22,008 distinct observation IDs. All 22,008 resolved to `LEGACY_CONFORMED`; zero were missing governed source-version, ingestion-run, artifact-digest or conformed-record anchors, and zero semantic/governed row hashes differed. A sampled RUCC row showed equal source-version IDs, equal run IDs, non-null artifact ID/SHA-256 and conformed record ID, and identical row hashes. This is live source-backed proof for the generic conformed lineage path, not merely a fixture or SELECT smoke test.

The view returned 88,032 rows across both DEV releases: 44,016 generic SVI/RUCC matches and 44,016 `UNMATCHED` observations from human, tick and pathogen families. Those families use source-specific authority tables rather than `CONFORMED.GOVERNED_SOURCE_RECORDS`; their unmatched status must not be represented as a successful generic conformed match. Of the unmatched rows, the pathogen family also has missing generic artifact digest for 3,144 observations per release. DATA #604 acceptance should explicitly retain this boundary and decide whether source-specific lineage is in scope before calling the route complete for every semantic observation.

## PROD pending

V137 has not been applied in PROD. No PROD READ PAT connection is configured in the reconciled connection inventory, so a single-identity PROD lineage proof cannot yet be run. The existing protected PROD promotion path, exact reviewed source ref/image digest, effective grant checks, and representative PROD SVI/RUCC validation remain required. ACCOUNTADMIN is prohibited for normal lineage verification.
