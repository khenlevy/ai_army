FROM python:3.12-slim

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies (no dev group)
RUN poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi

# Copy application source
COPY src/ ./src/

# Entrypoint: copy .env.production -> .env so app uses prod config when run with --env-file or mount
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Create non-root user
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

# At runtime: mount .env.production or use --env-file .env.production; entrypoint copies to .env for app
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["ai-army", "schedule"]
