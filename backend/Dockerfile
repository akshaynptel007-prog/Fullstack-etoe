# syntax=docker/dockerfile:1.7
# One image, three roles: API (default CMD), worker (`python -m app.worker`)
# and migrations (`alembic upgrade head`).

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"
WORKDIR /app

# --- dependencies (cached unless pyproject/uv.lock change) --------------------
FROM base AS deps
COPY --from=ghcr.io/astral-sh/uv:0.9.20 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM deps AS dev-deps
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# --- shared application layer -------------------------------------------------
FROM base AS app
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
RUN chmod 0755 ./scripts/start-api.sh
COPY app ./app

# --- test image: `docker compose --profile test run backend-tests` -------------
FROM app AS test
COPY --from=dev-deps /opt/venv /opt/venv
COPY pyproject.toml ./
COPY tests ./tests
USER app
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

# --- runtime image (default target) -------------------------------------------
FROM app AS runtime
COPY --from=deps /opt/venv /opt/venv
USER app
EXPOSE 8000 9100
STOPSIGNAL SIGTERM
CMD ["/app/scripts/start-api.sh"]
