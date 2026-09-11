# Governed Pipeline Deployment and Promotion

This runbook implements workspace ADR 0006. It applies only to the governed
pipeline; the Alpha POC loader and `ONE_HEALTH_LYME_GAP_ATLAS` database are out
of scope.

## Desired flow

1. A pull request passes the required `checks` workflow.
2. Merge to `main` builds a private OCI image tagged with the commit SHA and
   records its immutable digest.
3. The DEV deployment workflow applies only unapplied, checksum-validated DEV
   migrations, runs the DEV capability preflight, and points the DEV scheduled
   job at that digest.
4. The team reviews the DEV result, including the migration ledger and bounded
   source smoke evidence.
5. A designated approver starts the production workflow with that DEV-tested
   digest. GitHub's protected `production` environment pauses execution for
   approval.
6. The workflow checks the PROD migration ledger and capabilities, applies
   missing append-only migrations, then points the PROD scheduled job at the
   exact same digest.

## Environment boundary

| Concern | DEV | PROD |
| --- | --- | --- |
| Snowflake | `ONE_HEALTH_LYME_GAP_ATLAS_DEV` | `ONE_HEALTH_LYME_GAP_ATLAS_PROD` |
| Spaces | private `...-dev` bucket | separate private `...-prod` bucket |
| App Platform | `oh-lyme-data-dev` | separate non-routable job |
| GitHub environment | `dev` | protected `production` |
| Artifact | tested OCI digest | same OCI digest |

## Rollback

Disable the affected scheduled job if it must stop immediately. Redeploy its
last approved OCI digest; do not rebuild an old commit. Do not delete retained
artifacts or rewrite migration/ingestion lineage as part of rollback.

## Current implementation status

DEV is on the approved immutable-image path: a green `main` quality run builds
and deploys a private DOCR image digest to the non-routable DEV job. The
checksum-validated migration runner has registered the current two migrations
in the DEV ledger. CI validates migration source, dbt parsing, and the
container, but it deliberately does not receive Snowflake credentials or apply
Snowflake DDL/DML.

Completed controls:

1. Required quality checks include lint, formatting, typing, tests, dbt parse,
   container build, and full-history secret scanning. The scoped
   `.gitleaks.toml` exception covers only two reviewed historical non-secret
   literals.
2. A private OCI registry and GitHub `dev` / protected `production`
   environments exist.
3. `pipeline migration-plan` and explicit
   `pipeline apply-migrations --confirm` render one source-controlled migration
   set only for the DEV or PROD governed database and record checksums in that
   target's ledger.
4. DEV App Platform now uses an image digest, not a mutable GitHub source
   reference.

### DEV legacy migration-ledger recovery

If the checksum-enforced runner encounters the documented DEV legacy set for
V028, V029, and V033, it remains fail-closed until the separately reviewed
`pipeline reconcile-legacy-dev-migrations --confirm` command runs. That
command is hard-coded to the DEV database and the observed legacy checksums;
it verifies the registration-ledger shape and appends immutable reconciliation
records. It never updates or deletes `SCHEMA_MIGRATIONS` rows, and it cannot
run against PROD. V034 then reasserts the current redacted operations-view
contract in DEV only. To roll back before V034, stop the workflow or omit the
reconciliation command; no ledger history is rewritten. To disable the
operational views after V034, revoke the Streamlit owner role's view usage as
a separately reviewed, append-only grant change while retaining audit evidence.

### PROD legacy migration-ledger recovery

The protected historical CDC rollout found two bounded PROD conditions before
V051: earlier Windows execution recorded eleven otherwise identical migration
sources with CRLF hashes, and the applied PROD V022 variant reconciles duplicate
V020 rows while the current DEV-oriented V022 source reconciles V019. PROD also
contains exactly two identical V028 ledger rows. The runner treats LF and CRLF
as equivalent only when both hashes can be derived from the same normalized SQL;
any content change still fails closed.

Before applying V051, run the separately approved
`pipeline reconcile-legacy-prod-migrations --confirm` command. It accepts only
the pinned V022 filename/checksum with one row and the pinned V028
filename/checksum with two rows, then appends PROD-scoped evidence to
`GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS`. It never updates or deletes the
original ledger. Any different filename, checksum, row count, database, or
existing reconciliation record stops the operation.

This reconciliation is an AccountAdmin-governed bootstrap and is not included
in the normal DEV deployment. Use a separately authorized session, verify its
role/database/warehouse first, run only the reconciliation, and end that scope.
V051 requires its own explicit one-time AccountAdmin authorization. V052 must
use a separate PAT restricted to `OH_LYME_PROD_GOVERNED_VIEW_OWNER`; never
switch to that role inside an AccountAdmin-restricted PAT session.

### DEV V037 paper-review procedure ownership handoff

V037 replaces an owner-rights paper-review procedure. The GitHub DEV migration
role cannot preserve existing grants while transferring ownership because
`COPY CURRENT GRANTS` requires account-level `MANAGE GRANTS`. For this
DEV-only migration, use a separately approved AccountAdmin session to transfer
`GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(ARRAY, VARCHAR, VARCHAR, VARCHAR,
VARCHAR, VARCHAR)` to `OH_LYME_DEV_MIGRATION_DEPLOYER` before the migration
workflow. After its successful ledger entry, transfer ownership back to
`OH_LYME_DEV_KG_PAPER_REVIEW_OWNER` with `COPY CURRENT GRANTS`, then verify
that `OH_LYME_DEV_STREAMLIT_OWNER` retains `USAGE`. Do not use this procedure
or its DEV roles for production promotion.

V059 is a DEV-only correction for the same procedure. Before the protected
workflow, repeat the documented temporary ownership handoff to
`OH_LYME_DEV_MIGRATION_DEPLOYER`; after its successful ledger entry, transfer
ownership back to `OH_LYME_DEV_KG_PAPER_REVIEW_OWNER` with `COPY CURRENT GRANTS`.
It replaces the ambiguous `DECISION` parameter with prefixed names while
preserving the existing signature and atomic steward-decision boundary.

### DEV V056 PMC budget-procedure owner bootstrap

V056 restores the fail-closed PMC extraction budget procedure under the dedicated
`OH_LYME_DEV_KG_LLM_BUDGET_OWNER` role. Before the protected DEV workflow,
an explicitly authorized AccountAdmin session creates that DEV-only role; grants
it `USAGE` on the DEV database and `GOVERNANCE` schema; grants only `SELECT,
INSERT` on `GOVERNANCE.LLM_BUDGET_USAGE`; grants `CREATE PROCEDURE` on
`GOVERNANCE`; and grants only migration-ledger `SELECT, INSERT`. Grant this
role to `OH_LYME_DEV_MIGRATION_DEPLOY_SVC`, then transfer ownership of
`SP_RESERVE_KG_LLM_BUDGET` to it with `COPY CURRENT GRANTS`. The protected
workflow applies V056 under that role and re-grants only procedure `USAGE` to
the DEV pipeline and API runtime roles. Do not grant either runtime role direct
access to the budget table, and do not apply this bootstrap or migration to PROD.
V057 is a follow-on DEV-only correction that uses `INSERT ... SELECT` for the
generated reservation identifier; Snowflake rejects `UUID_STRING()` directly
inside the equivalent `VALUES` clause.

### V041 governed-view owner bootstrap

V041 must run as `OH_LYME_<ENV>_GOVERNED_VIEW_OWNER`, not the default
migration deployer and not the Streamlit owner. Before applying it, an
AccountAdmin-approved bootstrap grants that role only `USAGE` on the target
database, `GOVERNANCE`, `RAW`, and `CONFORMED` schemas; `CREATE VIEW` on
`GOVERNANCE`; migration-ledger `SELECT`/`INSERT`; and `SELECT` on the exact
CDC RAW, CDC CONFORMED, and validation-ledger dependencies. Grant the role to
the environment's migration deployment service user. Do not grant it to an
app owner, steward, viewer, pipeline runtime, or a cross-environment identity.

The checksum runner selects this role only for V041. Verify the four resulting
views using the Streamlit owner role before deploying either app. A rollback
redeploys prior app source and revokes app usage if necessary; it does not
delete ingestion or provenance records.

### V042 CDC evidence-runtime grant repair

V042 grants the pipeline runtime only the governance writes used by the
evidence-only CDC onboarding command: catalog dataset/resource registration,
the versioned access profile, document/schema snapshots, and the deterministic
quality assessment. It does not grant approval, source-version, RAW, dbt, or
Streamlit privileges. Apply and verify this migration before running the
protected PROD evidence-capture workflow; otherwise the job must fail closed.

### dbt runtime key handling

The App Platform runtime stores the Snowflake key only as encrypted
`SNOWFLAKE_PRIVATE_KEY_B64`. Before invoking dbt, the pipeline decodes that
value into a mode-`0600` file inside a process `TemporaryDirectory`, passes
only that temporary path to dbt, and removes it when dbt exits. Neither the key
nor dbt's captured stdout/stderr is emitted to workflow logs.

### Controlled CDC dbt-only recovery

When a completed approved CDC RAW ingestion needs only its dbt path retried,
use the protected `Recover approved CDC dbt path in PROD` workflow rather than
the full-ingestion workflow. It promotes the active DEV-tested digest, verifies
the named PROD source version is approved and has retained RAW rows, runs dbt
through a temporary non-routable pre-deploy job, and removes that temporary
topology afterward. It must never be used to re-ingest the source. See ADR
0017 for the exact guardrails and required post-run validation.

Completed production-runtime controls:

1. Separate PROD Snowflake, Spaces, service identity, and non-routable App
   Platform job are provisioned. Its production-only secrets remain stored in
   App Platform, and `PROD_APP_ID` is configured as a GitHub production
   environment variable.
2. The production workflow fetches the existing App Platform specification
   without emitting it, confirms the intended scheduled jobs, and updates only
   their immutable image digest. This preserves provider-encrypted secrets and
   all other production job settings.

The approved live PROD operational topology contains exactly six scheduled
jobs: `catalog-discovery`, `approved-source-ingestion`,
`catalog-registration-01`, `catalog-registration-02`,
`catalog-registration-03`, and `cdc-operations-watchdog`. The promotion
workflow fails closed if a job is missing, an unexpected or temporary job is
present, or any job is not using the private `pipeline` image. Literature jobs
in the provisioning template are not part of the current live PROD topology;
an image promotion must not create them implicitly. Adding those jobs requires
a separately reviewed topology change and live provisioning evidence.

Still required before a full-production ingestion can run:

1. Run the protected `Capture PROD CDC evidence for steward review` workflow
   from `main`. It uses the existing production runtime's encrypted settings to
   create only the bounded `x5j9-wybp` evidence candidate, verifies the
   one-shot job invocation, and restores the exact prior app specification.
   It cannot approve, full-ingest, run dbt, or promote an image. See ADR 0015.
2. Review and record the immutable PROD steward decision in the PROD
   `SOURCE_APPROVAL_CONSOLE`.
3. Run the protected `Run approved governed ingestion in PROD` workflow from
   `main`. It verifies that the active PROD digest appears in DEV deployment
   history, requires a recorded metadata-check ID, runs the explicitly authorized
   full refresh once as a temporary
   pre-deploy job, and restores the exact prior app specification. See ADR
   0016.
4. Exercise a DEV rollback by redeploying a previously approved digest.

The checked-in `.do/app.prod.yaml` is the production job specification. It
runs metadata-only CDC checks monthly. An operator-authorized full refresh invokes
dbt and quality checks before atomically publishing a snapshot. It requires an active steward-approved
PROD source version and `ENABLE_PRODUCTION_EXECUTION=true`; it cannot consume
a DEV approval, create an approval, or run against the Alpha POC database.

## Streamlit approval-console promotion checklist

Apply this checklist independently in each environment. It records DEV lessons
that are mandatory for the later protected PROD promotion.

1. **Create under the owner role.** Create `SOURCE_APPROVAL_CONSOLE` while
   using `OH_LYME_<ENV>_STREAMLIT_OWNER`. In this Snowflake account, ownership
   cannot be transferred to a Streamlit after it is created, so creating it as
   `ACCOUNTADMIN` and attempting a later ownership grant fails.
2. **Use a dedicated deployment identity.** A PAT session is role-restricted
   and cannot use `USE ROLE` to switch to the Streamlit owner. Provision a
   separate `<ENV>` deploy service user with encrypted key-pair authentication,
   default role `OH_LYME_<ENV>_STREAMLIT_OWNER`, and only the owner role's
   warehouse/schema/stage privileges. Do not reuse the DEV identity or key in
   PROD.
3. **Grant procedure dependencies explicitly.** Owner-rights stored procedures
   need direct `SELECT`/`INSERT` privileges on every governance table they use;
   `USAGE` on the procedure and `SELECT` on views are insufficient. The app
   itself must continue to read governed views only and write exclusively via
   `SP_RECORD_SOURCE_REVIEW_DECISION`.
   Use `INSERT ... SELECT` for procedure writes that include a bound `VARIANT`
   payload such as decision conditions; this Snowflake account rejects that
   payload in the corresponding `INSERT ... VALUES` form.
   The owner role also needs direct `SELECT` and `INSERT` access to the
   migration ledger so it can apply a later owner-owned procedure migration.
   It needs `CREATE PROCEDURE` on `GOVERNANCE` as well; this lets it replace
   the approval procedure it already owns, without broad account privileges.
   Validate both direct `SELECT` and `INSERT` grants for every procedure target
   table; an `INSERT ... SELECT` branch can require both at execution time.
   Keep the source-version creation and immutable decision insert in one
   explicit transaction. If an older deployment produced an orphaned version,
   retire it with a source-controlled reconciliation migration; never delete
   or silently reuse it.
   When a migration uses `CREATE OR REPLACE VIEW`, re-grant every required
   direct view privilege afterwards: Snowflake drops existing grants on the
   replaced view.
4. **Verify before steward review.** Confirm the app owner, query warehouse,
   source-stage files, app usage grants, migration ledger, and a no-write
   authorization-negative call. Then run a fixture candidate through one valid
   decision before asking a steward to decide on a real source.
5. **Show actionable, safe errors.** Keep the friendly rejection banner and
   display the exact Snowflake error beneath it after redacting token, secret,
   password, authorization, and private-key values. Do not expose raw payloads
   or connection configuration.
6. **Promote source and grants together.** Include Streamlit code, its source
   stage upload, owner-role grants, procedure/table privileges, and deployment
   identity configuration in the protected promotion evidence. A successful
   worker-image deployment alone does not deploy or validate the approval app.
7. **Preflight every owner-rights view dependency.** `SELECT` on a view is not
   enough for an owner-rights Streamlit app: its owner needs direct `SELECT` on
   every table expanded by that view. For this console, that includes
   `CATALOG_DATASETS` (queue/detail) and `INGESTION_RUNS` (pipeline status), in
   addition to the procedure dependencies above. Maintain the grant migration
   with the view change, and execute a read-only `SELECT` against **each** of
   queue, detail, pipeline status, and history using the owner role before
   steward access is granted.
8. **Preflight creator privileges before view replacement.** The Streamlit
   owner needs `CREATE VIEW` on `GOVERNANCE` before a migration that creates or
   replaces its owner-owned views. Run the privilege check before deployment;
   do not discover the omission halfway through a migration. `SECURITY_ADMIN`
   may manage grants yet still lack `CREATE TABLE`; baseline-table repair is an
   AccountAdmin-controlled recovery operation, not a normal promotion step.
9. **Treat missing baseline tables as a stop condition in PROD.** A role's
   object listing can hide tables it is not authorized to inspect. Verify the
   V001 governance-table baseline using an authorized administrative preflight
   before promotion. If a required table is actually absent in PROD, stop and
   open a controlled recovery incident; do not fabricate source evidence or
   proceed with a steward decision. The DEV V017 recovery is limited to the
   CDC parent relation and deliberately preserves incomplete evidence rather
   than inventing a metadata digest.
10. **Use short-lived, single-role repair credentials only when necessary.**
    PAT sessions cannot switch roles and cannot create or revoke PATs for the
    same human user. Create a separate, role-restricted, time-limited token
    from a browser-authenticated session only for a documented repair; revoke
    it and remove its local token file/connection entry immediately afterward.
    Keep the normal deployment identity restricted to the Streamlit owner role.

The `Promote governed pipeline to PROD` workflow is present and protected by
the GitHub `production` environment. It verifies that a requested digest is the
one currently deployed in DEV. It deliberately stops until distinct PROD
Snowflake/Spaces credentials and the PROD job exist; it never creates them as a
side effect of a promotion request.
