# DATA377 failure-packet integration (offline)

Starting merged main: 9e236ef78d9559ed3918dcbeeaa4874d1033bba2 (PR561).
DATA376 merge: 50809e2c56450863a7e680716ab4a482b427aa7a (PR563).
Frozen expectations remain 3c81b471c802b1ad7e9361740319bd7cbeb50b4b.
The only new engineering surface is the capstone integration test and this report;
no DATA376 schema, collector, packet fixture or unit test is copied or changed.

`tests/test_delivery_failure_integration.py` invokes the reviewed `validate_packet`
and `review_context` APIs against all four actual historical packets. It verifies
packet-to-corpus boundary and missing-check mappings, retained STATIC regression
and UNKNOWN repair/workload/role, independent behavioral-review requirements,
and no input mutation. Static-proof repair claims and tampered correlations reject.
An impossible UTC calendar date passes schema-only annotation validation but is
rejected by the mandatory Python API. Valid packet syntax never becomes live proof.

The #366 supplied offline denial continues to match frozen BLOCKED for the actual
SEMANTIC_RELEASES INSERT, while identity and grant authority remain UNKNOWN.
Packet UNKNOWN role is never replaced with desired executor policy. #336/#353/#365
remain UNKNOWN for absent engine proof; canonical membership arithmetic remains
a separate fixture result. No live failure injection, SQL, grants, or deployment.

Reproduce with:
`uv run pytest -q tests/test_delivery_failure_integration.py tests/test_delivery_regressions.py tests/test_failure_evidence.py`
then the unchanged exact-head Quality workflow. Static/offline packet validation,
real driver/engine execution, deployment and live functional proof are distinct.

## Remaining engineering under existing authority

- Consume the separate DATA372 owner's final reviewed snapshot/freshness/drift API
  and fixtures; add deterministic stale/partial/hidden metadata comparisons without
  copying the exporter or changing frozen expectations.
- Finish a version-bound aggregate capstone report referencing packet API v1,
  operation contract v1, context checker, frozen corpus and final snapshot version.
- Create pinned, bounded recipe helpers/tests and investigate available installed
  Codex launch/discovery and representative prompt-routing checks; document actual
  outcomes without claiming deterministic agent behavior.
- Parent independently reviews the integration change, refreshes main, reruns exact
  Quality and serializes merge and existing deployment if needed.

## External prerequisite / user action only if not already available

Real Snowflake recipe/role proof needs a specifically approved existing isolated
DEV target and its least-privilege connection/execution scope. No new credentials,
grants or environment-validation bypass may be created. The parent can identify
an existing approved setup under current authority; only absent scope/access needs
owner action. Missing/expired credentials require the account owner, not browser
login or elevated fallback. PROD proof remains separately scoped.

DATA372 delivery and independent reviews are engineering dependencies, not new
scientific/product decisions. DATA374/377 remain open; this offline integration
alone does not satisfy live recipe, routing or final capstone acceptance.
