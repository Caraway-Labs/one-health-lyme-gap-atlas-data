# ADR 0033: Production restricted CDC operator envelope

Status: Accepted

## Decision

The two requestor-restricted CDC ArboNET workbook sources may enter production
only through a one-shot, protected `production` GitHub environment workflow.
The requestor builds a short-lived private OCI envelope locally from a reviewed
immutable pipeline image. The workflow verifies its digest, runs a temporary
pre-deploy job, restores the exact DigitalOcean production app specification,
and deletes the registry tag on every exit path.

The raw workbook is never committed, uploaded as a GitHub artifact, printed to
logs, exposed to Streamlit or the API, or granted to a read role. Production
procedures execute as owner and retain source-faithful rows only in restricted
RAW and STAGING relations; the runtime role receives procedure usage only.

Evidence capture and full derivation are separate operations. Capture creates a
pending steward-review candidate. A derivation must name an already approved
evidence run and requires both the protected-envelope marker and production
execution enablement. No generic Tier B/C source command may use these sources.

Before a semantic release containing restricted-source output can be published,
an owner-controlled publication attestation must record that the required final
copy was delivered to CDC. The record retains only a delivery reference and
timestamp, never email contents or workbook bytes.

## Consequences

- A human steward still approves the candidate and any source-version change.
- The CDC final-copy duty is an external human action; it is a release gate, not
  an automated email action.
- Production deployment of this migration remains protected-branch and
  digest-bound. This ADR does not authorize use of an unreviewed image or
  bypass a required GitHub environment approval.
- Existing DEV-only migrations remain checksum-locked and untouched.
