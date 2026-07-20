ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf
ARG UV_BASE_IMAGE=ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa

FROM ${UV_BASE_IMAGE} AS uv_runtime
FROM ${PYTHON_BASE_IMAGE}

ARG PYTHON_BASE_IMAGE
ARG UV_BASE_IMAGE
ARG AUTHORITY_MANIFEST_SHA256
ARG AUTHORITY_CONTENT_SHA256
ARG DATA_MANIFEST_SHA256
ARG DATA_CONTENT_SHA256
ARG DOCKERFILE_SHA256
ARG CONTRACT_WRITER_SHA256
ARG VERIFIER_LOCK_SHA256

COPY --from=uv_runtime /uv /uvx /usr/local/bin/

WORKDIR /opt/f4-runtime
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-editable

COPY --from=authority / /opt/xinao-authority/
COPY Dockerfile write_execution_contract.py /opt/f4-metadata/
RUN /opt/f4-runtime/.venv/bin/python -I \
      /opt/xinao-authority/scripts/run_f4_snapshot_stage0.py dependency-smoke \
      > /opt/f4-metadata/dependency_import_smoke.json
RUN /opt/f4-runtime/.venv/bin/python -I /opt/f4-metadata/write_execution_contract.py \
      --output /opt/f4-metadata/execution_contract.json \
      --authority-manifest-sha256 "${AUTHORITY_MANIFEST_SHA256}" \
      --authority-content-sha256 "${AUTHORITY_CONTENT_SHA256}" \
      --data-manifest-sha256 "${DATA_MANIFEST_SHA256}" \
      --data-content-sha256 "${DATA_CONTENT_SHA256}" \
      --dockerfile-sha256 "${DOCKERFILE_SHA256}" \
      --contract-writer-sha256 "${CONTRACT_WRITER_SHA256}" \
      --verifier-lock-sha256 "${VERIFIER_LOCK_SHA256}" \
      --python-base-image "${PYTHON_BASE_IMAGE}" \
      --uv-base-image "${UV_BASE_IMAGE}"

RUN mkdir -p /work && chmod 0555 /work /opt/f4-runtime /opt/xinao-authority /opt/f4-metadata

ENV PATH="/opt/f4-runtime/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONUTF8=1 \
    TZ=UTC

LABEL org.opencontainers.image.title="XINAO F4 isolated verifier" \
      io.xinao.f4.authority.manifest.sha256="${AUTHORITY_MANIFEST_SHA256}" \
      io.xinao.f4.authority.content.sha256="${AUTHORITY_CONTENT_SHA256}" \
      io.xinao.f4.data.manifest.sha256="${DATA_MANIFEST_SHA256}" \
      io.xinao.f4.data.content.sha256="${DATA_CONTENT_SHA256}" \
      io.xinao.f4.dockerfile.sha256="${DOCKERFILE_SHA256}" \
      io.xinao.f4.contract-writer.sha256="${CONTRACT_WRITER_SHA256}" \
      io.xinao.f4.verifier-lock.sha256="${VERIFIER_LOCK_SHA256}"

USER 65532:65532
WORKDIR /work
ENTRYPOINT ["/opt/f4-runtime/.venv/bin/python", "-I", "/opt/xinao-authority/scripts/run_f4_snapshot_stage0.py"]
CMD ["run"]
