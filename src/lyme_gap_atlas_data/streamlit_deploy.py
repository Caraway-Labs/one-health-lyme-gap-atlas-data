"""Deployment of the internal Snowflake Streamlit approval application."""

from __future__ import annotations

from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .migrations import DATABASE_PATTERN

APP_SOURCE_DIR = Path(__file__).resolve().parents[2] / "streamlit_approval"


def deploy_approval_console(settings: SnowflakeSettings, database: str) -> str:
    """Upload reviewed local app files and create the owner-rights app object."""
    match = DATABASE_PATTERN.fullmatch(database)
    if match is None:
        raise ValueError("Approval console may target only the governed DEV or PROD database")
    environment = match.group(1)
    owner_role = f"OH_LYME_{environment}_STREAMLIT_OWNER"
    warehouse = f"OH_LYME_{environment}_APPROVAL_XS_WH"
    stage_path = "@GOVERNANCE.STREAMLIT_SOURCE_STAGE/source_approval_console"
    with connect(settings, include_database=False) as connection, connection.cursor() as cursor:
        cursor.execute(f"USE ROLE {owner_role}")
        cursor.execute(f"USE DATABASE {database}")
        cursor.execute(f"USE WAREHOUSE {warehouse}")
        for filename in ("streamlit_app.py", "environment.yml"):
            source_file = APP_SOURCE_DIR / filename
            if not source_file.is_file():
                raise FileNotFoundError(source_file)
            cursor.execute(
                f"PUT '{source_file.resolve().as_uri()}' {stage_path} "
                "AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
            )
        cursor.execute(
            """CREATE OR REPLACE STREAMLIT GOVERNANCE.SOURCE_APPROVAL_CONSOLE
               ROOT_LOCATION = '@GOVERNANCE.STREAMLIT_SOURCE_STAGE/source_approval_console'
               MAIN_FILE = 'streamlit_app.py'
               QUERY_WAREHOUSE = """
            + warehouse
        )
        cursor.execute(
            "GRANT USAGE ON STREAMLIT GOVERNANCE.SOURCE_APPROVAL_CONSOLE "
            + f"TO ROLE OH_LYME_{environment}_DATA_STEWARD"
        )
        cursor.execute(
            "GRANT USAGE ON STREAMLIT GOVERNANCE.SOURCE_APPROVAL_CONSOLE "
            + f"TO ROLE OH_LYME_{environment}_APPROVAL_VIEWER"
        )
    return f"{database}.GOVERNANCE.SOURCE_APPROVAL_CONSOLE"
