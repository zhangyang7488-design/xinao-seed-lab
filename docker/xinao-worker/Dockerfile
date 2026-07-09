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
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md* ./
COPY src ./src
COPY services ./services
COPY materials ./materials
COPY tests ./tests

# bus validation needs pytest (slice), instructor/fastmcp (L1/L3 probes). Bake into image so
# recreate does not lose runtime pip installs. Git init so finalize can write commit_hash.
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --extra workflow --no-dev \
    && uv pip install "markitdown[all]" pytest instructor fastmcp \
    && git config --global user.email "xinao-worker@local" \
    && git config --global user.name "xinao-worker" \
    && git init \
    && git add -A \
    && git -c commit.gpgsign=false commit -m "xinao-worker image bake" \
    || true

ENV PATH="/app/.venv/bin:${PATH}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD test -f /evidence/state/integrated_bus_worker_daemon/latest.json || exit 1

CMD ["python", "-m", "services.agent_runtime.integrated_bus_worker_daemon", \
     "--address", "temporal:7233", "--runtime-root", "/evidence"]