# Surveillance priority result v1

Status: Internal DEV-only Story #172 output
Owner: Atlas data stewardship and engineering
Contract: `surveillance-priority-result-v1`
Methodology: [`surveillance-priority-v1`](surveillance-priority-v1.md)

The evaluator consumes one safe #171 result and emits its exact coverage result ID/revision, construct and state, unordered triage disposition, exact comparison cohort and cohort ID, tie group if eligible, source/version/vintage, native geography/time, safe lineage, #165/#166 quality envelope, retained reasons, evidence basis, and interpretation disclaimer. The safe projection retains source geography, native site/plot/event, contextual county relationship and mapping state, `NOT_COUNTY_REPRESENTATIVE`, tick species, life stage, pathogen target, collection method and effort unit, tested scope where applicable, and source-native date/period fields. Testing scope is the approved `INDIVIDUAL_PATHOGEN_TEST`; collection and county constructs show `NOT_APPLICABLE`. It does not infer a testing method absent from #171. `display_key` is the underlying stable coverage result ID, not a scientific rank. No numeric priority field exists.

The serializer allowlists these fields and rejects URL, credential, private-key, artifact, or raw-payload material. The complete cohort identity, safe scientific/geographic projection, and #171 result revision participate in deterministic `result_revision` and `result_id`; a newly distinguished cohort or changed #171 revision yields a distinct immutable result. Previously staged rows remain immutable. An identical replay is a no-op and a conflicting payload under the same ID fails closed. Snowflake standard-table primary keys are informational, so only the intended serial DEV runtime writer may stage results.

V102 creates `PRESENTATION.SURVEILLANCE_PRIORITY_DERIVED_RESULTS` only in DEV, with DEV runtime INSERT/SELECT and DEV read SELECT. It is a separate derived-result store because source observations, #169 numeric metric rows, #171 coverage rows, and the fixed county semantic release have different meanings and constraints. There is no PROD migration, public view, API/web change, or county release pointer change. The existing Atlas county priority score is untouched.

Fixture-based calculation and DEV persistence prove behavior and mechanics only. Current-code source-backed #171 replay is not proven under the authorized read identity. A source-backed #172 interpretation and operational usefulness review remain separate evidence requirements before public or production use.
