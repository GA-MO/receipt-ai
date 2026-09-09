FROM python:3.12-slim

WORKDIR /app

# Install uv for faster package installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY app/ app/
# alembic/ and alembic.ini were missing: without them the container could only
# ever create a schema from the models, never migrate one that already holds
# the boss's test data.
COPY alembic/ alembic/
COPY alembic.ini ./
COPY scripts/ scripts/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p data uploads && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
