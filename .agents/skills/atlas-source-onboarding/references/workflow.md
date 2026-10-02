# Authoritative reference index

Resolve paths from the repository root; run `uv run python scripts/check_agent_context.py`.

- `docs/operations/agent-context.md`: context classifications and portable references.
- `docs/operations/operation-capabilities-v1.md` and `config/operation-capabilities-v1.yml`: bounded desired operation contracts; not live facts.
- `docs/operations/connection-inventory.md` and `docs/adr/0030-snowflake-role-model-simplification.md`: identity and authority mapping.
- `docs/contracts/catalog-to-snowflake/operating-model.md`, `docs/contracts/simplified-ingestion/interface-freeze.md`, `docs/operations/simplified-ingestion-migration.md`: source tiers and existing commands.
- `docs/operations/deployment-promotion.md`, `docs/contracts/semantic-release/`: protected release and bootstrap prerequisites.
- `src/lyme_gap_atlas_data/migrations.py`, `migrations/`: executable checksum truth and forward recovery.
- `docs/delivery/handoff-v1.schema.json`, `scripts/validate_handoff.py`: evidence handoff validation.
- `docs/delivery/data374-recipes.md`: boundary-specific recipe verification and known gaps.

Read only references relevant to the current task. DATA372 snapshots and DATA376
failure packets have separate owners; use their finalized references after integration.
