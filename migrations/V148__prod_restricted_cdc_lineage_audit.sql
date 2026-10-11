-- Repair the existing internal audit for the already governed PROD CDC path.
-- No source data, admission decision, release pointer or grant is changed.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE SECURE VIEW LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V COPY GRANTS AS
SELECT o.observation_id,
       o.release_id,
       o.measure_id,
       o.fips AS county_fips,
       o.temporal_window,
       o.source_key,
       o.source_version_id,
       dsv.data_source_version_id AS governed_source_version_id,
       o.ingestion_run_id,
       run.ingestion_run_id AS governed_ingestion_run_id,
       o.artifact_id,
       a.sha256 AS artifact_sha256,
       o.source_record_id AS semantic_source_record_id,
       o.source_row_hash AS semantic_source_row_hash,
       s.source_id,
       s.dataset_id,
       s.resource_key,
       r.bundle_sha256 AS release_bundle_sha256,
       v.record_id AS revision_record_id,
       v.capture_record_id,
       v.record_revision,
       v.artifact_sha256 AS revision_artifact_sha256,
       COALESCE(c.record_id, t.conformed_record_id, p.conformed_record_id) AS conformed_record_id,
       COALESCE(v.source_record_id, c.source_record_id, t.source_record_id,
                p.source_record_id) AS governed_source_record_id,
       COALESCE(v.source_row_hash, c.source_row_hash, t.source_row_hash,
                p.source_row_hash) AS governed_source_row_hash,
       CASE WHEN v.capture_record_id IS NOT NULL THEN 'IMMUTABLE_REVISION'
            WHEN c.record_id IS NOT NULL THEN 'LEGACY_CONFORMED'
            WHEN t.conformed_record_id IS NOT NULL OR p.conformed_record_id IS NOT NULL
              THEN 'RESTRICTED_CDC_CONFORMED'
            ELSE 'UNMATCHED' END AS record_match_kind
FROM PRESENTATION.SEMANTIC_OBSERVATIONS o
JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id = o.release_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = o.release_id AND s.source_key = o.source_key
 AND s.source_version_id = o.source_version_id
 AND s.ingestion_run_id = o.ingestion_run_id
 AND s.artifact_id = o.artifact_id
LEFT JOIN GOVERNANCE.DATA_SOURCE_VERSIONS dsv
  ON dsv.data_source_version_id = o.source_version_id
 AND dsv.resource_key = s.resource_key
 AND (dsv.ingestion_run_id IS NULL OR dsv.ingestion_run_id = o.ingestion_run_id)
 AND (dsv.artifact_id IS NULL OR dsv.artifact_id = o.artifact_id)
LEFT JOIN GOVERNANCE.INGESTION_RUNS run
  ON run.ingestion_run_id = o.ingestion_run_id
 AND run.resource_key = s.resource_key
LEFT JOIN GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS v
  ON v.source_id = s.source_id AND v.dataset_id = s.dataset_id
 AND v.resource_key = s.resource_key AND v.ingestion_run_id = o.ingestion_run_id
 AND v.artifact_id = o.artifact_id AND v.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR v.source_record_id = o.source_record_id
      OR v.record_id = o.source_record_id)
LEFT JOIN CONFORMED.GOVERNED_SOURCE_RECORDS c
  ON v.capture_record_id IS NULL
 AND c.source_id = s.source_id AND c.dataset_id = s.dataset_id
 AND c.resource_key = s.resource_key AND c.ingestion_run_id = o.ingestion_run_id
 AND c.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR c.source_record_id = o.source_record_id
      OR c.record_id = o.source_record_id)
LEFT JOIN CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS t
  ON v.capture_record_id IS NULL AND c.record_id IS NULL
 AND o.source_key = 'tick' AND s.resource_key = 'cdc_tick_ixodes_county_status'
 AND s.source_id = 'cdc_arbonet_tick_module' AND s.dataset_id = 'cdc-ixodes-county-status-2025'
 AND t.resource_key = s.resource_key AND t.ingestion_run_id = o.ingestion_run_id
 AND t.county_fips = o.fips AND t.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR t.source_record_id = o.source_record_id
      OR t.conformed_record_id = o.source_record_id)
LEFT JOIN CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS p
  ON v.capture_record_id IS NULL AND c.record_id IS NULL
 AND o.source_key = 'pathogen' AND s.resource_key = 'cdc_tick_ixodes_pathogen_status'
 AND s.source_id = 'cdc_arbonet_tick_module' AND s.dataset_id = 'cdc-ixodes-pathogen-status-2025'
 AND p.resource_key = s.resource_key AND p.ingestion_run_id = o.ingestion_run_id
 AND p.county_fips = o.fips AND p.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR p.source_record_id = o.source_record_id
      OR p.conformed_record_id = o.source_record_id)
LEFT JOIN GOVERNANCE.RAW_ARTIFACTS a
  ON a.artifact_id = o.artifact_id
 AND a.ingestion_run_id = COALESCE(t.evidence_run_id, p.evidence_run_id, o.ingestion_run_id)
 AND (t.conformed_record_id IS NULL OR a.sha256 = t.workbook_sha256)
 AND (p.conformed_record_id IS NULL OR a.sha256 = p.workbook_sha256);
