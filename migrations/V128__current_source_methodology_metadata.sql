-- Data #515 / API #55: approved public identities over the current release.
-- Source and method mappings fail closed if the reviewed source tuple or
-- methodological meaning changes in a future release.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_SOURCE_METADATA_V
COPY GRANTS AS
SELECT s.source_key, s.label, s.vintage, s.source_url, s.note,
       s.source_id, s.dataset_id,
       CASE WHEN s.source_key = 'human'
                  AND s.source_id = 'cdc_lyme'
                  AND s.dataset_id = 'x5j9-wybp'
            THEN 'Centers for Disease Control and Prevention'
            ELSE NULL END AS publisher,
       CAST(NULL AS TIMESTAMP_LTZ) AS upstream_updated_at,
       CAST(NULL AS TIMESTAMP_LTZ) AS source_retrieved_at,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s ON s.release_id = r.release_id
WHERE p.pointer_key = 'ATLAS';

GRANT SELECT ON VIEW PRESENTATION.CURRENT_SOURCE_METADATA_V
  TO ROLE OH_LYME_{{ ENV }}_READ;

CREATE VIEW IF NOT EXISTS PRESENTATION.CURRENT_METHODOLOGY_METADATA_V AS
WITH approved_methodologies AS (
    SELECT column1 AS measure_id, column2 AS methodology_id,
           column3 AS approved_text, column4 AS approved_limitation
    FROM VALUES
      ('human_status', 'human_source_native_status_mapping_v1',
       'source-native status mapping',
       'Published floors are not complete incidence.'),
      ('case_count_floor_2023', 'human_confirmed_probable_case_floor_v1',
       'x5j9 confirmed plus probable', 'Privacy-protected floor.'),
      ('incidence_floor_2023', 'human_case_floor_population_incidence_v1',
       'case floor divided by population', 'Not complete incidence.')
)
SELECT a.methodology_id, m.measure_id, m.methodology,
       r.methodology_version, m.limitation,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.CURRENT_MEASURE_METADATA_V m
  ON m.release_version = r.release_id
JOIN approved_methodologies a
  ON a.measure_id = m.measure_id
 AND a.approved_text = m.methodology
 AND a.approved_limitation = m.limitation
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id
 AND s.source_key = 'human'
 AND s.source_id = 'cdc_lyme'
 AND s.dataset_id = 'x5j9-wybp'
WHERE p.pointer_key = 'ATLAS';

GRANT SELECT ON VIEW PRESENTATION.CURRENT_METHODOLOGY_METADATA_V
  TO ROLE OH_LYME_{{ ENV }}_READ;

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
COPY GRANTS AS
SELECT o.observation_id,
       m.measure_id,
       o.fips AS geography_id,
       'COUNTY' AS geography_type,
       o.fips AS county_fips,
       DATE '2023-01-01' AS period_start,
       DATE '2023-12-31' AS period_end,
       'YEAR' AS temporal_grain,
       o.value,
       o.value_state,
       m.unit,
       m.denominator,
       m.supported_stratifications,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version,
       o.source_key,
       s.label AS source_label,
       s.vintage AS source_vintage,
       s.source_url,
       o.retrieved_at,
       o.transformation_version,
       m.methodology,
       r.methodology_version AS release_methodology_version,
       o.limitations AS observation_limitations,
       m.limitation AS measure_limitation,
       r.limitations AS release_limitations,
       s.source_id,
       s.dataset_id,
       mm.methodology_id
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_OBSERVATIONS o ON o.release_id = r.release_id
JOIN PRESENTATION.CURRENT_MEASURE_METADATA_V m
  ON m.release_version = r.release_id AND m.measure_id = o.measure_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id AND s.source_key = o.source_key
LEFT JOIN PRESENTATION.CURRENT_METHODOLOGY_METADATA_V mm
  ON mm.release_version = r.release_id AND mm.measure_id = m.measure_id
JOIN PRESENTATION.SEMANTIC_COUNTY_ATLAS c
  ON c.release_id = r.release_id AND c.fips = o.fips
WHERE p.pointer_key = 'ATLAS'
  AND o.measure_id IN ('human_status', 'case_count_floor_2023', 'incidence_floor_2023')
  AND o.source_key = 'human'
  AND o.geography_semantics = 'COUNTY_FIPS_5'
  AND REGEXP_LIKE(o.fips, '[0-9]{5}')
  AND o.temporal_window = '2023'
  AND m.geography_type = 'COUNTY_FIPS_5'
  AND m.temporal_grain = '2023';

GRANT SELECT ON VIEW PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
