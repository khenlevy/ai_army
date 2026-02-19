FROM python:3.12-slim

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies (no dev)
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Copy application source
COPY src/ ./src/

# Create non-root user
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

# Env vars (ANTHROPIC_API_KEY, GITHUB_TOKEN, etc.) must be passed at runtime
# e.g. docker run --env-file .env.production ...
CMD ["ai-army", "schedule"]
