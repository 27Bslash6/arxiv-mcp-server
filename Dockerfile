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

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm curl \
    && npm install -g supergateway \
    && apt-get remove -y npm && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install unpdf Rust binary for PDF-to-Markdown conversion
ARG UNPDF_VERSION=v0.2.1
RUN curl -sL https://github.com/iyulab/unpdf/releases/download/${UNPDF_VERSION}/unpdf-linux-x86_64-v${UNPDF_VERSION#v}.tar.gz \
    | tar xz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/unpdf

WORKDIR /app

COPY --from=uv /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
ENV MALLOC_ARENA_MAX=2

ENTRYPOINT ["supergateway"]
CMD ["--stdio", "python -m arxiv_mcp_server", "--outputTransport", "streamableHttp", "--port", "8000"]
