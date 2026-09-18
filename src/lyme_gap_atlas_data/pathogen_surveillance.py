"""Validation for the restricted CDC ArboNET Ixodes pathogen-status workbook.

This module deliberately validates only source semantics. It never uploads,
logs, or otherwise publishes the requestor-restricted workbook bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from openpyxl import load_workbook  # type: ignore[import-untyped]

from .settings import PipelineSettings

RESOURCE_KEY = "cdc_tick_ixodes_pathogen_status"
SOURCE_DATASET_ID = "cdc-ixodes-pathogen-status-2025"
PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "sources"
    / "cdc_tick_ixodes_pathogen_status.yml"
)
EXPECTED_HEADERS = (
    "FIPS_Code",
    "State",
    "County",
    "Borrelia_burgdorferi_sensu_stricto_County_Status",
    "Borrelia_burgdorferi_sensu_stricto_Data_Source",
    "Borrelia_mayonii_County_Status",
    "Borrelia_mayonii_Data_Source",
    "Borrelia_miyamotoi_County_Status",
    "Borrelia_miyamotoi_Data_Source",
    "Anaplasma_phagocytophilum_human_active_variant_County_Status",
    "Anaplasma_phagocytophilum_human_active_variant_Data_Source",
    "Ehrlichia_muris_eauclairensis_County_Status",
    "Ehrlichia_muris_eauclairensis_Data_Source",
    "Babesia_microti_County_Status",
    "Babesia_microti_Data_Source",
    "Powassan_virus_County_Status",
    "Powassan_virus_Data_Source",
)


@dataclass(frozen=True)
class PathogenWorkbookEvidence:
    sample: list[dict[str, object]]
    valid_county_row_count: int
    blank_fips_row_count: int
    schema: dict[str, object]

    @property
    def row_count(self) -> int:
        """Use the evidence interface shared by bounded workbook capture."""
        return self.valid_county_row_count


@dataclass(frozen=True)
class RestrictedPathogenRow:
    """One source-faithful restricted row, retained only inside the private loader."""

    source_row_number: int
    fips: str
    burgdorferi_status: str
    burgdorferi_source: str | None
    source_row_hash: str
    raw: dict[str, object]


def load_pathogen_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    """Load the exact, DEV-only profile for the reviewed pathogen workbook."""
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("Invalid pathogen-surveillance source profile")
    expected = {
        "resource_key": RESOURCE_KEY,
        "source_dataset_id": SOURCE_DATASET_ID,
        "connector_name": "HTTP_XLSX_V1",
        "landing_page_url": "https://www.cdc.gov/ticks/data-research/facts-stats/tick-surveillance-data-sets.html",
        "workbook_sheet": "Ixodes Pathogens 2025",
        "header_row": 2,
        "deterministic_order_clause": "FIPS_Code ASC",
        "incremental_strategy": "SNAPSHOT_DIFF",
        "onboarding_mode": "EVIDENCE_ONLY",
    }
    if any(profile.get(key) != value for key, value in expected.items()):
        raise ValueError("Pathogen-surveillance profile does not match the reviewed source")
    if profile.get("onboarding_environments") != ["dev", "prod"]:
        raise ValueError(
            "Pathogen-surveillance profile must name the approved DEV and PROD envelopes"
        )
    return profile


def parse_pathogen_workbook(
    payload: bytes, profile: dict[str, Any], sample_limit: int
) -> PathogenWorkbookEvidence:
    """Fail closed on changed workbook structure or status semantics."""
    if not 1 <= sample_limit <= int(profile["maximum_sample_limit"]):
        raise ValueError("sample_limit is outside the configured bound")
    if not zipfile.is_zipfile(BytesIO(payload)):
        raise ValueError("CDC pathogen-surveillance evidence is not a valid XLSX package")
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        if sum(member.file_size for member in archive.infolist()) > int(
            profile["maximum_uncompressed_bytes"]
        ):
            raise ValueError("CDC pathogen workbook exceeds the configured uncompressed byte bound")
        if any(
            member.filename.startswith(("/", "\\")) or ".." in Path(member.filename).parts
            for member in archive.infolist()
        ):
            raise ValueError("CDC pathogen workbook contains an invalid package member")
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    required_sheets = {"Data Use Agreement", "Classification Terms", profile["workbook_sheet"]}
    if len(workbook.sheetnames) > 10 or not required_sheets.issubset(workbook.sheetnames):
        raise ValueError("CDC pathogen workbook sheet structure changed")
    agreement = " ".join(
        str(value)
        for row in workbook["Data Use Agreement"].iter_rows(values_only=True)
        for value in row
        if value is not None
    ).lower()
    classification = " ".join(
        str(value)
        for row in workbook["Classification Terms"].iter_rows(values_only=True)
        for value in row
        if value is not None
    ).lower()
    agreement_terms = (
        "access to arbonet tick module data is limited",
        "should not be provided to other persons",
        "appropriately referenced",
        "final copy",
    )
    classification_terms = ("present", "no records", "not be interpreted as")
    if any(term not in agreement for term in agreement_terms) or any(
        term not in classification for term in classification_terms
    ):
        raise ValueError("CDC pathogen workbook data-use or classification semantics changed")
    sheet = workbook[profile["workbook_sheet"]]
    if sheet.max_row is None or sheet.max_column is None or not 3 <= sheet.max_row <= 10_000:
        raise ValueError("CDC pathogen workbook row shape is outside the reviewed evidence bound")
    if sheet.max_column != len(EXPECTED_HEADERS):
        raise ValueError("CDC pathogen workbook column count changed")
    header_row = int(profile["header_row"])
    headers = tuple(
        str(value) if value is not None else ""
        for value in next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
    )
    if headers != EXPECTED_HEADERS:
        raise ValueError("CDC pathogen workbook schema changed; steward review is required")
    allowed = set(profile["allowed_status_values"])
    status_columns = tuple(profile["pathogen_status_columns"])
    sample: list[dict[str, object]] = []
    prior_fips = ""
    valid_count = 0
    blank_count = 0
    for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        if not any(value is not None for value in values):
            continue
        row = dict(zip(headers, values, strict=True))
        fips = row["FIPS_Code"]
        if fips is None or fips == "":
            blank_count += 1
            continue
        if not isinstance(fips, str) or re.fullmatch(r"[0-9]{5}", fips) is None:
            raise ValueError("CDC pathogen workbook does not preserve five-character county FIPS")
        if prior_fips and fips <= prior_fips:
            raise ValueError(
                "CDC pathogen workbook is not deterministically ordered by county FIPS"
            )
        prior_fips = fips
        for column in status_columns:
            if row[column] not in allowed:
                raise ValueError(
                    "CDC pathogen workbook contains an unreviewed pathogen-status value"
                )
        valid_count += 1
        if len(sample) < sample_limit:
            sample.append(row)
    if len(sample) != sample_limit:
        raise ValueError("CDC pathogen workbook does not contain the requested bounded sample")
    return PathogenWorkbookEvidence(
        sample=sample,
        valid_county_row_count=valid_count,
        blank_fips_row_count=blank_count,
        schema={
            "contract_version": "tick-surveillance-v1",
            "observation_type": "PATHOGEN_PRESENCE_STATUS",
            "workbook_sheet": sheet.title,
            "header_row": header_row,
            "headers": list(headers),
            "dataset_as_of": str(profile["dataset_as_of"]),
            "temporal_semantics": profile["temporal_semantics"],
            "allowed_status_values": list(profile["allowed_status_values"]),
            "pathogen_status_columns": profile["pathogen_status_columns"],
            "embedded_data_use_agreement_validated": True,
            "embedded_classification_terms_validated": True,
            "full_dataset_quality_validated": False,
        },
    )


def collect_pathogen_surveillance_evidence(
    sample_limit: int = 25, *, evidence_bundle_dir: Path
) -> dict[str, object]:
    """Retain a bounded DEV review candidate; never load RAW or publish data."""
    # Imported here to keep the parser independent of Snowflake/Spaces imports.
    from .tick_surveillance import collect_restricted_workbook_evidence

    return collect_restricted_workbook_evidence(
        sample_limit=sample_limit,
        evidence_bundle_dir=evidence_bundle_dir,
        profile=load_pathogen_profile(),
        parser=parse_pathogen_workbook,
        source_title="CDC ArboNET pathogen county status",
        publisher="CDC ArboNET Tick Module",
        code_version="cdc-pathogen-ixodes-evidence-v1",
        status_semantics={
            "Present": "Publisher cumulative county pathogen identification status",
            "No records": (
                "No documented published county record; not pathogen absence or a negative test"
            ),
        },
        limitations=(
            "Cumulative county pathogen status through 2025-12-31; No records is not pathogen "
            "absence or a negative test. The workbook supplies no testing counts, positive counts, "
            "sampling effort, or laboratory-method detail. It is therefore a pathogen-presence "
            "status, not prevalence. Evidence capture retains the requestor-restricted workbook "
            "privately, serializes only a bounded sample, creates no RAW rows, and requires a "
            "steward review before any further use. ArboNET attribution and final-publication-copy "
            "obligations apply."
        ),
    )


def restricted_pathogen_rows(
    payload: bytes, profile: dict[str, Any]
) -> tuple[PathogenWorkbookEvidence, list[RestrictedPathogenRow]]:
    """Validate then prepare rows for the owner-rights DEV-only procedure.

    This function deliberately has no logging or serialization side effects.
    Its callers must keep the returned values inside the private envelope
    process and send them only as bound parameters to the restricted procedure.
    """
    evidence = parse_pathogen_workbook(payload, profile, sample_limit=1)
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    sheet = workbook[profile["workbook_sheet"]]
    header_row = int(profile["header_row"])
    headers = tuple(
        str(value) if value is not None else ""
        for value in next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
    )
    rows: list[RestrictedPathogenRow] = []
    for source_row_number, values in enumerate(
        sheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1
    ):
        if not any(value is not None for value in values):
            continue
        raw = dict(zip(headers, values, strict=True))
        fips = raw["FIPS_Code"]
        if fips is None or fips == "":
            continue
        # parse_pathogen_workbook already verified type, ordering, and vocabulary.
        assert isinstance(fips, str)
        canonical_raw = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
        rows.append(
            RestrictedPathogenRow(
                source_row_number=source_row_number,
                fips=fips,
                burgdorferi_status=str(raw["Borrelia_burgdorferi_sensu_stricto_County_Status"]),
                burgdorferi_source=_optional_text(
                    raw["Borrelia_burgdorferi_sensu_stricto_Data_Source"]
                ),
                source_row_hash=hashlib.sha256(canonical_raw.encode("utf-8")).hexdigest(),
                raw=raw,
            )
        )
    if len(rows) != evidence.valid_county_row_count:
        raise ValueError("CDC pathogen workbook row count changed during private preparation")
    return evidence, rows


def ingest_restricted_pathogen(
    *, evidence_bundle_dir: Path, evidence_run_id: str
) -> dict[str, object]:
    """Load derived output only through the environment's owner-rights boundary."""
    pipeline_settings = PipelineSettings()
    if pipeline_settings.topx_env not in {"dev", "prod"}:
        raise ValueError("Restricted pathogen derivation is limited to governed DEV or PROD")
    if pipeline_settings.topx_env == "prod" and (
        os.getenv("RESTRICTED_CDC_PROD_OPERATOR_ENVELOPE") != "true"
        or not getattr(pipeline_settings, "enable_production_execution", False)
    ):
        raise ValueError(
            "Production restricted derivation requires the protected operator envelope"
        )
    if not re.fullmatch(r"[0-9a-f-]{36}", evidence_run_id):
        raise ValueError("evidence_run_id must be a UUID")
    # Importing the private bundle verifier here avoids expanding its public interface.
    from .tick_surveillance import _load_evidence_bundle

    profile = load_pathogen_profile()
    bundle = _load_evidence_bundle(evidence_bundle_dir, profile)
    evidence, rows = restricted_pathogen_rows(bundle.workbook.payload, profile)
    payload = json.dumps(
        [
            {
                "source_row_number": row.source_row_number,
                "fips": row.fips,
                "burgdorferi_status": row.burgdorferi_status,
                "burgdorferi_source": row.burgdorferi_source,
                "source_row_hash": row.source_row_hash,
                "raw": row.raw,
            }
            for row in rows
        ],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    # Snowflake VARIANT has a 16 MB practical ceiling.  Refuse rather than chunk
    # restricted rows, because a partial load would break source-faithful lineage.
    if len(payload.encode("utf-8")) > 14_000_000:
        raise ValueError("Restricted pathogen payload exceeds the reviewed procedure bound")
    run_id = str(uuid.uuid4())
    retrieved_at = str(bundle.manifest["retrieved_at"])
    workbook_sha256 = hashlib.sha256(bundle.workbook.payload).hexdigest()
    procedure_name = f"GOVERNANCE.SP_LOAD_RESTRICTED_PATHOGEN_{pipeline_settings.topx_env.upper()}"
    settings = SnowflakeSettings()
    with connect(settings) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_RUNS
                    (ingestion_run_id, resource_key, run_mode, trigger_type, status, code_version,
                     config_sha256, started_at)
                    VALUES (%s, 'cdc_tick_ixodes_pathogen_status', %s,
                            'MANUAL', 'RUNNING',
                            'cdc-pathogen-restricted-derivation-v1', %s, %s)""",
                    (
                        run_id,
                        (
                            "RESTRICTED_FULL_PROD"
                            if pipeline_settings.topx_env == "prod"
                            else "RESTRICTED_FULL_DEV"
                        ),
                        hashlib.sha256(
                            yaml.safe_dump(profile, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                        datetime.now(UTC),
                    ),
                )
                cursor.execute(
                    f"CALL {procedure_name}(%s, %s, %s, PARSE_JSON(%s), %s)",
                    (run_id, evidence_run_id, workbook_sha256, payload, retrieved_at),
                )
                result = cursor.fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    procedure_result = result[0] if result is not None else None
    return {
        "ingestion_run_id": run_id,
        "evidence_run_id": evidence_run_id,
        "workbook_sha256": workbook_sha256,
        "source_count": evidence.valid_county_row_count,
        "blank_fips_row_count": evidence.blank_fips_row_count,
        "status": "PENDING_PARITY_CLASSIFICATION",
        "procedure_result": procedure_result,
    }


def ingest_restricted_pathogen_dev(
    *, evidence_bundle_dir: Path, evidence_run_id: str
) -> dict[str, object]:
    """Backward-compatible DEV entrypoint for the approved private derivation."""
    if PipelineSettings().topx_env != "dev":
        raise ValueError("This compatibility entrypoint is DEV-only")
    return ingest_restricted_pathogen(
        evidence_bundle_dir=evidence_bundle_dir, evidence_run_id=evidence_run_id
    )


def capture_and_ingest_restricted_pathogen_dev(
    *, sample_limit: int, evidence_bundle_dir: Path
) -> dict[str, object]:
    """Run the private evidence and derivation steps without exposing source rows."""
    evidence = collect_pathogen_surveillance_evidence(
        sample_limit=sample_limit, evidence_bundle_dir=evidence_bundle_dir
    )
    evidence_run_id = evidence.get("ingestion_run_id")
    if not isinstance(evidence_run_id, str):
        raise ValueError("Restricted evidence capture did not return an ingestion run ID")
    derivation = ingest_restricted_pathogen_dev(
        evidence_bundle_dir=evidence_bundle_dir, evidence_run_id=evidence_run_id
    )
    return {"evidence": evidence, "derivation": derivation}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
