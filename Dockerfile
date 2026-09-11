FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --extra pipeline
COPY config ./config
COPY dbt ./dbt
COPY catalog-search-terms.json ./
# DEV-only transactional fixture proof executes with the real job identity.
COPY scripts/verify_cdc_policy_dev.py ./scripts/verify_cdc_policy_dev.py
COPY scripts/verify_historical_cdc_dev.py ./scripts/verify_historical_cdc_dev.py
COPY migrations ./migrations
# App Platform replaces Docker CMD with each job's run_command.  Use the
# environment created during the image build; do not re-sync dependencies when
# a short-lived job starts.
CMD ["/app/.venv/bin/atlas-data", "pipeline", "discover"]
