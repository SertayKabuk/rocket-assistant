# syntax=docker/dockerfile:1.7

# Both images are Debian 13 (trixie), so a binary compiled in the Rust image runs in the Python image.
ARG PYTHON_IMAGE=python:3.14-slim-trixie
ARG RUST_IMAGE=rust:1.99-slim-trixie
ARG RRROCKET_VERSION=0.11.7
# Note: don't declare `ARG TARGETARCH` here; BuildKit fills it in automatically and redeclaring it blanks it.

# --- rrrocket replay parser ---
# amd64: upstream's prebuilt static binary, verified by checksum.
FROM ${PYTHON_IMAGE} AS rrrocket-amd64
ARG RRROCKET_VERSION
ARG RRROCKET_SHA256=39261f3e9707160cdcf01853fe41185b09a55f406fd7564a6e01988d77a82834
ADD --checksum=sha256:${RRROCKET_SHA256} \
    https://github.com/nickbabcock/rrrocket/releases/download/v${RRROCKET_VERSION}/rrrocket-${RRROCKET_VERSION}-x86_64-unknown-linux-musl.tar.gz \
    /tmp/rrrocket.tar.gz
RUN tar -xzf /tmp/rrrocket.tar.gz -C /tmp \
    && install -m 0755 /tmp/rrrocket-${RRROCKET_VERSION}-x86_64-unknown-linux-musl/rrrocket /usr/local/bin/rrrocket

# arm64: upstream publishes no Linux arm64 binary (and isn't on crates.io), so build the
# release commit from source. Keep RRROCKET_COMMIT in sync with RRROCKET_VERSION's tag.
FROM ${RUST_IMAGE} AS rrrocket-arm64
ARG RRROCKET_COMMIT=21444db98174267c177e01a5c43f0d227395246d
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    cargo install --locked --root /opt/rrrocket \
        --git https://github.com/nickbabcock/rrrocket --rev ${RRROCKET_COMMIT} rrrocket \
    && install -m 0755 /opt/rrrocket/bin/rrrocket /usr/local/bin/rrrocket

FROM rrrocket-${TARGETARCH} AS rrrocket

# --- Python dependencies and app, installed into a venv with uv ---
FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so they're cached across code changes
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- Runtime ---
FROM ${PYTHON_IMAGE}
RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir /data && chown app /data
COPY --from=rrrocket /usr/local/bin/rrrocket /usr/local/bin/rrrocket
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RRROCKET=/usr/local/bin/rrrocket \
    ROCKET_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8765
USER app
WORKDIR /app
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/stats', timeout=3)"
CMD ["rocket-assistant", "serve", "--no-browser"]
