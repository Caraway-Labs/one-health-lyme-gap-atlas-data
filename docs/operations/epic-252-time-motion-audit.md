# Epic #252 time/motion audit and scorecard (Epic #294, Story #299)

Modeled on the [Epic #223 closeout scorecard](epic-223-closeout-scorecard.md)
pattern. Data sources: `gh issue view`/`gh pr view` timestamps for every story
and PR in the Epic #252 chain, and Story #295's
[role-inventory-dev.md](role-inventory-dev.md),
[role-inventory-prod.md](role-inventory-prod.md),
[connection-inventory.md](connection-inventory.md), and
[role-classification.md](role-classification.md). All timestamps captured
2026-09-16 via read-only `gh` calls; nothing in GitHub or Snowflake was
mutated to produce this audit.

## Method

For each story, the audit records: `createdAt`, the timestamp of the last
substantive progress/evidence comment before closure (or "still open" for
in-flight stories), `closedAt`, and the active review-to-merge window of the
PR(s) that implemented it. The gap between "evidence finished" and "issue
closed" isolates non-engineering (bookkeeping/session-cadence) overhead from
actual development time.

## Table 1 — Completed foundation chain (#253, #257, #258, #259, #260)

| Story | Created (UTC) | Evidence/last comment before close | Closed (UTC) | Elapsed create&rarr;close | Evidence&rarr;close lag |
|---|---|---|---|---|---|
| #253 | 09-13 21:06:05 | 09-15 02:26:48 | 09-15 02:27:27 | 29h21m | **39s** |
| #257 | 09-13 21:06:12 | 09-15 02:26:54 | 09-15 02:27:32 | 29h21m | **38s** |
| #258 | 09-13 21:06:14 | PR #268 merged 02:16:14 (`Closes #258`) | 09-15 02:16:15 | 29h10m | **1s** (auto-closed by merge) |
| #259 | 09-13 21:48:27 | 09-15 02:26:57 | 09-15 02:27:34 | 28h39m | **37s** |
| #260 | 09-13 22:03:40 | PR #266 merged 01:34:49 (`Closes #260`) | 09-15 01:34:50 | 27h31m | **1s** (auto-closed by merge) |

**Finding:** every completed story in this chain was closed within **one
minute** of its final evidence being ready — either automatically (`Closes
#N` in the merging PR: #258, #260) or manually, immediately after the
evidence comment (#253, #257, #259). The 27-29 hour "elapsed" figures are
almost entirely a **session-cadence gap**, not per-step friction: for
example, #259's last active-development comment lands at 09-14 01:44:52, then
nothing happens until the wrap-up/evidence comment at 09-15 02:26:57 (24h42m
later) — the gap between one work session ending and the next beginning, not
time lost to governance steps, approvals, or role/connection switching within
the session.

## Table 2 — PR active-time sample (review-to-merge window)

| PR | Story | Created | Merged | Active window |
|---|---|---|---|---|
| #261 | #259 | 09-13 22:53:57 | 09-13 22:55:26 | 1m29s |
| #262 | #259 | 09-14 00:42:04 | 09-14 00:43:46 | 1m42s |
| #263 | #259 | 09-14 00:59:00 | 09-14 01:00:36 | 1m36s |
| #264 | #259 | 09-14 01:07:42 | 09-14 01:09:08 | 1m26s |
| #265 | #260 | 09-14 01:15:47 | 09-14 01:17:29 | 1m42s |
| #266 | #260 | 09-15 01:33:00 | 09-15 01:34:49 | 1m49s |
| #268 | #258 | 09-15 02:14:42 | 09-15 02:16:14 | 1m32s |
| #280 | #279 | 09-15 06:02:14 | 09-15 06:09:19 | 7m5s |

**Finding:** the automated CI gate (`ruff`, `mypy`, `pytest`, `dbt parse`,
container build) that Epic #223/#227 put in place resolves in **1-8 minutes**
per PR. Active engineering/CI time is not the bottleneck anywhere in this
sample.

## Table 3 — In-flight remaining-execution chain (as of 2026-09-16T22:03Z)

| Story | Created | Evidence delivered | Status now | Notes |
|---|---|---|---|---|
| #279 | 09-15 04:45:05 | PR #280 merged 09-15 06:09:19 | **Closed** 09-15 06:09:20 | 1h24m total, 1s evidence&rarr;close lag. The process works correctly when nothing interrupts it. |
| #254 | 09-13 21:06:07 | Live DEV run evidence posted **09-15 06:41:54** | **Still open** | Evidence delivered ~39h ago with no closure action taken — see Finding below. |
| #255 | 09-13 21:06:09 | Live evidence + protected-workflow proof posted **09-15 06:41:55** | **Still open** | Same gap as #254; identical evidence-comment pattern to #253/#257/#259 above, but nothing closed it. |
| #256 | 09-13 21:06:11 | Not yet delivered; explicitly marked "Story status: In Progress" 09-17 02:57:00 pending a steward-review console migration | **Open, genuinely in progress** | Tier D restricted-data review; this is real governance time, not overhead (ADR 0005/0027 human review for restricted sources). |
| #270-278 (9 stories) | 09-15 04:39-04:55 | Not started | **Open, not yet started** | Normal backlog; sequential dependency on #270 (parity contract) per the epic's normative execution order. |

## Finding: a real, fixable process gap — stale "complete" comments

Comparing Table 1 and Table 3 exposes an anomaly. `#254` and `#255` received
the **exact same evidence-comment pattern**, in the **same work session**, as
`#253`/`#257`/`#259` (compare: `Story #254 complete. ...` at 2026-09-15
02:26:50 and a confirming live-run comment at 06:41:54). `#253`/`#257`/`#259`
were closed within 40 seconds of their equivalent comment. `#254` and `#255`
were not closed at all — as of this audit they have sat open for **~39 hours
past their own delivered evidence**, with no governance reason (unlike #256,
which is genuinely still in progress on a Tier D restricted-data path).

This is not a role, connection, or approval-gate problem. It is a pure
bookkeeping gap: the repo's own established convention — opening a
completion comment with the literal phrase `Story #<N> complete.` — is not
acted on by anything. Nobody reliably notices it until an unrelated later
session happens to sweep it up.

### Fix implemented (not just recommended)

- `scripts/detect_story_complete_comment.py` — a small, tested detector:
  `is_story_complete_comment(issue_number, comment_body)` matches the
  existing `Story #<N> complete.` convention (case-insensitive, optional
  trailing period, anchored to the start of the comment so mid-sentence
  mentions of other stories don't false-positive).
- `.github/workflows/flag-completed-story-comment.yml` — triggers on every
  new issue comment; if the comment matches the convention for that issue,
  it adds a `needs-closure-review` label and posts an automated ping. **It
  never closes the issue itself.** Per Epic #252's own acceptance gate ("a
  story is not marked Done solely because local tests or deployment
  succeeded; production and cutover stories require live evidence"), the
  decision to close a story is deliberately left to a human. The fix removes
  only the "nobody noticed" delay, not the review step.

### Measured

`uv run pytest tests/test_detect_story_complete_comment.py
tests/test_flag_completed_story_comment_workflow.py -q` — **13 passed**,
replaying the detector against the real comment bodies captured in this
audit:

| Real comment (truncated) | Issue | Detector result |
|---|---|---|
| "Story #254 complete. `config/sources/cdc_qtbi_xd4i.yml`..." | #254 | **match** — would have flagged within seconds instead of the ~39h silent gap |
| "Story #255 complete. `run-ingestion.yml` is the single..." | #255 | **match** |
| "Implemented and pushed the first restricted-pathogen increment in PR #287..." | #256 | **no match** (correctly — not a completion comment) |
| "Story status: In Progress. The work has advanced through protected DEV evidence capture, but it is not ready to close..." | #256 | **no match** (correctly — explicitly not done) |

The negative cases matter as much as the positive ones: the fix must not
pressure a genuinely in-progress Tier D story toward premature closure.

## Finding: role/connection-switching, as required by the story's acceptance criteria

Story #295's inventory found **22 custom Snowflake roles and 12 named `snow`
CLI connections** in use across this one pipeline's lifecycle before this
epic. None of the Epic #252 story comments audited above mention an
authentication failure, role-scope error, or connection mixup as a source of
delay — the session-cadence gap in Table 1 dominates, not credential
friction. However, the sheer number of named identities a developer must
remember ("which connection do I use for a Streamlit deploy vs. a migration
vs. a PMC audit read?") is real cognitive overhead independent of wall-clock
time, and was the direct trigger for this epic.

Stories #297 and #298 (already merged) reduced that inventory from 22 to 8
custom roles (64% reduction) by consolidating owner-rights and read-only
roles per environment, while keeping every named control in
[role-classification.md](role-classification.md) intact ("runtime never
approves," owner-rights/runtime separation, DEV/PROD independence). Story
#300 (next in this epic) reduces the remaining 12-connection surface and
fixes the `BVB26657_PAT` default-role gap this inventory found. This audit
does not duplicate that work; it confirms the connection-surface reduction is
tracked, scoped, and already partially delivered rather than still an open
question.

## Named-control preservation statement (required by this story's acceptance criteria)

No control from workspace ADR 0005, ADR 0006, or data ADR 0027 is dropped,
merged, or weakened by this story:

- **ADR 0005** ("pipeline runtime roles must never record approvals";
  Tier B automated, Tier D human review) — untouched. The flag workflow adds
  no Snowflake privilege and does not touch the approval path.
- **ADR 0006** (immutable digest promotion; protected `production`
  environment approval) — untouched. No change to promotion, deployment, or
  environment isolation.
- **ADR 0027** (tiered operating model; Tier C/D human review) — untouched.
  The fix explicitly does not auto-close, and its negative-case tests prove
  it does not fire on an in-progress Tier D story (#256).

## Scorecard: before / after

| Metric | Before | After |
|---|---|---|
| Time from story evidence delivered to issue closed (happy path, #253/#257/#258/#259/#260/#279) | &le;40s (already good) | Unchanged — not the problem |
| Time from story evidence delivered to issue closed when nothing else prompts a review (#254, #255) | Unbounded — observed ~39h and still open at audit time | Flag posted **within the GitHub Actions run latency of the comment** (seconds), not after an unrelated future session |
| Mechanism | None — relies on a human noticing a comment | `needs-closure-review` label + automated ping, human still decides |
| Custom Snowflake roles (pipeline-wide) | 22 (Story #295 inventory) | 8 (Stories #297/#298, merged) |
| Named `snow` connections | 12 (Story #295 inventory) | 12 today; reduction scoped to Story #300 |
| Named ADR 0005/0006/0027 controls dropped by this story | n/a | **0** |
