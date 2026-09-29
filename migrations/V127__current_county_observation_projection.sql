-- Data #513 / API #54: narrow, current-release county observation publication.
-- The allowlist is intentionally explicit. The historical release has other
-- snapshot, cumulative, geometry, and state-native slots without a defensible
-- annual county period in this public query shape.
USE DATABASE {{ DATABASE }};

CREATE VIEW IF NOT EXISTS PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V AS
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
       r.limitations AS release_limitations
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_OBSERVATIONS o ON o.release_id = r.release_id
JOIN PRESENTATION.CURRENT_MEASURE_METADATA_V m
  ON m.release_version = r.release_id AND m.measure_id = o.measure_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id AND s.source_key = o.source_key
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
