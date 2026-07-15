# Codex TUI mouse experience 0.144.4

This directory is the durable source and recovery package for the locally compiled Codex input
experience. `xinao-seed-lab` owns this package; `openai/codex` is source provenance only and is not
the delivery remote.

The normal Codex 0.144.4 runtime is preserved. The only enabled interaction differences are:

- click positioning, drag selection, Delete or Backspace, and typing replacement in the composer;
- transcript drag selection with immediate exact clipboard copy and a short `Copied!` notice.

Models, `CODEX_HOME`, config, skills, plugins, apps, MCP servers, memories, goals, agents,
permissions, and session behavior continue to use the normal local Codex sources.

## Versioned contents

- `source/codex-tui-mouse-experience-0.144.4.bundle` contains a self-contained two-commit recovery
  history whose final tree exactly matches the committed feature source.
- `launcher/Open-Codex-S-Input-Canary.ps1` is the exact hash-pinned local launcher without secrets.
- `launcher/windows-terminal-profile.json` is the independent elevated Terminal profile fragment.
- `artifact-manifest.json` records source, runtime, symbol, launcher, cache, and test identities.

Large compiled files are deliberately kept in the local D/E artifact stores instead of Git. This
repository records their exact SHA-256 identities and the self-contained source needed to rebuild
them.

## Zero-build local recovery

The active runtime is:

`D:\XINAO_RESEARCH_RUNTIME\tools\codex-input-canary\0.144.4-20260716-84ff17ae-app-mouse-final`

The complete cold copy, including EXE, PDB, launcher backup, source ZIP, Git bundle, and patch, is:

`E:\XINAO_EXTERNAL_SOURCES\archives\codex-tui-mouse-experience\0.144.4-7774391`

The 41.54 GiB Cargo release and incremental cache remains at:

`E:\XINAO_EXTERNAL_SOURCES\openai-codex-0.144.4-grok-mouse\codex-rs\target`

The desktop entry is `C:\Users\xx363\Desktop\Codex 输入框试验版.lnk`. It starts the complete
compiled TUI through the same elevated Hardmode, `CODEX_HOME`, work directory, model configuration,
and capability sources as the normal Codex entry.

## Restore the source

```powershell
git clone --no-checkout source/codex-tui-mouse-experience-0.144.4.bundle restored-codex
git -C restored-codex config core.longpaths true
git -C restored-codex switch recovery/codex-tui-mouse-experience-0.144.4
```

The synthetic recovery history is intentional: the original source checkout was shallow and its
tag commit referenced an unavailable parent. A bundle made directly from that checkout passed
`git bundle verify` but failed an independent clone. The packaged recovery branch was fresh-cloned
on Windows and verified clean with the exact final tree hash.

## Carry forward to a new Codex version

1. Start from the required `rust-vX.Y.Z` tag.
2. Fetch the recovery branch from the bundle and cherry-pick recovery commit
   `14702e9e7d17ed130c82d1db68fc7e8c7be256ea`; resolve only `codex-rs/tui/src` and never copy the
   old `Cargo.lock`.
3. Reuse the existing Cargo cache, run the mouse and output-view tests, then the full TUI suite.
4. Run `just fix -p codex-tui` and `just fmt` after tests.
5. Build `codex-tui` and `codex-code-mode-host` sequentially, copy them into a new versioned D:
   directory, hash-pin the launcher, and rerun the real desktop interaction canary.

## Verified completion evidence

- focused mouse tests: 9 passed, 0 failed;
- output-view tests: 7 passed, 0 failed;
- full TUI suite: 2968 passed, 23 unrelated release-version or Windows home-path baseline failures,
  and 0 mouse-feature failures;
- real desktop route: elevated candidate, correct work directory and launch arguments, then clean
  window/process teardown;
- real UI: input drag-delete produced `01GHIJ`, transcript copy matched the exact sentinel, and the
  `Copied!` notice appeared within 400 ms.

Machine evidence remains under
`D:\XINAO_RESEARCH_RUNTIME\evidence\codex-app-mouse-final-20260716-84ff17ae`.
