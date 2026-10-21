# January PROD warehouse login correction

Identity run 38763686984, query 01c7bfd8-030c-3303-0064-2d070123e042,
confirmed user/role/database/region/account PASS and CURRENT_WAREHOUSE() NULL.
The account and credentials are correct and are not changed or re-investigated.

## Code and connector evidence

The shared `connection_parameters(SnowflakeSettings())` already supplies
`warehouse=settings.snowflake_warehouse` correctly. Connector 4.3.0
`auth/_auth.py` passes it as the login URL's `warehouse` parameter and then sets
its connection warehouse property from server `sessionInfo.warehouseName`.
Therefore there is no demonstrated misspelled or discarded warehouse argument.
The confirmed defect is an authenticated session accepted without its required
warehouse selected; retained evidence does not establish why Snowflake returned
NULL, nor does it prove a missing effective USAGE grant.

The connector's `validate_default_parameters` defaults to false. Its supported
true setting asks the server to validate requested database/schema/role/warehouse
during login (`connection.py`, CLIENT_VALIDATE_DEFAULT_PARAMETERS). See the
[official connector API](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api).

The correction enables strict login initialization only for explicit January PROD
workflow contexts. Existing canonical Data connections and the bounded identity
helper share one parameter builder: unchanged approved warehouse argument,
validate_default_parameters=true, statement60/queue10/abort-detached at login,
network65/socket65. The server-returned connection warehouse is checked before
any SQL, with no fallback; NULL or wrong selection closes without retry and fails.
Invalid configured warehouse/database fails before connecting. Other workflows
retain their existing behavior. All six later SQL identity checks, the account
pin, capacity checks, NOAA/TIGER checksums, lineage and owner admission remain.
There is no USE WAREHOUSE, additional session SQL, grant, credential change,
warehouse alteration or migration. V151/V152 are not repeated; V150 is excluded.

This hardening ensures a required warehouse is requested and accepted at login
or the session stops. It cannot grant access or guarantee a successful connection
if Snowflake rejects that existing warehouse for the runtime role. Missing or
inaccessible objects/permissions remain UNKNOWN, not absent.

## Next executable action and authority

The prior identity attempt is consumed. Request **one fresh identity-only
verification attempt**, max $7 (forecast $2.90625), within the existing $200 total,
at the reviewed merged correction. Existing protected runtime identity, exact
January definition, 180s +15s process grace, statement60/queue10/network65/socket65,
login validation and no retries. At most the existing one identity SELECT executes;
a rejected login stops before that SELECT. Human production-environment review
remains required. Do not rerun the prior attempt.

A mock or successful login alone is not a live six-field PASS. Only after the
actual identity SELECT passes all six may the still-undispatched conditional
Stage 2 capture authorization be used, on this reviewed correction with original
pins and its existing $7 ceiling. A failed login or identity gate stops without
USE WAREHOUSE, grant changes, credential substitution or another retry. The
server rejection may identify a required owner-side access action, but no such
change is included or guessed here.

Planning forecast after this extra verification: $136.50 original baseline +
$5.8125 previous recovery + $2.90625 new verification = $145.21875. Adding the full
$7 new reservation to the prior conservative $150.50 allocation gives $157.50,
leaving $42.50 planning headroom below $200. These are not measured billed dollars;
actual remaining budget is unknown without billing evidence. No extra $200 is
requested. Owner admissions, native capture, governed build/publication and
actual API service-reader acceptance follow existing dependency gates.
