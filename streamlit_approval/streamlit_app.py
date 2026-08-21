"""Internal-only Snowflake Streamlit source-approval console.

This application deliberately has no network client or secrets. Snowflake
owner's-rights execution supplies governed views; the actual viewer identity is
always supplied by st.user.user_name to the controlled procedure.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import re
import uuid

import streamlit as st
from snowflake.snowpark.context import get_active_session

APP_VERSION = "0.1.0"
DECISIONS = {"APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED", "RETIRED", "DEFERRED"}
CONDITIONS_REQUIRED = {"APPROVED_WITH_CONDITIONS", "REJECTED", "RETIRED", "DEFERRED"}
session = get_active_session()
viewer = st.user.user_name


def _rows(statement: str, params: list[object] | None = None) -> list[dict[str, object]]:
    return [row.as_dict() for row in session.sql(statement, params=params).collect()]


def _validate_decision(decision: str, rationale: str, conditions: list[str]) -> None:
    if decision not in DECISIONS:
        raise ValueError("Choose a supported decision")
    if not 10 <= len(rationale.strip()) <= 10_000:
        raise ValueError("Provide a rationale between 10 and 10,000 characters")
    if decision in CONDITIONS_REQUIRED and not conditions:
        raise ValueError("Provide at least one condition, action, or deferral reason")


def _approval_prerequisites_met(detail: dict[str, object]) -> bool:
    return (
        int(detail.get("document_snapshot_count", 0)) > 0
        and int(detail.get("schema_snapshot_count", 0)) > 0
        and detail.get("profile_version") is not None
        and detail.get("assessment_status") == "PENDING_REVIEW"
        and not bool(detail.get("has_material_schema_change", False))
    )


def _safe_snowflake_error(error: Exception) -> str:
    """Show the Snowflake error requested by reviewers without exposing secrets."""
    message = str(error)
    message = re.sub(
        r"(?i)((?:token|secret|password|private[_ -]?key|authorization)\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        message,
    )
    return message[:4_000]


st.set_page_config(page_title="Source approval console", layout="wide")
st.title("Source approval console")
st.caption("Internal governed review only. This app cannot start discovery or ingestion.")

steward = bool(
    _rows(
        "SELECT COUNT(*) AS COUNT FROM GOVERNANCE.V_ACTIVE_APPROVAL_STEWARDS WHERE username = ?",
        [viewer],
    )[0]["COUNT"]
)
queue = _rows(
    """SELECT resource_key, catalog_name, canonical_source_url, assessment_status, overall_score,
              recommendation, latest_decision, has_material_schema_change
       FROM GOVERNANCE.V_SOURCE_APPROVAL_QUEUE
       ORDER BY has_material_schema_change DESC, overall_score DESC NULLS LAST, assessed_at ASC
       LIMIT 200"""
)
if not queue:
    st.info("No source candidates are awaiting review.")
    st.stop()

st.dataframe(queue, use_container_width=True, hide_index=True)
resource_key = st.selectbox("Candidate", [str(row["RESOURCE_KEY"]) for row in queue])
detail = _rows(
    "SELECT * FROM GOVERNANCE.V_SOURCE_APPROVAL_DETAIL WHERE resource_key = ?", [resource_key]
)[0]
st.subheader("Evidence summary")
st.json({key.lower(): value for key, value in detail.items() if key != "RESOURCE_PAYLOAD"})
st.warning(
    "CDC Lyme x5j9-wybp is county-of-residence surveillance data for the 2022-current era. "
    "Do not compare it across CDC reporting eras without reviewed methodology; never join "
    "non-geographic line-listed CDC datasets to county facts."
)

history = _rows(
    "SELECT * FROM GOVERNANCE.V_SOURCE_REVIEW_HISTORY WHERE resource_key = ? ORDER BY decided_at DESC",
    [resource_key],
)
st.subheader("Decision history")
st.dataframe(history, use_container_width=True, hide_index=True)

if not steward:
    st.info("You have viewer access. An active data steward must submit decisions.")
    st.stop()

with st.form("source-review"):
    decision = st.selectbox("Decision", sorted(DECISIONS))
    rationale = st.text_area("Rationale", max_chars=10_000)
    condition_text = st.text_area("Conditions / required actions (one per line)")
    confirm = st.checkbox("I understand that this creates an immutable review record.")
    submitted = st.form_submit_button("Record governed decision")

if submitted:
    conditions = [item.strip() for item in condition_text.splitlines() if item.strip()]
    try:
        _validate_decision(decision, rationale, conditions)
        if decision in {"APPROVED", "APPROVED_WITH_CONDITIONS"} and not _approval_prerequisites_met(
            {key.lower(): value for key, value in detail.items()}
        ):
            raise ValueError("Approval is blocked until all evidence prerequisites are complete")
        if not confirm:
            raise ValueError("Confirm the immutable decision before submission")
        response = _rows(
            """CALL GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(
                   ?, ?, ?, PARSE_JSON(?), ?, ?, ?)""",
            [
                resource_key,
                decision,
                rationale,
                json.dumps(conditions),
                viewer,
                APP_VERSION,
                str(uuid.uuid4()),
            ],
        )
        st.success(f"Decision recorded: {next(iter(response[0].values()))}")
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(
            "Snowflake rejected the decision. Review the evidence prerequisites and try again."
        )
        st.code(_safe_snowflake_error(exc), language="text")
