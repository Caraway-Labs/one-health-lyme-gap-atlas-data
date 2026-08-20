"""Non-mutating configuration and bounded connectivity verification."""

from __future__ import annotations

from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .discovery import fetch_json, initial_requests, load_search_configuration
from .settings import PipelineSettings


def _present(value: object | None) -> bool:
    return value is not None and bool(str(value))


def _required_settings(settings: PipelineSettings) -> list[str]:
    required = {
        "SNOWFLAKE_ACCOUNT": settings.snowflake_account,
        "SNOWFLAKE_USER": settings.snowflake_user,
        "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE": settings.snowflake_private_key_passphrase,
        "DATA_GOV_API_KEY": settings.data_gov_api_key,
        "SPACES_ENDPOINT": settings.spaces_endpoint,
        "SPACES_ACCESS_KEY_ID": settings.spaces_access_key_id,
        "SPACES_SECRET_ACCESS_KEY": settings.spaces_secret_access_key,
    }
    if settings.snowflake_private_key_path is None and settings.snowflake_private_key_b64 is None:
        required["SNOWFLAKE_PRIVATE_KEY_PATH or SNOWFLAKE_PRIVATE_KEY_B64"] = None
    return [name for name, value in required.items() if not _present(value)]


def run_preflight() -> dict[str, Any]:
    """Run safe, bounded checks and return statuses without secret material."""
    settings = PipelineSettings()
    missing = _required_settings(settings)
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")
    assert settings.spaces_access_key_id is not None
    assert settings.spaces_secret_access_key is not None
    assert settings.data_gov_api_key is not None

    results: dict[str, Any] = {
        "environment": settings.topx_env,
        "database": settings.snowflake_database,
        "configuration": "ok",
    }
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.spaces_endpoint,
        aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        region_name=settings.spaces_region,
        config=Config(signature_version="s3v4"),
    )
    try:
        s3.head_bucket(Bucket=settings.spaces_bucket)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("Private Spaces bucket check failed") from exc
    results["spaces"] = {"bucket": settings.spaces_bucket, "access": "ok"}

    config, checksum = load_search_configuration(settings.catalog_search_terms_path)
    requests = initial_requests(config)
    seen_catalogs: set[str] = set()
    for request in requests:
        if request.catalog_id in seen_catalogs:
            continue
        headers = dict(request.headers)
        if request.catalog_id == "DATA_GOV":
            headers["X-Api-Key"] = settings.data_gov_api_key.get_secret_value()
        elif settings.socrata_app_token is not None:
            headers["X-App-Token"] = settings.socrata_app_token.get_secret_value()
        fetch_json(type(request)(request.catalog_id, request.term, request.url, headers))
        seen_catalogs.add(request.catalog_id)
    results["catalogs"] = {"checksum": checksum, "capabilities": sorted(seen_catalogs)}

    with connect(SnowflakeSettings()) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE()"
            )
            identity = cursor.fetchone()
            assert identity is not None
            user, role, warehouse, database = identity
        finally:
            cursor.close()
    if database != settings.snowflake_database:
        raise RuntimeError("Pipeline connection did not select the configured DEV database")
    results["snowflake"] = {
        "user": user,
        "role": role,
        "warehouse": warehouse,
        "database": database,
        "access": "ok",
    }
    return results
