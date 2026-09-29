-- Data #499: historical release builder bound measure/indicator values in
-- reverse physical columns. Do not rewrite immutable release rows. Resolve
-- the relationship against the release's own indicator identities; the
-- corrected builder uses the direct association for future releases.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_MEASURE_METADATA_V AS
SELECT CASE WHEN direct_indicator.indicator_id IS NOT NULL
            THEN m.measure_id ELSE m.indicator_id END AS measure_id,
       COALESCE(direct_indicator.indicator_id, legacy_indicator.indicator_id)
         AS indicator_id,
       m.label,
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
LEFT JOIN PRESENTATION.SEMANTIC_INDICATORS direct_indicator
  ON direct_indicator.release_id = r.release_id
 AND direct_indicator.indicator_id = m.indicator_id
LEFT JOIN PRESENTATION.SEMANTIC_INDICATORS legacy_indicator
  ON legacy_indicator.release_id = r.release_id
 AND legacy_indicator.indicator_id = m.measure_id
 AND direct_indicator.indicator_id IS NULL
WHERE p.pointer_key = 'ATLAS'
  AND COALESCE(direct_indicator.indicator_id, legacy_indicator.indicator_id)
      IS NOT NULL;

GRANT SELECT ON VIEW PRESENTATION.CURRENT_MEASURE_METADATA_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
