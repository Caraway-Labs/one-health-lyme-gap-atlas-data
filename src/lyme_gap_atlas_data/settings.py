"""Settings and environment invariants for the governed pipeline."""

from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    """Non-secret configuration for the isolated governed environment."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    topx_env: str = "dev"
    enable_production_execution: bool = False
    snowflake_database: str = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_role: str = "OH_LYME_DEV_PIPELINE_RUNTIME"
    snowflake_warehouse: str = "OH_LYME_DEV_INGEST_XS_WH"
    snowflake_private_key_path: Path | None = None
    snowflake_private_key_b64: SecretStr | None = None
    snowflake_private_key_passphrase: SecretStr | None = None
    data_gov_api_key: SecretStr | None = None
    socrata_app_token: SecretStr | None = None
    spaces_region: str = "sfo3"
    spaces_endpoint: str = ""
    spaces_bucket: str = "one-health-lyme-gap-atlas-data-dev"
    spaces_prefix: str = "dev"
    spaces_access_key_id: SecretStr | None = None
    spaces_secret_access_key: SecretStr | None = None
    catalog_search_terms_path: Path = Path("catalog-search-terms.json")
    discovery_max_runtime_seconds: int = 1500
    ncbi_api_key: SecretStr | None = None
    ncbi_email: str = ""
    papers_require_human_review: bool = True
    neo4j_uri: str = ""
    neo4j_runtime_user: str = "graph_runtime"
    neo4j_runtime_password: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_environment(self) -> "PipelineSettings":
        expected = f"ONE_HEALTH_LYME_GAP_ATLAS_{self.topx_env.upper()}"
        if self.snowflake_database != expected:
            raise ValueError(f"SNOWFLAKE_DATABASE must be {expected} for TOPX_ENV={self.topx_env}")
        if self.topx_env not in {"dev", "prod"}:
            raise ValueError("TOPX_ENV must be dev or prod")
        if self.topx_env == "prod" and not self.enable_production_execution:
            raise ValueError("Production execution requires ENABLE_PRODUCTION_EXECUTION=true")
        if self.snowflake_database == "ONE_HEALTH_LYME_GAP_ATLAS":
            raise ValueError("The Alpha POC database is not a pipeline target")
        if not 1 <= self.discovery_max_runtime_seconds <= 1740:
            raise ValueError("DISCOVERY_MAX_RUNTIME_SECONDS must be between 1 and 1740")
        return self
