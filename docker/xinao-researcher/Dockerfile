ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

FROM ${PYTHON_BASE_IMAGE}

ARG GROK_DONOR_IMAGE_ID
ARG GROK_DONOR_BINARY_SHA256
ARG CHARTER_SHA256
ARG OUTPUT_SCHEMA_SHA256
ARG MATERIAL_BUNDLE_SCHEMA_SHA256
ARG RUNTIME_LOCK_SHA256
ARG SKILL_INVOKER_SHA256
ARG DOCKERFILE_SHA256
ARG ENTRYPOINT_SHA256
ARG SOURCE_IDENTITY_SHA256
ARG REQUESTED_MODEL=grok-4.5

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0555 /opt/xinao-researcher /work

# Grok binary is extracted once from the lock-pinned donor image Id via a never-started
# temporary container into an owned host staging context. There is no donor FROM stage and
# no mutable-tag re-resolution at build time (SP-B-001).
COPY donor-artifacts/grok /usr/local/bin/grok
COPY --chmod=0555 docker/xinao-researcher/entrypoint.py /opt/xinao-researcher/entrypoint.py
RUN printf '%s  %s\n' "${GROK_DONOR_BINARY_SHA256}" /usr/local/bin/grok \
    | sha256sum --check --strict - \
    && printf '%s  %s\n' "${ENTRYPOINT_SHA256}" /opt/xinao-researcher/entrypoint.py \
    | sha256sum --check --strict - \
    && test "${REQUESTED_MODEL}" = "grok-4.5" \
    && chmod 0555 /usr/local/bin/grok \
    && /usr/local/bin/grok version

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HOME=/grok-home \
    GROK_HOME=/grok-home \
    XINAO_RESEARCHER_ENTRYPOINT_SHA256=${ENTRYPOINT_SHA256}

LABEL org.opencontainers.image.title="XINAO dedicated scientific researcher" \
      io.xinao.researcher.chain="dedicated-xinao-science" \
      io.xinao.researcher.generic-worker-route="forbidden" \
      io.xinao.researcher.grok-donor-image-id="${GROK_DONOR_IMAGE_ID}" \
      io.xinao.researcher.grok-donor-binary.sha256="${GROK_DONOR_BINARY_SHA256}" \
      io.xinao.researcher.charter.sha256="${CHARTER_SHA256}" \
      io.xinao.researcher.output-schema.sha256="${OUTPUT_SCHEMA_SHA256}" \
      io.xinao.researcher.material-bundle-schema.sha256="${MATERIAL_BUNDLE_SCHEMA_SHA256}" \
      io.xinao.researcher.runtime-lock.sha256="${RUNTIME_LOCK_SHA256}" \
      io.xinao.researcher.skill-invoker.sha256="${SKILL_INVOKER_SHA256}" \
      io.xinao.researcher.dockerfile.sha256="${DOCKERFILE_SHA256}" \
      io.xinao.researcher.entrypoint.sha256="${ENTRYPOINT_SHA256}" \
      io.xinao.researcher.source-identity.sha256="${SOURCE_IDENTITY_SHA256}" \
      io.xinao.researcher.requested-model="${REQUESTED_MODEL}"

WORKDIR /work
ENTRYPOINT ["python", "-I", "/opt/xinao-researcher/entrypoint.py"]
