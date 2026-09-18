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
# --extra vorlagen: two small pure-Python packages, so that the operator who
# imports a collection sheet somebody filled in can do it in this container
# rather than needing a checkout. `cli import` accepts .xlsx as well as .yaml,
# and a harness that could not read the format its cases arrive in would push
# a manual conversion step in front of every round.
RUN uv sync --frozen --no-dev --extra vorlagen --no-install-project

COPY README.md .
COPY alembic.ini .
COPY src/ src/

RUN uv sync --frozen --no-dev --extra vorlagen

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
