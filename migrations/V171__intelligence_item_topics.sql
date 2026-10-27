-- Vocabulary topic rows for intelligence item revisions.
-- Readers use the v1 projections. The pipeline runtime may merge item topic rows.
-- The vocabulary table is static. Rows merge on topic and vocabulary version
-- so a retry after a later statement failure does not insert duplicates.
-- A fallback match stores a null matched term.
-- Captured item documents stay unchanged.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS CONFORMED.INTELLIGENCE_ITEM_TOPICS (
    item_id VARCHAR(64) NOT NULL,
    revision_id VARCHAR(64) NOT NULL,
    topic_id VARCHAR(64) NOT NULL,
    vocabulary_version VARCHAR(16) NOT NULL,
    matched_field VARCHAR(32) NOT NULL,
    matched_term VARCHAR(4096),
    computed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (item_id, revision_id, topic_id, vocabulary_version)
);

GRANT SELECT, INSERT, UPDATE ON TABLE CONFORMED.INTELLIGENCE_ITEM_TOPICS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;

CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_ITEM_TOPICS_V1 AS
SELECT item_id,
       revision_id,
       topic_id,
       vocabulary_version,
       matched_field,
       matched_term,
       computed_at
FROM CONFORMED.INTELLIGENCE_ITEM_TOPICS
WHERE vocabulary_version = 'v1';

GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_ITEM_TOPICS_V1
    TO ROLE OH_LYME_{{ ENV }}_READ;

CREATE TABLE IF NOT EXISTS CONFORMED.INTELLIGENCE_TOPICS (
    topic_id VARCHAR(64) NOT NULL,
    vocabulary_version VARCHAR(16) NOT NULL,
    label VARCHAR(256) NOT NULL,
    definition VARCHAR(4096) NOT NULL,
    sort_order NUMBER(10, 0) NOT NULL,
    PRIMARY KEY (topic_id, vocabulary_version)
);

MERGE INTO CONFORMED.INTELLIGENCE_TOPICS AS target
USING (
    SELECT
        column1 AS topic_id,
        column2 AS vocabulary_version,
        column3 AS label,
        column4 AS definition,
        column5 AS sort_order
    FROM VALUES
    ('lyme-disease', 'v1', 'Lyme disease', 'Borrelia burgdorferi sensu lato infection and the clinical disease called Lyme disease.', 0),
    ('babesiosis', 'v1', 'Babesiosis', 'Babesia infection, including babesiosis.', 1),
    ('anaplasmosis', 'v1', 'Anaplasmosis', 'Anaplasma infection, including human granulocytic anaplasmosis.', 2),
    ('ehrlichiosis', 'v1', 'Ehrlichiosis', 'Ehrlichia infection, including human monocytic ehrlichiosis.', 3),
    ('powassan', 'v1', 'Powassan', 'Powassan virus infection and deer tick virus.', 4),
    ('alpha-gal', 'v1', 'Alpha-gal', 'Alpha-gal syndrome and galactose-alpha-1,3-galactose allergy.', 5),
    ('spotted-fever-rickettsioses', 'v1', 'Spotted fever rickettsioses', 'Spotted fever group Rickettsia infections, including Rocky Mountain spotted fever.', 6),
    ('tick-borne-encephalitis', 'v1', 'Tick-borne encephalitis', 'Tick-borne encephalitis virus infection.', 7),
    ('cchf-sfts', 'v1', 'CCHF and SFTS', 'Crimean-Congo hemorrhagic fever and severe fever with thrombocytopenia syndrome.', 8),
    ('ticks-and-vectors', 'v1', 'Ticks and vectors', 'Ticks and the tick genera that transmit pathogens.', 9),
    ('zoonoses-one-health', 'v1', 'Zoonoses and One Health', 'Infections shared by people and animals, and One Health reports of those infections.', 10),
    ('arboviruses', 'v1', 'Arboviruses', 'Arthropod-borne viruses, including dengue, Zika, West Nile, and chikungunya.', 11),
    ('foodborne-enteric', 'v1', 'Foodborne and enteric', 'Foodborne and enteric infections, including Salmonella, Campylobacter, and hepatitis A.', 12),
    ('respiratory', 'v1', 'Respiratory', 'Respiratory infections, including influenza, COVID-19, and pneumonic disease.', 13),
    ('vaccines', 'v1', 'Vaccines', 'Vaccines, vaccination, and immunization.', 14),
    ('antimicrobial-resistance', 'v1', 'Antimicrobial resistance', 'Antimicrobial and antibiotic resistance, including MRSA and carbapenem resistance.', 15),
    ('surveillance-data', 'v1', 'Surveillance data', 'Public-health surveillance products and routine statistical summaries such as QuickStats.', 16),
    ('diagnostics', 'v1', 'Diagnostics', 'Laboratory diagnostics, including PCR, serology, and molecular detection.', 17),
    ('other-public-health', 'v1', 'Other public health', 'Public-health item with no vocabulary v1 topic match.', 18)
) AS source
ON target.topic_id = source.topic_id
 AND target.vocabulary_version = source.vocabulary_version
WHEN MATCHED AND (
    target.label IS DISTINCT FROM source.label
    OR target.definition IS DISTINCT FROM source.definition
    OR target.sort_order IS DISTINCT FROM source.sort_order
) THEN UPDATE SET
    label = source.label,
    definition = source.definition,
    sort_order = source.sort_order
WHEN NOT MATCHED THEN INSERT (
    topic_id, vocabulary_version, label, definition, sort_order
) VALUES (
    source.topic_id, source.vocabulary_version, source.label, source.definition, source.sort_order
);

CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_TOPICS_V1 AS
SELECT topic_id,
       vocabulary_version,
       label,
       definition,
       sort_order
FROM CONFORMED.INTELLIGENCE_TOPICS
WHERE vocabulary_version = 'v1';

GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_TOPICS_V1
    TO ROLE OH_LYME_{{ ENV }}_READ;
