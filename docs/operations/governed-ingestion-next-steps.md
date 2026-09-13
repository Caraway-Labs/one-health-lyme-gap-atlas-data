# Governed ingestion: next steps

This diagram documents the source-onboarding path after metadata registration.
It is not an authorization to ingest, approve a source, run dbt, or promote to
production. The Alpha POC database remains outside this process.

```mermaid
flowchart LR
  A[Completed catalog registration\nmetadata only] --> B[CDC/Socrata x5j9-wybp candidate]
  B --> C[Assessment evidence\nmetadata, schema, ordered sample]
  C --> D{Data steward decision\nDEV source version}
  D -- Pending or rejected --> H[Hold candidate\nno source acquisition]
  D -- Approved --> E[Controlled DEV ingestion\nimmutable artifacts and provenance-bearing RAW]
  E --> F[dbt validation\nRAW --> STAGING --> CONFORMED]
  F --> G{DEV acceptance\nlineage, quality, and operational evidence}
  G -- Failure --> I[Stop and investigate\nno PROD promotion]
  G -- Passed --> J[Exercise DEV rollback\nredeploy a prior approved digest]
  J --> K{Separate steward decision\nPROD source version}
  K -- Not approved --> L[Hold PROD execution]
  K -- Approved --> M[Protected promotion\nsame DEV-tested immutable digest]
  M --> N[Controlled PROD ingestion\nand post-run verification]

  classDef gate fill:#fff3cd,stroke:#996c00,color:#3e2b00;
  classDef stop fill:#fde2e1,stroke:#a3312f,color:#50110f;
  class D,G,K gate;
  class H,I,L stop;
```

## What each step proves

1. **Steward review** establishes that the source has an acceptable use,
   provenance, license, geography, time semantics, and source-specific
   limitations. The pipeline supplies evidence; it cannot make this decision.
2. **Controlled DEV ingestion** obtains only the approved source version, keeps
   immutable artifacts and manifests, and loads source-faithful records to the
   isolated DEV `RAW` schema.
3. **Provenance and dbt validation** verifies the artifact-to-RAW lineage,
   row/load evidence, source-specific quality rules, and dbt results through
   `STAGING` and `CONFORMED`. A green deployment or a populated table alone is
   insufficient.
4. **DEV rollback exercise** proves the operational recovery path: the DEV job
   can be returned to a previously approved immutable image without rewriting
   retained artifacts or governance history.
5. **Separate PROD source approval** records an independent, environment-bound
   decision. A DEV approval must never be reused to activate a PROD source.
6. **Protected digest promotion** requires the production workflow and its
   designated approval to deploy the exact image digest already verified in
   DEV. It does not rebuild an image or make manual production changes.
7. **Controlled PROD ingestion and verification** runs the approved source on
   the production schedule and confirms the operational ledger, provenance,
   load, transformation, and rollback evidence.
