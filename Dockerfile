FROM python:3.12-slim

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files and project files needed for install (readme, scripts, src)
COPY pyproject.toml poetry.lock ./
COPY README.md ./
COPY scripts/ ./scripts/
COPY src/ ./src/

# Install dependencies and the project (no dev group). torch comes from pytorch-cpu source in pyproject.toml
RUN poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi

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
