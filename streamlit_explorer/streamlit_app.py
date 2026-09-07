"""Read-only CDC explorer for curated CONFORMED and analytics-ready projection views."""

from __future__ import annotations

import re
from typing import Final

import streamlit as st
from snowflake.snowpark.context import get_active_session

PAGE_SIZE: Final = 250
session = get_active_session()


def _rows(statement: str, params: list[object] | None = None) -> list[dict[str, object]]:
    return [row.as_dict() for row in session.sql(statement, params=params).collect()]


def _safe_snowflake_error(error: Exception) -> str:
    return re.sub(
        r"(?i)((?:token|secret|password|private[_ -]?key|authorization)\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        str(error),
    )[:4_000]


def _source_versions() -> list[dict[str, object]]:
    return _rows(
        """SELECT * FROM GOVERNANCE.V_DATA_EXPLORER_SOURCE_VERSIONS
           ORDER BY source_version_created_at DESC"""
    )


def _records(
    view: str, source_version_id: str, year: int | None, offset: int
) -> list[dict[str, object]]:
    if view not in {"V_DATA_EXPLORER_CONFORMED_CDC", "V_DATA_EXPLORER_ANALYTICS_CDC"}:
        raise ValueError("Unsupported explorer view")
    where = "WHERE data_source_version_id = ?"
    params: list[object] = [source_version_id]
    if year is not None:
        where += " AND report_year = ?"
        params.append(year)
    params.extend([PAGE_SIZE, offset])
    return _rows(
        f"""SELECT source_record_id, data_source_version_id, ingestion_run_id, artifact_id,
                   county_fips, report_year, case_status, sex, age_category_years, frequency,
                   source_value_status, geography_semantics, source_resolution, temporal_window,
                   caveat, retrieved_at
            FROM GOVERNANCE.{view} {where}
            ORDER BY report_year DESC, county_fips, case_status, sex, age_category_years
            LIMIT ? OFFSET ?""",
        params,
    )


st.set_page_config(page_title="Governed data explorer", layout="wide")
st.title("GOVERNED_DATA_EXPLORER")
st.caption(
    "Internal read-only exploration of curated CDC/Socrata CONFORMED and analytics-ready data."
)
st.info(
    "This app never exposes RAW payloads, artifacts, request data, credentials, or write actions."
)

try:
    versions = _source_versions()
except Exception as exc:
    st.error("Governed explorer data is currently unavailable.")
    st.code(_safe_snowflake_error(exc), language="text")
    st.stop()

if not versions:
    st.info("No approved CDC source versions are available for exploration yet.")
    st.stop()

options = [str(row["DATA_SOURCE_VERSION_ID"]) for row in versions]
selected = st.sidebar.selectbox("Source version", options)
selected_summary = next(row for row in versions if str(row["DATA_SOURCE_VERSION_ID"]) == selected)
page = st.sidebar.radio("View", ("Run summary", "CONFORMED records", "Analytics-ready projection"))

if page == "Run summary":
    st.subheader("Source and run summary")
    st.dataframe([selected_summary], use_container_width=True, hide_index=True)
    st.warning(str(selected_summary["CAVEAT"]))
    st.caption(
        "Row counts are evidence of materialized governed relations, not a claim "
        "about disease risk."
    )
else:
    view = (
        "V_DATA_EXPLORER_CONFORMED_CDC"
        if page == "CONFORMED records"
        else "V_DATA_EXPLORER_ANALYTICS_CDC"
    )
    year_text = st.sidebar.text_input("Report year (optional)")
    year = int(year_text) if year_text.strip().isdigit() else None
    page_number = int(st.sidebar.number_input("Result page", min_value=1, value=1, step=1))
    records = _records(view, selected, year, (page_number - 1) * PAGE_SIZE)
    st.subheader(page)
    if page == "Analytics-ready projection":
        st.info(
            "No reviewed aggregate is defined yet. This projection preserves CONFORMED grain and "
            "provenance; it does not create a disease-risk measure or cross-era comparison."
        )
    st.caption(f"Showing up to {PAGE_SIZE} curated rows per page; no RAW payload is displayed.")
    if records:
        st.dataframe(records, use_container_width=True, hide_index=True)
        st.warning(str(records[0]["CAVEAT"]))
    else:
        st.info("No records match this source version and optional year filter.")
