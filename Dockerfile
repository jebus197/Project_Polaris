FROM python:3.13-slim

LABEL org.opencontainers.image.title="Project Genesis"
LABEL org.opencontainers.image.description="Governance-first trust infrastructure"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY config/ ./config/
COPY tools/ ./tools/
COPY tests/ ./tests/

# Install the package
RUN pip install --no-cache-dir -e ".[dev]"

# Verify installation
RUN python -m pytest tests/ -q --tb=short

# Default: run invariant checks
CMD ["python", "-m", "genesis.cli", "check-invariants"]
