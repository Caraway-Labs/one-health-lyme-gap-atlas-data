# DATA376: source-backed offline reproduction and remaining boundaries

Audited 2026-10-02 at data main
`50809e2c56450863a7e680716ab4a482b427aa7a`, after the independently reviewed
failure-packet v1 merge. This follow-up owns this document,
`tests/test_failure_reproductions.py`, its new fixture directory, and narrow
historical packet reference updates. DATA374/377 retain their entry-point and
capstone files. The merged validator/schema and pipeline implementation are
unchanged.

## Historical repair chain, not an invented execution mapping

| Case | Authoritative repair source | Feasible offline evidence | Remaining proof |
|---|---|---|---|
| PR336 | Before: `5f880f3497bc8454383e5234e65e356cca21ebd5`; first repair: `71314065f0cee0203e5acf60135b0b42b67de2e7`; subsequent PR337: `650371245d938dc426f787c76cae5521abac7857` | Real locked connector reproduces the original INSERT SELECT `executemany` rewrite failure; current bounded `execute` calls pass real local pyformat conversion | Historical driver/version and workload/artifact mapping UNKNOWN; Snowflake execution, persistence and release-level repair UNKNOWN |
| PR353 | V091 in `1f63e3937e9b2aa85dda435beade9d1630ff5002`, followed by V092/PR354 in `a663be7613a124df1d3931b6dba3dbaf6f07d542` | Existing tests inspect SELECT form and the later explicit `:CONDITIONS` binding | SQL Scripting VARIANT behavior, caller rights and evidence/steward gates require Snowflake execution; UNKNOWN offline |
| PR365 | V098 in `93aac100c0e191837182d7d09396aae8f76cd790` | Existing Python consumer tests execute canonical-only membership and missing coverage as Unknown | V098's actual canonical-count query, owner-rights procedure and live classification ledger remain UNKNOWN |
| PR366 | V099 in `34c561ddc9656dd66b3ed0242d2de870fcec69bc` | Existing tests inspect the migration plan and least-privilege grant statements | Intended executor's real INSERT/UPDATE rights versus grant authority remain UNKNOWN; a fake permission model would not prove them |

The original PR336 description identifies DEV run `35273891419` and its county
`executemany` rewrite boundary. [PR337](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/337)
records the follow-on DEV run `35274411282`: the first repair reached Snowflake,
which rejected PARSE_JSON directly inside VALUES. Thus a passing local driver
rewrite for the first repair cannot be called complete repair. The subsequent
repair moves PARSE_JSON to the outer SELECT and avoids `executemany` rewriting.
The tests exercise the current equivalent production functions; they do not
replay a live release or claim the server accepted them.

[PR354](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/354)
and V092 document a second correction after PR353: binding `:CONDITIONS`
explicitly rather than resolving CONDITIONS as a column. Static evidence for
V091 alone therefore cannot demonstrate the final procedure repair.

These hashes identify reviewed source versions only. They are not the historical
checkout SHA, workflow head, image identity, or applied migration receipt.
No such mapping is inferred from a PR head or merge.

## Executable offline reproduction v1

Fixture: `tests/fixtures/failure_reproductions/semantic-batch-binding-v1.json`,
`fixture_schema: atlas-failure-reproduction/v1`.

The fixture contains public source SQL templates, not exception messages, logs,
bound SQL parameters, private workbooks or source rows. A test extracts literal
templates with AST from the exact pinned Git objects and compares them to the
fixture. It never imports or executes the historical module. CI's existing full
history checkout supplies those objects; missing history fails explicitly.

The driver facade uses the installed SnowflakeCursor `executemany` method,
SnowflakeConnection local parameter processing, and SnowflakeConverter. Only
the server `execute` boundary is replaced. The test connection has no transport,
no settings/credentials, and no telemetry. Socket connections, live connection
construction, and the pipeline `connect` function are denied and counted; any
attempt fails the suite even if a library tries to suppress the error.

Both county and observation templates are covered. Synthetic rows exercise
two batch boundaries (50+1 counties, 500+1 observations), parameter order,
the observation release-ID replacement, width rejection before execution,
and conversion by the actual locked client. Prepared fixture SQL stays in test
memory; it is never written into a packet, receipt or log. Caught errors are
checked by a bounded numeric category without printing their text.

```powershell
uv sync --extra dev --extra pipeline --locked
uv run pytest tests/test_failure_reproductions.py -q
uv run pytest tests/test_semantic_release.py::test_pathogen_source_scope_superset_is_not_allocated_to_canonical_counties tests/test_semantic_release.py::test_pathogen_parity_classification_preserves_unknown_not_no_records -q
```

This is behavioral client-binding proof, not engine, privilege, deployment,
or transaction-persistence proof. The locked driver version must be retained
with CI evidence; the historical driver version stays UNKNOWN. The canonical
consumer commands reuse existing approved semantics, not a translated SQL
procedure or a new scientific interpretation.

## Packet evidence updates and DATA374/377 contract

Packet schema stays version `1`; no added fields or relaxed privacy rules.
The reproduction reference for PR336 may point to the follow-up PR containing
these executable tests. Its regression may point to a passing CI run with kind
BEHAVIORAL for the client boundary. The historical repair state remains UNKNOWN:
that local proof cannot close the follow-on Snowflake engine/persistence gap.
PR353's repair-source reference adds PR354, preserving UNKNOWN runtime proof.
PR365 consumer proof stays separate from V098 procedure verification.

DATA374/377 can invoke the new test module and fixture directly and reuse
`failure_evidence.validate_packet` unchanged. Do not convert a consumer-only or
client-only PASS into a live historical repair PASS. The original four-case
capstone corpus and its expected readiness outcomes remain owned by DATA377.
Parent coordinates any corpus/reference update, independent review and merge.

## Is an opt-in runtime hook required?

The issue does not require automatic production activation or a new backend.
Its outcome, "a failed change produces" a packet, and collection-failure
acceptance criterion need an actual opted-in failure boundary to demonstrate
operational integration. The merged utility and offline tests alone do not
establish that integration. Keep this gap explicit; the source-backed tests
here do not activate a hook.

Minimal implementation plan, using the existing semantic-release CLI entry:

1. Add a disabled-by-default, per-invocation adapter over `collect_failure` at
   `semantic_release_build_command`, outside `build_semantic_release`'s existing
   transaction/rollback handler. Avoid a global all-command hook and preserve
   existing command arguments/results when not enabled.
2. Accept separately reviewed, strict v1 metadata and an explicitly configured
   bounded private packet sink. Do not scrape raw logs, CLI arguments, manifest
   content, environment dumps, exception messages or parameters. Do not start a
   new role/metadata query solely to collect evidence. Existing observed role
   and execution identities may be supplied; absent facts stay UNKNOWN. The
   GitHub workflow head must not substitute for actual checkout/artifact identity.
3. On the original Exception, collect once and then bare-raise it. Preserve
   the builder's rollback and never commit, retry, approve, mutate pipeline data,
   change grants or attempt credential fallback. Collection failure emits only
   a constant status, separately from the pipeline outcome. Do not catch normal
   successful exits as failures or infer SOFTWARE_DEFECT from a generic error.
4. Bound the configured sink to one capped metadata packet, with no network or
   extra credentials; maintain per-attempt files without overwriting prior
   evidence. A sink's bounded completion must be demonstrated, not assumed from
   an arbitrary callback. Publication remains separately reviewed and contains
   only the packet; no directory-wide/raw-log artifact upload.

Required integration tests before counting the hook as implemented:

- Disabled and successful invocations perform no collection and preserve outputs.
- A real builder invocation with injected local connection/cursor fails at a
  write boundary, performs rollback once, never commits, and re-raises the same
  exception/traceback after collection. All live connections remain denied.
- Invalid/hostile metadata, missing workload/role/query evidence, sink failure,
  write collision and byte-limit rejection preserve the original failure.
- An exception whose string/property rendering raises is never rendered;
  no SQL parameters, manifest values or personal paths reach packet/log output.
- Independently inspect behavioral evidence and safe metadata before enabling
  any existing governed job. Activation is not implied by these tests or this
  plan, and no extra production deployment is needed for the offline artifacts.

No owner decision, new grant or credential is needed for the completed offline
work. Remaining engineering is this narrowly scoped adapter and its tests.
Actual engine/procedure/role-boundary proof is separate: it needs an approved
bounded fixture scope using existing appropriate DEV identities, not replay of
destructive or restricted historical PROD operations. No live fixture is run by
this follow-up, and no missing evidence is converted into a pass.
