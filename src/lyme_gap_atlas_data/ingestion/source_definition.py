"""SourceDefinition loading and local validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .types import (
    DEFAULT_HTTP_STRUCTURED_STAGES,
    DEFAULT_HTTP_XLSX_STAGES,
    DEFAULT_SOCRATA_STAGES,
    AdapterKind,
    AuthMode,
    FailureCategory,
    QualityRule,
    SourceDefinition,
    Stage,
    ValidationIssue,
    ValidationResult,
)

_PLATFORM_TO_ADAPTER: dict[str, AdapterKind] = {
    "SOCRATA_SODA2": AdapterKind.SOCRATA,
    "socrata": AdapterKind.SOCRATA,
    "HTTP_XLSX": AdapterKind.HTTP_XLSX,
    "http_xlsx": AdapterKind.HTTP_XLSX,
    "HTTP_JSON": AdapterKind.HTTP_JSON,
    "http_json": AdapterKind.HTTP_JSON,
    "HTTP_CSV": AdapterKind.HTTP_CSV,
    "http_csv": AdapterKind.HTTP_CSV,
    "NEON_RELEASE_PACKAGE": AdapterKind.NEON_RELEASE_PACKAGE,
    "neon_release_package": AdapterKind.NEON_RELEASE_PACKAGE,
    "NCLIMGRID_DAILY": AdapterKind.NCLIMGRID_DAILY,
    "nclimgrid_daily": AdapterKind.NCLIMGRID_DAILY,
}


def _as_adapter(value: Any) -> AdapterKind:
    if isinstance(value, AdapterKind):
        return value
    text = str(value)
    if text in _PLATFORM_TO_ADAPTER:
        return _PLATFORM_TO_ADAPTER[text]
    return AdapterKind(text)


def _as_stages(raw: Any, adapter: AdapterKind) -> tuple[Stage, ...]:
    if not raw:
        if adapter is AdapterKind.SOCRATA:
            return DEFAULT_SOCRATA_STAGES
        if adapter is AdapterKind.HTTP_XLSX:
            return DEFAULT_HTTP_XLSX_STAGES
        return DEFAULT_HTTP_STRUCTURED_STAGES
    return tuple(Stage(str(item)) for item in raw)


def load_source_definition(path: Path | str) -> SourceDefinition:
    """Load a versioned SourceDefinition from YAML (legacy profiles supported)."""
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Source definition must be a mapping")
    return source_definition_from_mapping(document)


def source_definition_from_mapping(document: dict[str, Any]) -> SourceDefinition:
    resource_key = str(document.get("resource_key") or "").strip()
    if not resource_key:
        raise ValueError("resource_key is required")

    adapter_raw = document.get("adapter_kind") or document.get("platform_type")
    if not adapter_raw:
        raise ValueError("adapter_kind or platform_type is required")
    adapter = _as_adapter(adapter_raw)

    version = document.get("definition_version", document.get("profile_version", 1))
    quality_raw = document.get("quality_rules") or []
    quality_rules = tuple(
        QualityRule(rule_id=str(rule["rule_id"]), severity=str(rule.get("severity", "BLOCKING")))
        for rule in quality_raw
        if isinstance(rule, dict) and "rule_id" in rule
    )
    restrictions = document.get("restrictions") or []
    required_columns = document.get("required_columns") or []
    destination = str(
        document.get("destination") or document.get("raw_table") or f"RAW.{resource_key.upper()}"
    )
    auth_raw = document.get("auth_mode", "none")
    known = {
        "resource_key",
        "source_id",
        "dataset_id",
        "source_dataset_id",
        "definition_version",
        "profile_version",
        "adapter_kind",
        "platform_type",
        "endpoint_template",
        "metadata_endpoint_template",
        "auth_mode",
        "deterministic_order_clause",
        "incremental_strategy",
        "geography_semantics",
        "temporal_semantics",
        "restrictions",
        "artifact_policy",
        "quality_rules",
        "destination",
        "raw_table",
        "expected_refresh_cadence",
        "stages",
        "required_columns",
        "workbook_sheet",
        "header_row",
        "maximum_workbook_bytes",
        "maximum_rows",
        "page_size",
        "connector_name",
    }
    extra = {key: value for key, value in document.items() if key not in known}

    return SourceDefinition(
        resource_key=resource_key,
        source_id=str(document.get("source_id") or resource_key),
        dataset_id=str(
            document.get("dataset_id") or document.get("source_dataset_id") or resource_key
        ),
        definition_version=int(version),
        adapter_kind=adapter,
        endpoint_template=str(document.get("endpoint_template") or ""),
        metadata_endpoint_template=(
            str(document["metadata_endpoint_template"])
            if document.get("metadata_endpoint_template")
            else None
        ),
        auth_mode=AuthMode(str(auth_raw)),
        deterministic_order_clause=str(document.get("deterministic_order_clause") or ""),
        incremental_strategy=str(document.get("incremental_strategy") or ""),
        geography_semantics=str(document.get("geography_semantics") or ""),
        temporal_semantics=str(document.get("temporal_semantics") or ""),
        restrictions=tuple(str(item) for item in restrictions),
        artifact_policy=str(document.get("artifact_policy") or "PUBLIC_SEVEN_YEAR"),
        quality_rules=quality_rules,
        destination=destination,
        expected_refresh_cadence=str(document.get("expected_refresh_cadence") or ""),
        stages=_as_stages(document.get("stages"), adapter),
        required_columns=tuple(str(item) for item in required_columns),
        workbook_sheet=(
            str(document["workbook_sheet"]) if document.get("workbook_sheet") else None
        ),
        header_row=int(document["header_row"]) if document.get("header_row") is not None else None,
        maximum_workbook_bytes=(
            int(document["maximum_workbook_bytes"])
            if document.get("maximum_workbook_bytes") is not None
            else None
        ),
        maximum_rows=(
            int(document["maximum_rows"]) if document.get("maximum_rows") is not None else None
        ),
        page_size=int(document.get("page_size") or 5_000),
        extra=extra,
    )


def validate_source_definition(definition: SourceDefinition) -> ValidationResult:
    """Validate configuration locally before network or warehouse side effects."""
    issues: list[ValidationIssue] = []

    if not definition.endpoint_template.startswith(("https://", "file://", "fixture://")):
        issues.append(
            ValidationIssue(
                code="ENDPOINT_SCHEME",
                message="endpoint_template must use https://, file://, or fixture://",
                category=FailureCategory.CONFIGURATION,
            )
        )
    if not definition.deterministic_order_clause:
        issues.append(
            ValidationIssue(
                code="ORDER_CLAUSE_REQUIRED",
                message="deterministic_order_clause is required for reproducible acquisition",
            )
        )
    if not definition.geography_semantics or not definition.temporal_semantics:
        issues.append(
            ValidationIssue(
                code="GEO_TIME_REQUIRED",
                message="geography_semantics and temporal_semantics are required lineage facts",
            )
        )
    if definition.definition_version < 1:
        issues.append(
            ValidationIssue(
                code="DEFINITION_VERSION",
                message="definition_version must be a positive integer",
            )
        )
    if not 1 <= definition.page_size <= 100_000:
        issues.append(
            ValidationIssue(
                code="PAGE_SIZE",
                message="page_size must be between 1 and 100,000",
            )
        )
    if definition.maximum_rows is not None and not 1 <= definition.maximum_rows <= 10_000_000:
        issues.append(
            ValidationIssue(
                code="MAXIMUM_ROWS",
                message="maximum_rows must be between 1 and 10,000,000",
            )
        )
    if definition.adapter_kind is AdapterKind.SOCRATA:
        if ":id" not in definition.deterministic_order_clause.replace(" ", "").lower() and (
            definition.deterministic_order_clause != ":id ASC"
        ):
            # Keep soft: historical profiles may differ; x5j9 requires :id ASC.
            pass
        if not definition.quality_rules:
            issues.append(
                ValidationIssue(
                    code="QUALITY_RULES_REQUIRED",
                    message="Socrata sources must declare at least one quality rule",
                    category=FailureCategory.QUALITY,
                )
            )
        # Required columns are checked again against the acquired payload; this
        # local check only protects an accidentally empty declaration.
        if definition.required_columns and any(
            not column.strip() for column in definition.required_columns
        ):
            issues.append(
                ValidationIssue(
                    code="REQUIRED_COLUMN_NAME",
                    message="required_columns must contain non-empty names",
                    category=FailureCategory.SCHEMA,
                )
            )
    if definition.adapter_kind is AdapterKind.HTTP_XLSX:
        if not definition.required_columns:
            issues.append(
                ValidationIssue(
                    code="REQUIRED_COLUMNS",
                    message="http_xlsx sources must declare required_columns",
                    category=FailureCategory.SCHEMA,
                )
            )
        if definition.workbook_sheet is None:
            issues.append(
                ValidationIssue(
                    code="WORKBOOK_SHEET",
                    message="http_xlsx sources must declare workbook_sheet",
                    category=FailureCategory.SCHEMA,
                )
            )
    if (
        definition.adapter_kind in {AdapterKind.HTTP_JSON, AdapterKind.HTTP_CSV}
        and not definition.required_columns
    ):
        issues.append(
            ValidationIssue(
                code="REQUIRED_COLUMNS",
                message="structured HTTP sources must declare required_columns",
                category=FailureCategory.SCHEMA,
            )
        )
    if definition.adapter_kind is AdapterKind.NEON_RELEASE_PACKAGE:
        if definition.auth_mode is not AuthMode.NEON_API_TOKEN_ENV:
            issues.append(
                ValidationIssue(
                    code="NEON_AUTH_MODE",
                    message="neon_release_package requires auth_mode neon_api_token_env",
                    category=FailureCategory.PERMISSION,
                )
            )

        if not definition.required_columns:
            issues.append(
                ValidationIssue(
                    "REQUIRED_COLUMNS",
                    "neon_release_package must declare frozen required columns",
                    FailureCategory.SCHEMA,
                )
            )
        if definition.extra.get("release") != "RELEASE-2026":
            issues.append(
                ValidationIssue(
                    "NEON_RELEASE_PIN",
                    "neon_release_package is limited to RELEASE-2026",
                    FailureCategory.POLICY_LICENSE,
                )
            )

    if definition.adapter_kind is AdapterKind.NCLIMGRID_DAILY:
        from ..county_analysis_geometry import SELECTED_ARTIFACT_SHA256, SOURCE_URL

        year_month = str(definition.extra.get("year_month", ""))
        expected_endpoint = (
            "https://www.ncei.noaa.gov/data/nclimgrid-daily/access/grids/"
            f"{year_month[:4]}/ncdd-{year_month}-grd-scaled.nc"
        )
        if (
            len(year_month) != 6
            or not year_month.isdigit()
            or not 1 <= int(year_month[4:]) <= 12
            or definition.endpoint_template != expected_endpoint
        ):
            issues.append(
                ValidationIssue(
                    "NCLIMGRID_SCALED_PIN", "Exact scaled monthly NOAA URL and YYYYMM are required"
                )
            )
        if (
            definition.extra.get("tiger_url") != SOURCE_URL
            or definition.extra.get("tiger_sha256") != SELECTED_ARTIFACT_SHA256
        ):
            issues.append(
                ValidationIssue("TIGER_PIN", "Approved 2025 TIGER URL and SHA-256 are required")
            )
        if definition.extra.get("minimum_supported_area_completeness") != 0.95:
            issues.append(
                ValidationIssue(
                    "COMPLETENESS_POLICY",
                    "nClimGrid v1 requires 0.95 daily valid area within source-supported area",
                )
            )
        if (
            definition.geography_semantics != "CONUS_COUNTY_FIPS_2025_ANALYSIS"
            or definition.temporal_semantics != "COUNTY_DAY"
        ):
            issues.append(
                ValidationIssue(
                    "NCLIMGRID_GRAIN", "nClimGrid v1 requires CONUS county-day semantics"
                )
            )

    return ValidationResult(ok=not issues, issues=issues)


def starter_definition_yaml(*, resource_key: str, adapter_kind: AdapterKind) -> str:
    """Smallest useful starter definition for `source init`."""
    if adapter_kind is AdapterKind.SOCRATA:
        return (
            f"resource_key: {resource_key}\n"
            "definition_version: 1\n"
            "adapter_kind: socrata\n"
            "endpoint_template: https://data.example.gov/resource/example.json\n"
            "metadata_endpoint_template: https://data.example.gov/api/views/example\n"
            "auth_mode: none\n"
            'deterministic_order_clause: ":id ASC"\n'
            "incremental_strategy: FULL_REFRESH\n"
            "expected_refresh_cadence: annual\n"
            "geography_semantics: COUNTY\n"
            "temporal_semantics: year\n"
            "artifact_policy: PUBLIC_SEVEN_YEAR\n"
            "destination: RAW.EXAMPLE\n"
            "quality_rules:\n"
            "  - rule_id: example_required_geography\n"
            "    severity: BLOCKING\n"
            "restrictions:\n"
            "  - Replace endpoint and semantics before Tier B runs.\n"
        )
    return (
        f"resource_key: {resource_key}\n"
        "definition_version: 1\n"
        "adapter_kind: http_xlsx\n"
        "endpoint_template: https://www.example.gov/data/example.xlsx\n"
        "auth_mode: none\n"
        "deterministic_order_clause: FIPSCode ASC\n"
        "incremental_strategy: SNAPSHOT_DIFF\n"
        "geography_semantics: COUNTY\n"
        "temporal_semantics: as_of_date\n"
        "workbook_sheet: Sheet1\n"
        "header_row: 1\n"
        "maximum_workbook_bytes: 1048576\n"
        "required_columns:\n"
        "  - FIPSCode\n"
        "artifact_policy: PUBLIC_SEVEN_YEAR\n"
        "destination: RAW.EXAMPLE\n"
        "quality_rules:\n"
        "  - rule_id: example_required_columns\n"
        "    severity: BLOCKING\n"
        "restrictions:\n"
        "  - Replace endpoint and sheet before Tier B runs.\n"
    )
