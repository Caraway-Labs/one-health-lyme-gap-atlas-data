# SOURCE_APPROVAL_CONSOLE

This Snowflake-native application reads only governed views and records a
decision only through `GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION`. It makes
no external network requests and has no secrets or App Platform credentials.
