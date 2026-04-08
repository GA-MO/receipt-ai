FROM python:3.12-slim

WORKDIR /app

# Install uv for faster package installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY app/ app/

RUN mkdir -p data uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
