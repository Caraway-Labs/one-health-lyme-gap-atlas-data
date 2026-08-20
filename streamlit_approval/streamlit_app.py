"""Snowflake-hosted approval console; deployment supplies owner-rights context."""

import streamlit as st

st.set_page_config(page_title="Source approval console")
st.title("Source approval console")
st.caption("Approvals are immutable. The pipeline cannot approve candidates.")
st.dataframe(st.connection("snowflake").query("SELECT * FROM GOVERNANCE.V_SOURCE_APPROVAL_QUEUE"))
