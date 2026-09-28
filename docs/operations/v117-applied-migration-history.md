# Canonical DEV V117 migration history

The protected validation of draft PR #488 applied the nClimGrid internal bulk
transport stage as V117 in DEV. Its immutable migration receipt has SHA-256
`97dc205df634efdefa5dc561b36481068cfaa09dc6391d2acdc8cdf474add5e0`.

PR #489 independently introduced a different V117 and a V118 before its
Dataset Discovery migrations were applied. PR #490 moved those unapplied SQL
bodies forward to V119 (safe metadata projection) and V120 (candidate decision
audit). V119 and V120 then applied successfully in DEV. V118 remains
intentionally unused. Applied receipts are never renumbered for cosmetic
contiguity.

This hotfix restores the byte-identical V117 stage source to repository history,
marks it DEV-only, and retains its DEV owner execution role. It does not execute
a new logical migration, edit the DEV ledger, change either Dataset Discovery
migration, grant schema creation rights to the runtime, or touch PROD. The
protected deploy should validate the three existing receipts and skip all three.
