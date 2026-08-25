"""Internal-only Snowflake Streamlit SOURCE_APPROVAL_CONSOLE.

This first governed release is restricted to the DEV CDC/Socrata x5j9-wybp
candidate. It makes no network calls and writes only via the controlled procedure.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import re
import uuid
from typing import Final

import streamlit as st
from snowflake.snowpark.context import get_active_session

APP_VERSION: Final = "1.0.0"
CDC_RESOURCE_KEY: Final = "cdc_lyme_x5j9_wybp"
DECISIONS: Final = {"APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED", "RETIRED", "DEFERRED"}
CONDITIONS_REQUIRED: Final = {"APPROVED_WITH_CONDITIONS", "REJECTED", "RETIRED", "DEFERRED"}
session = get_active_session()
viewer = st.user.user_name


def _rows(statement: str, params: list[object] | None = None) -> list[dict[str, object]]:
    return [row.as_dict() for row in session.sql(statement, params=params).collect()]


def _lower_keys(row: dict[str, object]) -> dict[str, object]:
    return {key.lower(): value for key, value in row.items()}


def _validate_decision(decision: str, rationale: str, conditions: list[str]) -> None:
    if decision not in DECISIONS:
        raise ValueError("Choose a supported decision")
    if not 10 <= len(rationale.strip()) <= 10_000:
        raise ValueError("Provide a rationale between 10 and 10,000 characters")
    if decision in CONDITIONS_REQUIRED and not conditions:
        raise ValueError("Provide at least one condition, required action, or deferral reason")


def _approval_prerequisites_met(detail: dict[str, object]) -> bool:
    return (
        int(detail.get("document_snapshot_count", 0)) > 0
        and int(detail.get("schema_snapshot_count", 0)) > 0
        and detail.get("profile_version") is not None
        and detail.get("assessment_status") == "PENDING_REVIEW"
        and not bool(detail.get("has_material_schema_change", False))
        and not bool(detail.get("has_material_document_change", False))
        and not bool(detail.get("has_blocking_issue", False))
    )


def _safe_snowflake_error(error: Exception) -> str:
    message = re.sub(
        r"(?i)((?:token|secret|password|private[_ -]?key|authorization)\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        str(error),
    )
    return message[:4_000]


def _queue() -> list[dict[str, object]]:
    return _rows(
        """SELECT resource_key, catalog_name, canonical_source_url, api_dataset_id, resource_type,
                  assessment_status, relevance_score, joinability_score, accessibility_score,
                  documentation_score, quality_score, overall_score, recommendation, limitations,
                  assessed_at, latest_decision, has_material_schema_change,
                  has_material_document_change, has_blocking_issue
           FROM GOVERNANCE.V_SOURCE_APPROVAL_QUEUE
           WHERE resource_key = ?
           ORDER BY has_blocking_issue DESC, overall_score DESC NULLS LAST, assessed_at ASC""",
        [CDC_RESOURCE_KEY],
    )


def _detail() -> dict[str, object] | None:
    rows = _rows(
        "SELECT * FROM GOVERNANCE.V_SOURCE_APPROVAL_DETAIL WHERE resource_key = ?",
        [CDC_RESOURCE_KEY],
    )
    return _lower_keys(rows[0]) if rows else None


def _history() -> list[dict[str, object]]:
    return _rows(
        """SELECT manual_review_decision_id, decision, rationale, conditions, reviewer_username,
                  supersedes_decision_id, data_source_version_id, app_version, correlation_id, decided_at
           FROM GOVERNANCE.V_SOURCE_REVIEW_HISTORY WHERE resource_key = ? ORDER BY decided_at DESC""",
        [CDC_RESOURCE_KEY],
    )


def _pipeline_status() -> dict[str, object] | None:
    rows = _rows(
        "SELECT * FROM GOVERNANCE.V_SOURCE_PIPELINE_STATUS WHERE resource_key = ?",
        [CDC_RESOURCE_KEY],
    )
    return _lower_keys(rows[0]) if rows else None


def _paper_queue() -> list[dict[str, object]]:
    return _rows(
        """SELECT pmid, pmcid, title, journal, publication_date, publication_types,
                  language, abstract, access_status, state, query_families, pubmed_url,
                  discovered_at, configuration_version
           FROM GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE
           ORDER BY publication_date DESC NULLS LAST, discovered_at ASC"""
    )


st.set_page_config(page_title="Source approval console", layout="wide")
st.title("SOURCE_APPROVAL_CONSOLE")
st.caption("DEV only | CDC/Socrata x5j9-wybp only | internal governed review")
st.info("This console cannot run discovery, ingestion, retries, or transformations.")
recorded_decision = st.session_state.pop("recorded_decision", None)
if recorded_decision:
    message = f"Recorded immutable {recorded_decision['decision']} decision."
    if recorded_decision.get("source_version_id"):
        message += " A governed source version is now eligible for the next pipeline step."
    st.success(message)

try:
    steward = bool(
        _rows(
            """SELECT COUNT(*) AS count FROM GOVERNANCE.V_ACTIVE_APPROVAL_STEWARDS
               WHERE username = ? AND authorization_scope IN (?, ?, ?, ?, ?)""",
            [
                viewer,
                "GLOBAL",
                CDC_RESOURCE_KEY,
                f"RESOURCE:{CDC_RESOURCE_KEY}",
                "CATALOG:CDC_SOCRATA",
                "DOMAIN:cdc.gov",
            ],
        )[0]["COUNT"]
    )
    page = st.sidebar.radio(
        "View",
        ("Paper review", "Queue", "Candidate detail", "Decision form", "Decision history"),
    )
    queue = _queue()
except Exception as exc:
    st.error("Governance data is currently unavailable. No decision was recorded.")
    st.code(_safe_snowflake_error(exc), language="text")
    st.stop()

if page == "Paper review":
    st.subheader("Literature paper review")
    st.caption(
        "Review metadata, abstract, access evidence, and query matches. "
        "Approval only admits the paper to the separate PMC Open Access check."
    )
    papers = _paper_queue()
    if not papers:
        st.success("The paper review queue is clear")
        st.caption("New PubMed discoveries appear here after normalization and deduplication.")
        st.stop()
    state_filter = st.multiselect(
        "State", sorted({str(row["STATE"]) for row in papers}), default=["awaiting_review"]
    )
    family_filter = st.multiselect(
        "Query family",
        sorted({str(family) for row in papers for family in (row.get("QUERY_FAMILIES") or [])}),
    )
    displayed = [
        row
        for row in papers
        if (not state_filter or row["STATE"] in state_filter)
        and (
            not family_filter
            or set(str(value) for value in (row.get("QUERY_FAMILIES") or [])) & set(family_filter)
        )
    ]
    selected = st.multiselect(
        "Select PMIDs for one immutable batch decision",
        [str(row["PMID"]) for row in displayed],
        format_func=lambda pmid: next(
            f"{pmid} — {row['TITLE']}" for row in displayed if str(row["PMID"]) == pmid
        ),
    )
    for row in displayed:
        with st.expander(f"PMID {row['PMID']}: {row['TITLE']}"):
            st.link_button("Open PubMed record", str(row["PUBMED_URL"]))
            st.json(
                {
                    "journal": row.get("JOURNAL"),
                    "publication_date": row.get("PUBLICATION_DATE"),
                    "publication_types": row.get("PUBLICATION_TYPES"),
                    "language": row.get("LANGUAGE"),
                    "access_status": row.get("ACCESS_STATUS"),
                    "query_families": row.get("QUERY_FAMILIES"),
                    "configuration_version": row.get("CONFIGURATION_VERSION"),
                    "abstract": row.get("ABSTRACT"),
                }
            )
    if not steward:
        st.info("You have read-only access. An active data steward must submit decisions.")
        st.stop()
    with st.form("paper-review-batch"):
        decision = st.selectbox("Batch decision", ["approved", "rejected", "deferred"])
        rationale = st.text_area("Rationale", max_chars=10_000)
        confirm = st.checkbox("I confirm this creates immutable decisions for every selected PMID.")
        submitted = st.form_submit_button("Record paper decisions")
    if submitted:
        if not selected:
            st.error("Select at least one paper.")
        elif not 10 <= len(rationale.strip()) <= 10_000:
            st.error("Provide a rationale between 10 and 10,000 characters.")
        elif not confirm:
            st.error("Confirm the immutable batch decision before submission.")
        else:
            try:
                response = _rows(
                    "CALL GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(PARSE_JSON(?), ?, ?, ?, ?, ?)",
                    [
                        json.dumps(selected),
                        decision,
                        rationale,
                        viewer,
                        APP_VERSION,
                        str(uuid.uuid4()),
                    ],
                )
                st.success(f"Recorded {decision} for {len(selected)} papers.")
                st.json(response)
            except Exception as exc:
                st.error("Snowflake rejected the batch. No partial decision was recorded.")
                st.code(_safe_snowflake_error(exc), language="text")

elif page == "Queue":
    st.subheader("Candidate queue")
    st.caption("Priority: blocking issues, readiness score, then oldest assessment.")
    if not queue:
        st.success("Review queue is clear")
        st.caption(
            "Future CDC discovery evidence will appear here when it is ready for steward review."
        )
        st.stop()
    status_filter = st.selectbox(
        "Assessment status", ["All"] + sorted({str(r["ASSESSMENT_STATUS"]) for r in queue})
    )
    displayed = (
        queue
        if status_filter == "All"
        else [r for r in queue if r["ASSESSMENT_STATUS"] == status_filter]
    )
    st.dataframe(displayed, use_container_width=True, hide_index=True)
    st.download_button(
        "Download filtered queue JSON",
        json.dumps(displayed, default=str, indent=2),
        "cdc_x5j9_wybp_approval_queue.json",
        "application/json",
    )
    st.caption(
        "Export contains review metadata only; it excludes artifacts, raw payloads, and secrets."
    )

elif page == "Candidate detail":
    st.subheader("Candidate evidence")
    detail = _detail()
    if detail is None:
        st.warning("No active CDC candidate evidence is available.")
        st.stop()
    st.warning(str(detail["cdc_guardrail"]))
    pipeline = _pipeline_status()
    if pipeline:
        if bool(pipeline.get("eligible_for_full_ingestion")):
            st.success(
                "Pipeline eligibility: eligible for scheduled full ingestion; this app cannot start it."
            )
        else:
            st.warning("Pipeline eligibility: blocked or awaiting steward action.")
        st.json(pipeline)
    st.subheader("Metadata and assessment")
    st.json(
        {
            key: detail.get(key)
            for key in (
                "catalog_name",
                "catalog_record_id",
                "canonical_source_url",
                "api_dataset_id",
                "resource_type",
                "metadata_payload",
                "metadata_sha256",
                "assessment_status",
                "relevance_score",
                "joinability_score",
                "accessibility_score",
                "documentation_score",
                "quality_score",
                "overall_score",
                "recommendation",
                "limitations",
                "assessed_at",
                "profile_version",
                "connector_name",
                "deterministic_order_clause",
                "incremental_strategy",
            )
        }
    )
    st.subheader("Documentation, terms, schema, and sample evidence")
    st.json(
        {
            key: detail.get(key)
            for key in (
                "document_snapshot_count",
                "document_evidence",
                "schema_snapshot_count",
                "schema_evidence",
                "has_material_schema_change",
                "has_material_document_change",
            )
        }
    )

elif page == "Decision form":
    st.subheader("Record a governed decision")
    if not steward:
        st.info("You have read-only viewer access. An active data steward must submit a decision.")
        st.stop()
    detail = _detail()
    if detail is None:
        st.warning("No active CDC candidate is available for decision.")
        st.stop()
    approvals_enabled = _approval_prerequisites_met(detail)
    if not approvals_enabled:
        st.warning("Approval is disabled: complete evidence or resolve material changes first.")
    with st.form("source-review"):
        available_decisions = (
            sorted(DECISIONS)
            if approvals_enabled
            else sorted(DECISIONS - {"APPROVED", "APPROVED_WITH_CONDITIONS"})
        )
        decision = st.selectbox("Decision", available_decisions)
        consequence = {
            "APPROVED": "Allows scheduled full ingestion after a governed source version is activated.",
            "APPROVED_WITH_CONDITIONS": "Allows scheduled ingestion only with the recorded conditions.",
            "REJECTED": "Blocks full ingestion and preserves the evidence and decision history.",
            "RETIRED": "Retires any active source version and blocks future full ingestion.",
            "DEFERRED": "Leaves the candidate pending and blocks full ingestion until later review.",
        }[decision]
        st.caption(consequence)
        rationale = st.text_area("Plain-language rationale", max_chars=10_000)
        condition_text = st.text_area(
            "Conditions / required actions / deferral reason (one per line)"
        )
        confirm = st.checkbox("I confirm this creates an immutable decision record.")
        submitted = st.form_submit_button("Record governed decision")
    if submitted:
        conditions = [item.strip() for item in condition_text.splitlines() if item.strip()]
        try:
            _validate_decision(decision, rationale, conditions)
            if decision in {"APPROVED", "APPROVED_WITH_CONDITIONS"} and not approvals_enabled:
                raise ValueError(
                    "Approval is blocked until all evidence prerequisites are complete"
                )
            if not confirm:
                raise ValueError("Confirm the immutable decision before submission")
            response = _rows(
                "CALL GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(?, ?, ?, PARSE_JSON(?), ?, ?, ?)",
                [
                    CDC_RESOURCE_KEY,
                    decision,
                    rationale,
                    json.dumps(conditions),
                    viewer,
                    APP_VERSION,
                    str(uuid.uuid4()),
                ],
            )
            payload = json.loads(str(next(iter(response[0].values()))))
            st.session_state["recorded_decision"] = {
                "decision": decision,
                "source_version_id": payload.get("source_version_id"),
            }
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(
                "Snowflake rejected the decision. Review the evidence prerequisites and try again."
            )
            st.code(_safe_snowflake_error(exc), language="text")

else:
    st.subheader("Decision history")
    history = _history()
    if not history:
        st.info("No immutable review decisions have been recorded for this candidate.")
    else:
        st.dataframe(history, use_container_width=True, hide_index=True)
        st.download_button(
            "Download decision history JSON",
            json.dumps(history, default=str, indent=2),
            "cdc_x5j9_wybp_review_history.json",
            "application/json",
        )
