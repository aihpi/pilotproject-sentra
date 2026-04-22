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
COPY src/ src/

# Install the project itself
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "uvicorn", "sentra.main:app", "--host", "0.0.0.0", "--port", "8000"]
