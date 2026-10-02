# DATA374 bounded runtime verification

Baseline: merged DATA374/377 and DATA376 integration at
`f28efd9d510ea117d774846292ead8f6bb3e8603`. Historical expectations remain
unchanged from `3c81b471c802b1ad7e9361740319bd7cbeb50b4b`.
This supplements [the recipe index](data374-recipes.md), without replacing
operation contracts or granting authority.

## Reproduction

Run from a source checkout with locked pipeline/dev dependencies. Supply the
installed Codex executable path locally; never record personal paths in evidence.

```text
python scripts/verify_atlas_skill_discovery.py --codex-bin <installed-codex>
python scripts/verify_atlas_metadata_routing.py --codex-bin <installed-codex> --run-routing
python scripts/verify_atlas_readonly_recipes.py --inspect-dev
```

Discovery uses app-server `skills/list`, without agent turns, at the repository
root and nested tests directory. Codex CLI 0.159.2 discovered all four enabled
skills at both locations, with zero discovery errors. This agrees with the
documented [.agents/skills discovery scope](https://learn.chatgpt.com/docs/build-skills).
Interactive UI and assembled workspace discovery remain unverified.

The separate metadata routing probe uses a disposable repository containing only
the four public skills, read-only sandbox, no approvals, disabled apps/hooks,
and explicitly requested `gpt-6.1-sol` with low reasoning. Four positive, four
negative and four near-miss cases matched; zero tool calls were observed. This
is one observed classification run, not deterministic-agent or end-to-end
workflow proof. Raw startup/account diagnostics are captured privately in memory
and never emitted or committed. Only fixed case IDs and skill enums are retained.

## Actual DEV read scope

The fixed helper validates the existing named `ATLAS_DEV_READ` connection,
`OH_LYME_DEV_READ`, `ONE_HEALTH_LYME_GAP_ATLAS_DEV` and expected DEV warehouse
before any recipe. It uses existing PAT authentication, without browser fallback.
Only identity SELECTs, synthetic SELECT parameter binding, an anonymous scripting
block containing SELECT, and canonical county CTE SELECTs are executed. No
objects, rows, stages, grants or procedure invocations are created or changed.
Actual usernames and raw CLI responses are excluded from the report.

Observed connector 4.3.0 and engine 10.35.101 passed three checks:

| Check | Observed result | Limit |
| --- | --- | --- |
| `executemany` SELECT with JSON and timezone timestamps | PASS | Does not exercise INSERT bulk rewrite |
| Anonymous scripting SQL-expression bind | PASS | Does not prove stored-procedure binding or caller/owner rights |
| Canonical county CTE: 3 counties, 2 matches, missing 01005 UNKNOWN, source-only 01999 | PASS | Does not invoke V098 parity procedure |

Timestamp validation compares timezone-aware instants, accepting equivalent
`Z` and `+00:00` serialization while rejecting time loss or naive values.
The connector's [executemany contract](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api)
and [binding modes](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-example)
distinguish this repeated SELECT path from bulk INSERT behavior.
[Scripting variable binding](https://docs.snowflake.com/en/developer-guide/snowflake-scripting/variables)
uses `:variable` inside SQL expressions in the anonymous block.

## Capstone limits and integration interface

Historical #336 and #353 repairs remain UNKNOWN. The canonical fixture result
does not upgrade historical #365 procedure evidence. #366 retains its frozen
offline BLOCKED denied-capability result, independently of UNKNOWN observed
authority. Real bulk INSERT, stored-procedure caller/owner behavior, grant
replacement, role allow/deny and bootstrap remain UNVERIFIED. Testing them needs
an explicitly approved existing isolated DEV target and role scope; routine read
authority does not authorize writes or grants.

DATA376 packet validation is integrated in merged PR565
(`f28efd9d510ea117d774846292ead8f6bb3e8603`). DATA372 draft final interface at
`7bd6886e32b2cb279836db947804d82c91cf3c95` was audited: v1 schema, reviewed
metadata scope, partial visibility, source-kind labels, mixed-source UNKNOWN,
scope/hash integrity and default 24-hour TTL. Its final reviewed output must be
integrated before capstone acceptance. Metadata is not row lineage, absent grants
are not deny proof, and snapshots never authorize consequential readiness.
No snapshot implementation or evidence-owner files are changed here.

These helpers are opt-in laptop verification tools. No deployment, credentials,
grants, CI identity or workflow changes are required. Existing deployment remains
parent-coordinated after independent review and exact CI on refreshed main.
