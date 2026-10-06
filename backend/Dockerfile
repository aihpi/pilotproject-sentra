FROM python:3.12-slim

WORKDIR /app

# System dependencies for Docling PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY README.md .
# The migrations are under src/, but the file that points alembic at them
# is not, and without it `alembic upgrade head` in a container fails with
# "No 'script_location' key found in configuration" (#200).
COPY alembic.ini .
COPY src/ src/

# Install the project itself
RUN uv sync --frozen --no-dev

# --no-dev matters here as much as in the sync above. `uv run` re-resolves the
# environment before running and includes the dev group by default, so without
# it every container start downloaded ruff, mypy and pytest — undoing the
# --no-dev from the build layer, requiring network access to the package index
# to start an image that was already on the host, and putting development
# tooling in a production image.
CMD ["uv", "run", "--no-dev", "uvicorn", "sentra.main:app", "--host", "0.0.0.0", "--port", "8000"]
