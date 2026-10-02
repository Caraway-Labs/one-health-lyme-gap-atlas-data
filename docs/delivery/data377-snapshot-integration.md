# DATA377 final owner-contract integration

Base: DATA372 merge `b7493e1aaef9c4f8107a9439a757dc3c23e83cb4`.
DATA376 final consumer tests merged through PR565 at
`f28efd9d510ea117d774846292ead8f6bb3e8603`.
Historical expected outcomes remain byte-unchanged from the pre-implementation
freeze `3c81b471c802b1ad7e9361740319bd7cbeb50b4b`.

`tests/test_delivery_snapshot_integration.py` consumes the final published current
DEV snapshot through `validate_snapshot` and `report`, plus all four historical
packets through mandatory `validate_packet` and `review_context`. Fixed capture
times make these offline regressions repeatable. Expiry, tampering and mixed-source
comparisons use in-memory copies; no destructive live failure is induced.

| Capstone boundary | Final consumer result |
| --- | --- |
| #336 connector batch / #353 procedure binding | Historical repair UNKNOWN; metadata cannot supply absent behavior |
| #365 canonical coverage | Frozen county fixture unchanged; metadata cannot supply parity semantics |
| #366 runtime authority | Frozen sanitized denial BLOCKED; invisible authority remains UNKNOWN |
| Missing mandatory context | Existing path regression remains BLOCKED |
| Stale context | Final DATA372 observation expires after reviewed TTL; refresh required |
| Tampered and mixed-source evidence | Integrity mismatch or non-live comparison; consequential use blocked |
| Final DATA372/DATA376 integration | Both reviewed APIs and published artifacts consumed without owner implementation edits |

DATA372's actual DEV capture remains partial, with PROD unverified and no selected
procedures. Empty grants are not absence proof. Metadata is not row lineage and
never becomes observed functional capability or runtime authority. Its original
capture workload and UTC provenance remain intact; the capstone does not relabel
the observation with its own commit. See
[DATA372 acceptance handoff](data372-evidence-2026-10-02.md).

DATA374 runtime evidence is proposed separately in PR567 at
`9560ceffd2bc0bba50a502a153bd409334960132`: installed root/nested discovery,
bounded metadata routing and actual DEV SELECT/anonymous scripting/CTE recipes.
That PR requires independent review and fresh-main exact CI before merge.
End-to-end skill execution, interactive/assembled-workspace discovery, bulk INSERT,
exact procedure caller/owner binding, role allow/deny, replacement grants/bootstrap
and V098 procedure execution remain unverified. These gaps prevent a claim of
complete capstone acceptance. No new credentials, grants, migrations, deployment
or snapshot/evidence-owner implementation changes are introduced.
