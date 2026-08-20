FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
COPY config ./config
COPY catalog-search-terms.json ./
ENTRYPOINT ["uv", "run", "atlas-data", "pipeline", "discover"]
