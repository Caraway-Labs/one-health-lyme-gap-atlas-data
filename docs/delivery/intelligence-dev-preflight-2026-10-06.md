# DATA132/135 fixed protected DEV metadata preflight

The existing DEV workflow has no intelligence object/owner inspection mode.
Add one fixed read-only option using the existing protected migration service and
warehouse; it exits before migration application and refuses mixed modes.

Targets are the two raw-retention metadata tables, source-version registry, and
V1/V2 feed views only. Hidden objects remain unknown rather than presumed absent.
Only the two pilot sources' latest version/hash receipts are read; no registry
payload, approval mutation, source HTTP request, source registration, DDL, grants,
or cleanup operation is included.

Execution requires independently reviewed code, reconciled aggregate pilot cost
accounting (including prior/idle/service cost), positive contracted USD/credit,
a conservative total forecast including those overheads, and actual prior feed
request accounting within the six-request cap. It does not establish invoice
truth from caller assertions. Unknown billing or an unknown research-request
count blocks execution. A 50-second process watchdog and 10-second statements
bound the probe; the warehouse is existing infrastructure and remains unchanged.

Public logs contain no inventory. An existing reviewer's RSA public key (2048+
bit) encrypts a random one-use AES-GCM evidence key with RSA-OAEP-SHA256. This is
artifact encryption, not a service credential. No key is created or installed.
The encrypted artifact expires after one day; only its intended reviewer can
recover the private JSON. The watchdog preserves a failure receipt before exit.

Validation: six offline tests cover wrong-identity refusal, reconciled budget,
request reuse, unknown metadata visibility, encrypted evidence recovery, and
workflow branch ordering. Hosted Quality checks remain required. No live query,
DDL application, grant, migration number, image deployment, or paid feed run.

Follow-up: independently review the separately prepared exact minimal DDL/grant
delta, reserve the shared migration slot with parent, inspect actual state via
this mode after budget reconciliation, then select only reviewed required SQL.
Cleanup/purge authority remains separate. Source/native policy and physical
retention prerequisites still gate the first live feed proof.
