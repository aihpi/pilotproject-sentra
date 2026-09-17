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
# --no-dev matters here as much as in the sync above. `uv run` re-resolves the
# environment before running and includes the dev group by default, so without
# it every container start downloaded ruff, mypy and pytest — undoing the
# --no-dev from the build layer, requiring network access to the package index
# to start an image that was already on the host, and putting development
# tooling in a production image.
CMD ["uv", "run", "--no-dev", "uvicorn", "sentra_eval.app:app", "--host", "0.0.0.0", "--port", "8100"]
