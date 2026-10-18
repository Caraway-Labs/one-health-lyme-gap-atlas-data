FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY docs/contracts/intelligence/v1 ./docs/contracts/intelligence/v1
COPY docs/contracts/intelligence/v2 ./docs/contracts/intelligence/v2
COPY docs/contracts/semantic-domain/cdc-2025 ./docs/contracts/semantic-domain/cdc-2025
COPY docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json ./docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json
COPY docs/contracts/semantic-release/release-completeness-2026-10-18.json ./docs/contracts/semantic-release/release-completeness-2026-10-18.json
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --extra pipeline
COPY config ./config
COPY dbt ./dbt
COPY catalog-search-terms.json ./
# DEV-only transactional fixture proof executes with the real job identity.
COPY scripts/verify_cdc_policy_dev.py ./scripts/verify_cdc_policy_dev.py
COPY scripts/verify_historical_cdc_dev.py ./scripts/verify_historical_cdc_dev.py
COPY scripts/run_release_integrity_fixture.py scripts/release_integrity_fixture_seed.py scripts/release_integrity_fixture_matrix.py scripts/release_integrity_fixture_inventory.py scripts/prepare_release_integrity_dev_plan.py scripts/publish_surveillance_situations.py ./scripts/
COPY migrations ./migrations
# App Platform replaces Docker CMD with each job's run_command.  Use the
# environment created during the image build; do not re-sync dependencies when
# a short-lived job starts.
CMD ["/app/.venv/bin/atlas-data", "pipeline", "discover"]
