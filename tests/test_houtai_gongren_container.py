from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_worker_image_uses_pinned_official_uv_and_cache_layer() -> None:
    text = (REPO / "docker/houtai-gongren/Dockerfile").read_text(encoding="utf-8")
    assert "ghcr.io/astral-sh/uv@sha256:0f36cb9361a334" in text
    assert "--mount=type=cache,target=/root/.cache/uv" in text
    assert "pip install --no-cache-dir uv" not in text


def test_worker_image_has_fail_closed_unprivileged_bwrap_boundary() -> None:
    dockerfile = (REPO / "docker/houtai-gongren/Dockerfile").read_text(encoding="utf-8")
    wrapper = (REPO / "docker/houtai-gongren/grok-bwrap-unprivileged-wrapper.sh").read_text(
        encoding="utf-8"
    )
    entrypoint = (REPO / "docker/houtai-gongren/grok-container-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    tool_shell = (REPO / "docker/houtai-gongren/grok-tool-shell-wrapper.sh").read_text(
        encoding="utf-8"
    )
    assert "bubblewrap" in dockerfile
    assert "ARG GROK_CLI_VERSION=0.2.117" in dockerfile
    assert 'test "$parsed" = "${GROK_CLI_VERSION}"' in dockerfile
    # Version probe may recreate installer-home residue; final image must scrub it.
    assert "rm -rf /opt/grok-installer" in dockerfile
    probe_idx = dockerfile.index('test "$parsed" = "${GROK_CLI_VERSION}"')
    scrub_idx = dockerfile.index("rm -rf /opt/grok-installer", probe_idx)
    assert scrub_idx > probe_idx
    assert "mv /usr/bin/bwrap /usr/libexec/xinao/bwrap-real" in dockerfile
    assert "grok-bwrap-unprivileged-wrapper.sh /usr/bin/bwrap" in dockerfile
    assert "expected_caps=00000000000000c0" in wrapper
    assert "NoNewPrivs:" in wrapper
    assert '--reuid="$tool_uid"' in wrapper
    assert '--regid="$tool_gid"' in wrapper
    assert "tool_uid=65532" in wrapper
    assert "grok-container-entrypoint.sh /usr/local/bin/xinao-grok-entrypoint" in dockerfile
    assert "install -m 0644 /inputs/transport-sandbox.toml" in entrypoint
    assert ': > "$GROK_HOME/hooks-paths"' in entrypoint
    assert 'exec /usr/local/bin/grok "$@"' in entrypoint
    assert "grok-tool-shell-wrapper.sh /usr/libexec/xinao/grok-tool-shell-wrapper" in dockerfile
    assert "mv /usr/bin/bash /usr/libexec/xinao/bash-real" in dockerfile
    assert "empty-grok-profile" in dockerfile
    assert "expected_caps=00000000000000c0" in tool_shell
    assert "tool_uid=65532" in tool_shell
    assert "grok_home=/grok-home/.grok" in tool_shell
    assert '--ro-bind "$empty_profile" "$grok_home"' in tool_shell
    assert "--bind /workspace /workspace" in tool_shell
    assert '--reuid="$tool_uid"' in tool_shell


def test_houtai_gongren_build_surfaces_are_lf_and_gitattributes_pinned() -> None:
    """Windows donor rebuild requires LF materialization of houtai-gongren build surfaces."""
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "docker/houtai-gongren/** text eol=lf" in attrs
    for rel in (
        "docker/houtai-gongren/Dockerfile",
        "docker/houtai-gongren/grok-bwrap-unprivileged-wrapper.sh",
        "docker/houtai-gongren/grok-container-entrypoint.sh",
        "docker/houtai-gongren/grok-tool-shell-wrapper.sh",
    ):
        raw = (REPO / rel).read_bytes()
        assert b"\r" not in raw, rel
