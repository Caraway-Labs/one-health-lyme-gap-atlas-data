# Intelligence capture natural key

A daily source run inserts a row in `GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES` only
when no capture already has the same natural key:

`source_id`, `registry_version`, `transport`, `item_id`, `revision_id`.

`capture_id` stays run-scoped. The stored item document includes `fetched_at`
and provenance, so an id that ignored the run would conflict on an exact replay
of that run. Repeat polls of unchanged content do not add another fetch, run, or
artifact row. The existing capture remains that evidence.

The writer classifies each staged item before the insert, with one aggregate
read of captures for that `source_id` and `registry_version`:

- `items_new`: the item has no capture for this source version and transport
- `items_changed`: the item exists, and this revision does not
- `items_unchanged`: the natural key already exists
- `items_seen`: the staged items in the run

`items_new + items_changed + items_unchanged = items_seen`, and
`captures_inserted = items_new + items_changed`. Unchanged items count as
`captures_replayed`. A run that inserts nothing is still completed. `wrote:
false` on LOAD does not change run status. Health stays `quiet` or `healthy`
from new revisions, as before.

An item that disappears from a later feed is left in place. `INTELLIGENCE_FEED_V2`
returns the latest capture per item, revision, source, and transport over all
history, so skipping an unchanged capture does not hide the item. A registry
version bump is a different natural key and inserts one capture for that version.

Description and categories belong inside `publisher_metadata`. The revision hash
already covers that object whole. Add any other newly stored hashed field to
`REVISION_CONTENT_FIELDS` only.
