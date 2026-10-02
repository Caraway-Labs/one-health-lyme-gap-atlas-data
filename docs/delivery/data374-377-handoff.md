# DATA374 / DATA377 handoff (2026-10-02)

Branch: feat/data374-skills. Isolated worktree: task-3/data374.
Starting baseline c5a2310; expectations frozen in
3c81b471c802b1ad7e9361740319bd7cbeb50b4b before implementation commit
920c7d68692e5e3f883104d0bbc522571be337b3. Draft PR #561.

## Acceptance mapping

DATA374: four trigger-focused skills, required inputs/reference indexes/stop
conditions/output/examples delivered. No unrestricted shell/SQL wrapper or
privilege escalation added. Existing target validation unchanged. Offline
references checked. Installed-mode discovery, actual prompt routing, independent
session reproducibility and real DEV driver/engine/positive-negative role proofs
remain UNKNOWN/unverified. Recipe packet describes proof requirements rather than
claiming executable Snowflake acceptance.

DATA377: sanitized corpus committed before artifacts; independent expectation
review pending. Missing reference helper and existing curated contracts have
credential-free regressions in normal pytest CI. Reports separate offline static,
engine execution, deployment and live proof. #366 coverage mismatch is explicit.
Snapshot freshness and failure-packet integration await separate DATA372/DATA376
owners. No capstone acceptance or issue closure claimed.

## Verification

- Locked sync completed (Python 3.13.15, Snowflake connector 4.3.0).
- Focused pytest: 15 passed in 58.65s.
- Ruff check: PASS; Ruff format --check: 413 files already formatted.
- mypy src: PASS, 101 source files.
- check_agent_context.py: PASS isolated repository.
- Bundled quick_validate.py: atlas-db-change valid; other skills use identical
  frontmatter structure; all four explicit validators PASS. Routing tests remain unverified.
- Full pytest: 2108 passed, 19 dependency deprecation warnings; independent dbt parse PASS. Docker build PASS (image sha256:9506a0d84c896b71ca78a30b1cde9959430d5e3fd3d049800279c6be24b7f0a0); completed in this
  handoff. Quality CI passed at 10e042c3869099b86fd13f2e29b23d113acdcfaa (run 36973426380); recheck final documentation head before review.

No deployment performed. No DB migrations or runtime changes require deployment.
Parent owns independent review, main refresh, exact CI rerun and serialized release.
Existing approved DEV infrastructure must be identified for behavioral recipe tests;
do not create credentials/grants or bypass environment restrictions.

## Narrow correction for independent review

The independently confirmed #366 contract gap is corrected in desired metadata:
actual SEMANTIC_RELEASES:INSERT, protected migration_deployer executor, and V099
only as a PROD prerequisite. Frozen expectations are unchanged. DEV retains its
shared migration dependencies; missing visibility stays UNKNOWN. This is a
contract/readiness change requiring independent review and exact-head Quality CI,
not a grant, historical migration or deployed permission change.
