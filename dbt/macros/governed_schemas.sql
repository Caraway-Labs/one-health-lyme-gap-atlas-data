{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}

{% macro snowflake__create_schema(relation) -%}
  {# Schemas are provisioned and authorized by append-only Snowflake migrations. #}
  {%- if relation.schema not in ["STAGING", "CONFORMED"] -%}
    {{ exceptions.raise_compiler_error("dbt may create relations only in governed schemas") }}
  {%- endif -%}
  select 1 as governed_schema_exists
{%- endmacro %}
