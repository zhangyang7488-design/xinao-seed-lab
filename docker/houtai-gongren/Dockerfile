# XINAO integrated_bus worker — Temporal + LangGraphPlugin main route
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf
COPY --from=ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_HTTP_TIMEOUT=120 \
    UV_LINK_MODE=copy \
    XINAO_RESEARCH_RUNTIME=/evidence \
    XINAO_CODEX_S_REPO_ROOT=/app \
    PYTHONPATH=/app:/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Official Grok Build CLI: exact cross-platform version, copied out of the
# installer HOME so the runtime credential bind cannot hide the executable.
ARG GROK_CLI_VERSION=0.2.101
RUN set -eu; \
    export HOME=/opt/grok-installer GROK_BIN_DIR=/opt/grok-installer/bin; \
    mkdir -p "$HOME" "$GROK_BIN_DIR"; \
    curl -fsSL https://x.ai/cli/install.sh | bash -s "${GROK_CLI_VERSION}"; \
    install -m 0755 "$(readlink -f "$GROK_BIN_DIR/grok")" /usr/local/bin/grok; \
    rm -rf "$HOME"; \
    /usr/local/bin/grok version

ENV OPA_VERSION=1.0.0
RUN curl -fsSL -o /usr/local/bin/opa \
    "https://openpolicyagent.org/downloads/v${OPA_VERSION}/opa_linux_amd64_static" \
    && chmod 0755 /usr/local/bin/opa \
    && opa version

COPY pyproject.toml uv.lock README.md* ./
COPY xinao_discovery/pyproject.toml xinao_discovery/README.md ./xinao_discovery/
COPY xinao_discovery/src ./xinao_discovery/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra workflow --no-dev \
    && uv pip install "markitdown[all]" pytest pytest-cov pytest-json-report diff-cover \
       instructor fastmcp duckdb watchdog GitPython litellm "langfuse>=2.60,<3" \
       crawl4ai opentelemetry-sdk optuna "dvc>=3"

COPY services ./services
COPY materials ./materials
COPY policies ./policies
COPY scripts ./scripts
COPY tests ./tests

ARG RTK_VERSION=v0.43.0
ENV RTK_INSTALL_DIR=/usr/local/bin \
    RTK_VERSION=${RTK_VERSION}
RUN curl -fsSL "https://raw.githubusercontent.com/rtk-ai/rtk/${RTK_VERSION}/install.sh" | sh \
    && test -x /usr/local/bin/rtk \
    && /usr/local/bin/rtk --version
ARG CAVEMAN_COMMIT=0d95a81d35a9f2d123a5e9430d1cfc43d55f1bb0
RUN install -d /usr/local/bin \
    && printf '%s\n' '#!/usr/bin/env sh' 'exec python /app/scripts/l8/caveman_compress_stdin.py "$@"' > /usr/local/bin/caveman-compress \
    && chmod 0755 /usr/local/bin/caveman-compress \
    && git init /opt/caveman \
    && git -C /opt/caveman remote add origin https://github.com/JuliusBrussee/caveman.git \
    && git -C /opt/caveman fetch --depth 1 origin "${CAVEMAN_COMMIT}" \
    && git -C /opt/caveman checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/caveman rev-parse HEAD)" = "${CAVEMAN_COMMIT}" \
    && printf '%s\n' '#!/usr/bin/env sh' 'exec node /opt/caveman/bin/install.js "$@"' > /usr/local/bin/caveman \
    && chmod 0755 /usr/local/bin/caveman /opt/caveman/bin/install.js \
    && command -v rtk \
    && command -v caveman-compress \
    && command -v caveman

# Image-only Git baseline for diff-cover and read-only GitPython snapshots.
# Runtime finalize never stages or commits the mounted S worktree.
RUN git config --global user.email "houtai-gongren@local" \
    && git config --global user.name "后台工人" \
    && git init \
    && git add -A \
    && (git -c commit.gpgsign=false commit -m "后台工人镜像基线" \
        || git -c commit.gpgsign=false commit -m "后台工人镜像基线" --allow-empty)

ENV PATH="/app/.venv/bin:${PATH}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD test -f /evidence/state/integrated_bus_worker_daemon/latest.json || exit 1

CMD ["python", "-m", "services.agent_runtime.integrated_bus_worker_daemon", \
     "--runtime-root", "/evidence"]
