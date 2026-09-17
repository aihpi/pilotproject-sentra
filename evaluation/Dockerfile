# The evaluation harness. Its own image, beside SENTRA's rather than derived
# from it: it depends on nothing of SENTRA's and reaches it over HTTP.
#
# No libgl1, no docling, no qdrant-client. This process reads answers SENTRA
# has already produced.

FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Dependencies first, as their own layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md .
COPY alembic.ini .
COPY src/ src/

RUN uv sync --frozen --no-dev

# The schema is applied deliberately, not at startup: a process that migrates
# when it boots decides the schema by whichever replica won the race.
#   docker compose --profile eval run --rm eval-harness uv run alembic upgrade head
CMD ["uv", "run", "uvicorn", "sentra_eval.app:app", "--host", "0.0.0.0", "--port", "8100"]
