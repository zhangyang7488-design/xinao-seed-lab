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
ARG SHADOW_RUNTIME_TREE_SHA256
ARG SHADOW_RUNTIME_LOCK_SHA256
ARG RESEARCHER_IMAGE_MODULES_TREE_SHA256
ARG REQUESTED_MODEL=grok-4.5
ARG SHADOW_PYDANTIC_VERSION=2.13.4
ARG SHADOW_RFC8785_VERSION=0.1.4
ARG SHADOW_UUID6_VERSION=2025.0.1

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0555 /opt/xinao-researcher /opt/xinao-shadow /work /usr/libexec/xinao

# Grok binary is extracted once from the lock-pinned donor image Id via a never-started
# temporary container into an owned host staging context. There is no donor FROM stage and
# no mutable-tag re-resolution at build time (SP-B-001).
COPY donor-artifacts/grok /usr/local/bin/grok
# Dual-profile modules: default canary entrypoint + genuine-scientist alternate cone.
COPY --chmod=0555 docker/xinao-researcher/entrypoint.py /opt/xinao-researcher/entrypoint.py
COPY --chmod=0555 docker/xinao-researcher/episode_entrypoint.py /opt/xinao-researcher/episode_entrypoint.py
COPY --chmod=0444 docker/xinao-researcher/episode_boundary.py /opt/xinao-researcher/episode_boundary.py
COPY --chmod=0444 docker/xinao-researcher/episode_events.py /opt/xinao-researcher/episode_events.py
COPY --chmod=0444 docker/xinao-researcher/ipc_contract.py /opt/xinao-researcher/ipc_contract.py
COPY --chmod=0444 docker/xinao-researcher/transport_broker.py /opt/xinao-researcher/transport_broker.py
COPY --chmod=0444 docker/xinao-researcher/episode_mcp_binding.py /opt/xinao-researcher/episode_mcp_binding.py
COPY --chmod=0555 docker/xinao-researcher/mcp_episode_lab_server.py /opt/xinao-researcher/mcp_episode_lab_server.py
# Package-owned pure candidate-manifest validator (exact xinao-discovery source bytes staged).
COPY --chmod=0444 docker/xinao-researcher/research_episode_candidate_manifest.py /opt/xinao-researcher/research_episode_candidate_manifest.py
COPY --chmod=0555 docker/xinao-researcher/grok-bwrap-unprivileged-wrapper.sh /usr/libexec/xinao/grok-bwrap-unprivileged-wrapper
COPY --chmod=0555 docker/xinao-researcher/episode-tool-shell-wrapper.sh /usr/libexec/xinao/episode-tool-shell-wrapper
COPY docker/xinao-researcher/empty-grok-profile/ /opt/xinao-researcher/empty-grok-profile/
# Locked leg-A shadow runtime cone (xinao_discovery subset). Host skill launches it with
# --entrypoint python -I -m xinao.shadow_lifecycle; researcher ENTRYPOINT stays INSTRUMENT_CANARY.
COPY shadow-runtime/ /opt/xinao-shadow/
RUN printf '%s  %s\n' "${GROK_DONOR_BINARY_SHA256}" /usr/local/bin/grok \
    | sha256sum --check --strict - \
    && printf '%s  %s\n' "${ENTRYPOINT_SHA256}" /opt/xinao-researcher/entrypoint.py \
    | sha256sum --check --strict - \
    && test "${REQUESTED_MODEL}" = "grok-4.5" \
    && test -n "${SHADOW_RUNTIME_TREE_SHA256}" \
    && test -n "${SHADOW_RUNTIME_LOCK_SHA256}" \
    && test -n "${RESEARCHER_IMAGE_MODULES_TREE_SHA256}" \
    && chmod 0555 /usr/local/bin/grok \
    && /usr/local/bin/grok version \
    && pip install --no-cache-dir --root-user-action=ignore \
        "pydantic==${SHADOW_PYDANTIC_VERSION}" \
        "rfc8785==${SHADOW_RFC8785_VERSION}" \
        "uuid6==${SHADOW_UUID6_VERSION}" \
    && python -c "import sysconfig; from pathlib import Path; Path(sysconfig.get_paths()['purelib'], 'xinao-shadow.pth').write_text('/opt/xinao-shadow\n', encoding='utf-8')" \
    && python -I -c "import xinao.shadow_lifecycle as m; assert m.CONSUMER_VERSION"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HOME=/grok-home \
    GROK_HOME=/grok-home \
    XINAO_RESEARCHER_ENTRYPOINT_SHA256=${ENTRYPOINT_SHA256} \
    XINAO_SHADOW_RUNTIME_TREE_SHA256=${SHADOW_RUNTIME_TREE_SHA256} \
    XINAO_SHADOW_RUNTIME_LOCK_SHA256=${SHADOW_RUNTIME_LOCK_SHA256} \
    XINAO_RESEARCHER_IMAGE_MODULES_TREE_SHA256=${RESEARCHER_IMAGE_MODULES_TREE_SHA256}

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
      io.xinao.researcher.shadow-runtime.sha256="${SHADOW_RUNTIME_TREE_SHA256}" \
      io.xinao.researcher.shadow-runtime-lock.sha256="${SHADOW_RUNTIME_LOCK_SHA256}" \
      io.xinao.researcher.image-modules.sha256="${RESEARCHER_IMAGE_MODULES_TREE_SHA256}" \
      io.xinao.researcher.requested-model="${REQUESTED_MODEL}" \
      io.xinao.researcher.default-profile="INSTRUMENT_CANARY" \
      io.xinao.researcher.episode-profile="GENUINE_SCIENTIST_EPISODE" \
      io.xinao.researcher.episode-entrypoint="/opt/xinao-researcher/episode_entrypoint.py" \
      io.xinao.researcher.episode-network-policy="DENY_ALL_FAIL_CLOSED" \
      io.xinao.researcher.episode-tool-shell="/usr/libexec/xinao/episode-tool-shell-wrapper" \
      io.xinao.researcher.mcp-server="/opt/xinao-researcher/mcp_episode_lab_server.py" \
      io.xinao.researcher.mcp-tools-allowlist="search_tool,use_tool"

WORKDIR /work
# INSTRUMENT_CANARY remains the sole default ENTRYPOINT (one-shot, tool-free).
ENTRYPOINT ["python", "-I", "/opt/xinao-researcher/entrypoint.py"]
