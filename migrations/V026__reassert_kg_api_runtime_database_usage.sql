USE DATABASE {{ DATABASE }};

-- The API runtime needs database usage in addition to GOVERNANCE schema and
-- procedure usage. V025's initial partial attempt granted this in DEV before
-- its Alpha presentation-read correction; reassert it forward-only so fresh
-- environments receive the same least-privilege prerequisite.
GRANT USAGE ON DATABASE {{ DATABASE }} TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
