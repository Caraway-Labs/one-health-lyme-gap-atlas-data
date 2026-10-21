# Approved CDC metadata feed expansion

Scope: add only CDC EID Ahead-of-Print and CDC Outbreaks to the existing canonical RSS ingestion, fixed registration and existing raw-copy expiry path. Existing Data/API/Web boundaries and the 2 MiB / 250 item / 30 second / one attempt / zero redirects bounds remain. No new pipeline or scheduler is introduced.

Source authority is Matthew's recorded eight-source selection, DATA #132 comment 5964095143, and his explicit October 21 instruction to execute supported feed expansion. NIAID, WHO and Vital Signs remain deferred; null-endpoint PubMed definitions are not admitted. NIH and the oversized MMWR/Newsroom feeds are outside this increment. Both added feeds are CDC-owned endpoints already represented by genuine, value-safe native fixtures. Their source approval/trust records refer to the existing owner selection; reviewed_at records when this package reconciled that decision, not an invented timestamp of the owner's action. No new scientific approval, source-health acceptance, or epidemiological claims are inferred.

Reuse the accepted CDC metadata-only direction: title, canonical link, publisher timing and language only, no excerpts, descriptions, full text, image values/bytes or logos; CDC attribution, free-original link and nonendorsement remain. Each native policy is tied to the exact new source document SHA and observed fixture path inventory. The existing restricted 30-day artifact class is reused without broadening its storage rights. Active raw copies retain immutable capture+30-day deadlines and proactive eligibility at day 28.

Production registration/acquisition remain disabled until the fixed registry document, pinned runtime and matching expiry authority pass review, required migrations/security handoff and native production gates. The old EID synthetic proof will not be repeated. A new procedure handoff that expands persistent security authority requires the owner's applicable explicit approval; code merge alone does not authorize it.

Execution accounting must record at most the already-authorized six feed requests / US$5 aggregate across this lane; no provider probes or article fetches are added. The existing native fixtures permit offline transport/policy checks without spending an extra feed request. Acquire each new feed once, then one repoll each only after remaining request/cost accounting is reconciled. Do not silently truncate an oversized response.

## Current normal-transport endpoint evidence

The existing pinned TLS/DNS adapter, real local retention composition and unchanged source bounds made one GET per added source. No Snowflake/Spaces writes or persistent XML were used; local retention metadata contains hashes/claims only. This is current endpoint acceptance, not production registry/ingestion proof.

- cdc-eid-ahead-of-print: HTTP 200, 28 items, 12146 bytes, SHA256 `77f9d54d3429a66cabb7436cd61f5c5567d9fe57c276b104a79d45bf7e414232`. Observed native paths equal the checked-in genuine inventory.
- cdc-outbreaks: HTTP 200, 11 items, 7380 bytes, SHA256 `d15713abccbc43bf2ffd9ee6a02ac12ca19fd926737e8b0b5dc2305400732639`. Observed native paths equal the checked-in genuine inventory.

Request accounting for the current overnight activation: original production EID capture (1), these two endpoint probes (2), then at most two new production captures (2) and one repoll (1) reach the six-request ceiling. Do not execute a second new-source repoll in that same six-request envelope. Any other prior requests/credits must be reconciled before dispatch, not silently excluded. No extra request or spend is authorized by this receipt.
