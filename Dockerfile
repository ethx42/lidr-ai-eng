# syntax=docker/dockerfile:1
# AI service. Every stage uses the same base image: the venv's interpreter path must match at runtime.
FROM python:3.12-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS deps
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Local development only (compose.dev.yaml): dev dependencies and reload; runs as root so compose watch
# can sync into /app/app.
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim-trixie AS runtime
RUN groupadd --system --gid 999 nonroot && useradd --system --gid 999 --uid 999 --create-home nonroot
WORKDIR /app
COPY --from=deps --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --chown=nonroot:nonroot app ./app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER nonroot
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "30"]
