# Epic #159 consolidated remediation matrix

Baseline: `epic-159-governed-audit.json`, audited main
`b59a93439009fe5b8c827a17bb4712cc996e5228`.
Scope: internal DEV #171 coverage and #172 surveillance investigation triage.
The original v1 results and V101/V102 migration history remain immutable.

| Audit defect | Root cause | Code change | Contract change | Regression tests | Status |
| --- | --- | --- | --- | --- | --- |
| AUDIT-159-001 | County dimension accepted without exact source mapping | Shared `scientific_attestation`; county positive-state gate | Scientific eligibility v1; coverage result v2 | Registry county ID/label/mapping matrix | Implemented; DEV pending |
| AUDIT-159-002 | Active collection omitted required source-specific stratum proof | Taxon, life stage, method, and effort-unit gates | Scientific eligibility v1; coverage result v2 | Registry collection matrix, unmapped ADULT, aggregate/MIXED | Implemented; DEV pending |
| AUDIT-159-003 | Testing mapping/scope could use foreign or missing proof | Exact-source target/result checks and explicit testing-scope attestation | Canonical optional evidence fields; coverage result v2 | Foreign mapping, missing scope/ID, testing matrix | Implemented; DEV pending |
| AUDIT-159-004 | #172 reconstructed collection comparison from labels | Attested canonical IDs for taxon, life stage, method, and unit | Priority result v2 | Collection matrix and tampered display cases | Implemented; DEV pending |
| AUDIT-159-005 | #172 inferred individual testing scope | Consume #171 testing attestation only | Priority result v2 | Missing/aggregate scope, foreign target, no cohort/tie | Implemented; DEV pending |
| AUDIT-159-006 | PERIOD evidence coerced to point time and omitted from identity | Explicit temporal gate and identity field | Coverage and priority result v2 | PERIOD vs POINT identity and no cohort | Implemented; DEV pending |
| AUDIT-159-007 | County cohort allowed unresolved/aggregate/source-incompatible dimension | Exact county attestation, resolved FIPS, approved tuple | Scientific eligibility v1; priority result v2 | County matrix, aggregate/source-only cases | Implemented; DEV pending |
| AUDIT-159-008 | Incompatible or missing source/version/vintage context could cohort | Governed tuple validation and attestation recheck | Scientific eligibility v1 tuple table; priority result v2 | Version mismatch, mixed vintage, foreign mapping | Implemented; DEV pending |
| AUDIT-159-009 | Safe projection lost eligibility proof; identity omitted it | Versioned safe attestations included in v2 revision | Coverage and priority result v2 | Full-path matrix, ID/label identity equivalence | Implemented; DEV pending |
| AUDIT-159-010 | Secret-like path could pass an allowlisted value | Shared safe path validator in both serializers | Coverage and priority result v2 safe-field rules | Private-key path rejection, opaque ID acceptance | Implemented; DEV pending |
| AUDIT-159-011 | Numeric positive effort could contradict UNKNOWN missingness | Explicit contradiction gate, retained safe missingness | Coverage methodology clarification and result v2 | Positive effort/UNKNOWN missingness no cohort | Implemented; DEV pending |
| AUDIT-159-012 | Evidence basis and changed scientific proof collided under immutable ID | Evidence basis in result revision/ID, normalized scientific context identity | ADR 0034; coverage and priority result v2 | Synthetic/source-backed ID split, immutable replay | Implemented; DEV pending |

Permanent generated regression evidence: 30 canonical values, 31 relevant
mapping rules, 124 source/value/representation combinations, plus absent,
foreign, unsupported, conflicting, aggregate, and version-mismatch probes.
The test reports unexpected positive/cohort and rejected-positive/cohort counts.

Current-code source-backed replay remains `NOT PROVEN`. This matrix does not
authorize new source acquisition, privilege escalation, PROD/public release,
or closure of Epic #159. Final status requires protected Quality and bounded
exact-main DEV verification after merge.
