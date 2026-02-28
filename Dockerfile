FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev --no-editable

ADD . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim-bookworm

WORKDIR /app

COPY --from=uv /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
ENV MALLOC_ARENA_MAX=2

ENTRYPOINT ["python", "-m", "arxiv_mcp_server"]
