# XINAO integrated_bus worker — Temporal LangGraphPlugin spine (unchanged logic)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XINAO_RESEARCH_RUNTIME=/evidence \
    XINAO_CODEX_S_REPO_ROOT=/app \
    PYTHONPATH=/app:/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md* ./
COPY src ./src
COPY services ./services
COPY materials ./materials
COPY scripts ./scripts
COPY tests ./tests

# bus validation needs pytest (slice), instructor/fastmcp (L1/L3 probes). Bake into image so
# recreate does not lose runtime pip installs.
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --extra workflow --no-dev \
    && uv pip install "markitdown[all]" pytest pytest-cov pytest-json-report diff-cover instructor fastmcp duckdb watchdog GitPython litellm "langfuse>=2.60,<3" crawl4ai

# L8 token stack CLIs — RTK (Rust Token Killer) + caveman-compress stdin shim.
ENV RTK_INSTALL_DIR=/usr/local/bin
RUN curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh \
    && test -x /usr/local/bin/rtk \
    && /usr/local/bin/rtk --version
RUN install -d /usr/local/bin \
    && printf '%s\n' '#!/usr/bin/env sh' 'exec python /app/scripts/l8/caveman_compress_stdin.py "$@"' > /usr/local/bin/caveman-compress \
    && chmod 0755 /usr/local/bin/caveman-compress \
    && git clone --depth 1 https://github.com/JuliusBrussee/caveman.git /opt/caveman \
    && printf '%s\n' '#!/usr/bin/env sh' 'exec node /opt/caveman/bin/install.js "$@"' > /usr/local/bin/caveman \
    && chmod 0755 /usr/local/bin/caveman /opt/caveman/bin/install.js \
    && command -v rtk \
    && command -v caveman-compress \
    && command -v caveman

# Git init so L5 diff_cover + finalize commit_hash work inside /app (separate RUN — never || true the sync).
RUN git config --global user.email "houtai-gongren@local" \
    && git config --global user.name "后台工人" \
    && git init \
    && git add -A \
    && (git -c commit.gpgsign=false commit -m "后台工人镜像烘焙" \
        || git -c commit.gpgsign=false commit -m "后台工人镜像烘焙" --allow-empty)

ENV PATH="/app/.venv/bin:${PATH}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD test -f /evidence/state/integrated_bus_worker_daemon/latest.json || exit 1

# samples-aligned worker shell: Client.connect(TEMPORAL_ADDRESS) → LangGraphPlugin → Worker (see
# langgraph_plugin/graph_api/react_agent/run_worker.py). Address from compose env, not CMD args.
CMD ["python", "-m", "services.agent_runtime.integrated_bus_worker_daemon", \
     "--runtime-root", "/evidence"]