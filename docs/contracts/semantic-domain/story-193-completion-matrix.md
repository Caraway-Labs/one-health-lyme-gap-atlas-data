# Story #193 acceptance and evidence matrix

Evidence is separated by class. `tests/test_semantic_lineage.py` uses synthetic fixtures and an in-memory authority snapshot; it does not claim live source replay, Snowflake integration, or public API behavior. No database objects, roles, migrations, release pointer, or public views change in this story.

| #193 acceptance criterion | Artifact | Test/evidence | Status |
| --- | --- | --- | --- |
| Inventory complete chain and missing edges | `story-193-lineage-gap-matrix-2026-09-24.md` | Audited exact `origin/main` `3958e335eedefa2417904c68ef192d71a6a0358d`; source code and contracts | COMPLETE — contract/design |
| Multiple inputs, transformation versions, immutable revisions and supersession | `atlas-semantic-lineage-v1.md`; `semantic_lineage.py`; minimal order normalization in `semantic_domain.py` | Derived two-input and ordering/duplicate fixtures; existing historical stores untouched | COMPLETE — fixture/unit |
| Safe normalization and eligibility references | `semantic_lineage.py` edge/proof joins | Tick/NEON normalization and derived eligibility fixtures; orphan proof rejection | COMPLETE — fixture/unit; owning proof content remains governed by #156/#159 |
| Evidence basis and result revision distinctions | Contract and result authority join | #158 and #159 derived fixtures; invalid basis, input and result mismatch rejection | COMPLETE — fixture/unit; no source-backed replay claim |
| Reject orphan/mismatched source, run, artifact, hash, transform, cross-release joins | `semantic_lineage.py` | Negative fixture suite for each relationship | COMPLETE — fixture/unit |
| Safe attributable consumer projection | `consumer_safe_lineage()` and contract | Projection tests retain publisher, source, method, limitations; reject restricted path/URL | COMPLETE — contract/fixture; #194 owns API/public exposure |
| End-to-end representative traces | Ten parameterized traces in `tests/test_semantic_lineage.py` | Human, SVI, RUCC, tick, pathogen, NEON collection/testing, #158, #159 coverage, source-only | COMPLETE — synthetic fixtures; comprehensive live mappings owned by #192 |
| New database behavior under intended role; no broadened data access | No database behavior changed, no new table/view/role/connector | Repository diff and no-Snowflake scope review | NOT APPLICABLE — no database integration claim; #192/#195 own later changed DB paths |

Completion requires protected PR Quality and human merge authorization. This matrix is updated with actual gate results in the PR, and #193 may be closed only after the approved merge and exact-main checks. Epic #188 remains open.

## Local gate evidence

On the Story #193 worktree, `uv run ruff check .` and `uv run ruff format --check .` passed; `uv run mypy src` passed for 70 source files; `uv run pytest -q` passed 805 tests; and offline `uv run dbt parse --project-dir dbt --profiles-dir dbt` passed. `git diff --cached --check` passed before the final two negative-case tests, and the final diff check is repeated before commit. These are local contract/fixture gates; no Snowflake runtime or source-backed integration claim is made.
