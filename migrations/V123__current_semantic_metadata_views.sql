-- Data #499: current approved release metadata, with a closed column allowlist.
-- Release hierarchy rows are immutable; the ATLAS pointer is the only selector.
USE DATABASE {{ DATABASE }};

CREATE VIEW IF NOT EXISTS PRESENTATION.CURRENT_INDICATOR_METADATA_V AS
SELECT i.indicator_id, i.label, i.description, i.limitation,
       CAST(NULL AS VARCHAR) AS domain,
       CAST(NULL AS VARCHAR) AS category,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_INDICATORS i ON i.release_id = r.release_id
WHERE p.pointer_key = 'ATLAS';

CREATE VIEW IF NOT EXISTS PRESENTATION.CURRENT_MEASURE_METADATA_V AS
SELECT m.measure_id, m.indicator_id, m.label,
       CAST(NULL AS VARCHAR) AS description,
       m.data_type AS measure_type, m.unit,
       CAST(NULL AS VARCHAR) AS denominator,
       m.geography_semantics AS geography_type,
       m.temporal_resolution AS temporal_grain,
       CAST(NULL AS VARCHAR) AS supported_stratifications,
       CAST(NULL AS VARCHAR) AS source_references,
       CAST(NULL AS VARCHAR) AS standards_mappings,
       m.missingness_semantics, m.methodology, m.limitation,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_MEASURES m ON m.release_id = r.release_id
WHERE p.pointer_key = 'ATLAS';

GRANT SELECT ON VIEW PRESENTATION.CURRENT_INDICATOR_METADATA_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
GRANT SELECT ON VIEW PRESENTATION.CURRENT_MEASURE_METADATA_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
