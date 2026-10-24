# Cursor Cloud Agent dispatch for data tickets

`.github/workflows/cursor-dispatch.yml` hands a data story to a Cursor Cloud
Agent when an issue gets the `cursor:ready` label. It runs
`.github/scripts/cursor-dispatch.sh`, a port of the web repository's
dispatcher with a data-specific agent brief.

## How to dispatch

1. Make sure the issue is an open story or task (`type: story`, `Story`,
   `type: task`, or no type label). Epics and other types such as
   `type: bug` are skipped with a comment.
2. Add the `cursor:ready` label.
3. The workflow starts an agent from `main`, comments the agent ID and URL on
   the issue, and swaps `cursor:ready` for `cursor:running`.

The agent opens a ready-for-review PR whose body starts `Part of #<issue>`.
Nothing here merges, deploys, or runs DEV/PROD workflows; review and merge
stay with the owner.

## Labels

| Label | Meaning |
| --- | --- |
| `cursor:ready` | Request a dispatch now. |
| `cursor:queued` | Waiting: either 4 agents are already ACTIVE or the issue has open blocked-by dependencies. A 15-minute schedule retries queued issues, oldest first. |
| `cursor:running` | An agent was launched. Re-adding `cursor:ready` will not start a second one. |
| `cursor:failed` | Dispatch failed (for example a Cursor API error). See the issue comment and Actions run, fix the cause, remove this label and add `cursor:ready` again. |

## Capacity

The 4-agent cap counts every ACTIVE Cloud Agent visible to the
`CURSOR_API_KEY` across all repositories, not only data agents. If the web
and data repositories use keys from the same Cursor account, they share the
four slots. The `cursor-cloud-agent-dispatch` concurrency group is per
repository; it only keeps two data label events from both passing the count.

## Prerequisites

- Repository Actions secret `CURSOR_API_KEY` (a Cursor API key that can
  create Cloud Agents). Without it the workflow fails before contacting
  Cursor.
- The Cursor GitHub app must have access to this repository so the agent can
  push a branch and open the PR.
- The four `cursor:*` labels above.

## What the agent is told

The brief tells the agent to treat the issue (and its parent epic) as the
spec, follow `AGENTS.md`, branch from latest `main`, and run the same gates
as `.github/workflows/quality.yml`. It must list the commands it ran in the
PR, use no GitHub closing keywords anywhere (even negated sentences close
issues on merge), never merge, never dispatch or approve DEV/PROD workflows,
and never change Snowflake, DigitalOcean, secrets, environments or
migrations. Live DEV/PROD steps go in a "Remaining operator steps" PR section.
