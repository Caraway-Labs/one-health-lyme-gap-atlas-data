# Story #190 acceptance matrix

| #190 acceptance requirement | Contract/code artifact | Test/evidence | Status |
| --- | --- | --- | --- |
| Current-state gap matrix against exact audited main SHA | `current-state-gap-matrix-2026-09-24.md` | `origin/main` = `e63c0c9aed93197819050d5b6b695a3afee32ea9`; matrix committed first | Complete |
| One authoritative v1 model reusing release concepts | `atlas-semantic-domain-v1.md`; `semantic_domain.py`; ADR 0035 | Focused contract tests | Complete for #190; ADR proposed for human review |
| Stable IDs, versions, cardinalities, units, denominators, grain, time, strata, origin, value states | v1 domain contract and validator | Positive/negative parameterized tests | Complete for #190 |
| Current five-source county release unchanged | v1 contract maps existing hierarchy; no release or migration edits | Test introspects 14 builder slots and 3,144/14 constants; historical diff check | Fixture/static compatibility proven; no database replay |
| NEON site/event collection/testing, #158 derived metric, #159 coverage/priority, source-only case | v1 typed envelope and native/derived tests | `test_native_and_derived_shapes` | Representative fixture proof only; #192 owns full source mapping |
| Preserve representativeness, unknown/unavailable, eligibility/quality limits, evidence basis | v1 contract composes #157–#159; validator checks site/event and source-only geography, value states, evidence basis | Negative tests for geography, states, provenance, origin; basis revision test | Complete for #190; exact-source eligibility remains governed by #159 and detailed mapping by #192 |
| Metadata versus semantic meaning evolution | `meaning_signature`; version-transition table | Label-stability and duplicate/conflicting meaning tests | Complete core rule; #191 metadata revisions and #195 cross-version gates remain |
| Reject duplicate identities, incompatible unit/denominator/grain, contradictory states, invalid strata, provenance gaps, unversioned meaning | `validate_measures`, `validate_observation`, `validate_domain` | Parameterized negative tests | Complete core invariants; #195 expands across mapped registries |
| Preserve V071/V072 and V100–V102 history, release pointer, public behavior | No changes to migration, release builder, pointer, or views | Diff scope and existing full regression suite | Complete at code/fixture level; no database mutation |
| ADR and contracts name authoritative files, decisions, downstream obligations | ADR 0035; v1 contract; gap matrix | Documentation review | Proposed ADR pending human protected review; #191–#195 obligations explicit |
| Distinguish fixture from database/deployment evidence | v1 contract and this matrix | Gate results attached to PR | Complete; no new database behavior claimed |

Story #190 has no new database path, so no DEV/PROD integration or consumer proof is claimed. Hosted Quality and protected review are required before merge. The full Epic #188 remains open for #191–#195.
