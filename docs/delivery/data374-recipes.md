# DATA374 boundary-specific recipe packet

Baseline: c5a2310; frozen DATA377 expectations: 3c81b47. No migration,
role, environment validation, snapshot exporter or failure collector is changed.

These skills route to existing implementations; they do not install a second
SQL executor or deployment engine. Repository discovery follows
https://developers.openai.com/codex/skills/ (`.agents/skills` from launch directory
through repository ancestors). Subsequent installed discovery, metadata routing
and bounded DEV reads are recorded in
[runtime verification](data374-readonly-verification.md). End-to-end skill execution
and interactive/assembled-workspace discovery remain unverified.

| Recipe | Existing implementation / regression context | Required proof |
| --- | --- | --- |
| Connector batch JSON/VARIANT and timestamps | semantic release implementation; #336 | Lock driver/runtime versions from uv.lock; execute actual batch with fixture values in an approved isolated DEV setup and read back JSON/timestamps. Do not infer SQL Scripting behavior. |
| Procedure binding | V091; #353 | Invoke exact procedure signature with positive/negative parameters under caller rights; separately verify applicable owner-rights procedures. |
| Replacement grants and bootstrap | deployment-promotion; V056/V057 and V099; #366 | Distinct executor/runtime/authority role observations and behavioral allow/deny checks; replacement retains documented USAGE. No new grants here. |
| Canonical county coverage | V098; #365 | Fixture canonical 01001/01003/01005, source 01001/01003/01999: two of three, missing 01005 UNKNOWN, 01999 source-only/unallocated. |
| Rerun / partial failure | existing migration runner and ledger tests | Preserve checksum-locked bytes, reject changed checksums, retain append-only evidence and use protected forward recovery. Never induce live destructive failure. |

Actual driver SELECT, anonymous scripting binding and canonical CTE checks passed
under the existing DEV read role. Bulk INSERT, exact stored-procedure execution,
role allow/deny and parity procedure evidence remain **UNKNOWN / unverified**.
This packet does not promote offline or read-only proof to repair acceptance. No scratch
database allowlist, credential, grant, or environment bypass is introduced.

Use `uv run pytest tests/test_delivery_regressions.py tests/test_operation_capabilities.py
 tests/test_handoff_validation.py` for offline comparison, then the unchanged Quality
workflow for full acceptance. Separate snapshot/failure owners must provide final
DATA372/DATA376 artifacts before DATA377 capstone acceptance. Independent review of
the frozen rubric must precede acceptance of the comparison. Parent serializes review,
main refresh, exact CI and any deployment. Documentation/fixtures alone need no runtime
migration; live recipe evidence needs an approved existing DEV test target.
