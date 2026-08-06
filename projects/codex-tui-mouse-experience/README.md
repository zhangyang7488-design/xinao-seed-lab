# Codex TUI mouse experience — frozen recovery index

This project is not an active Codex runtime, launcher, or upgrade route. The
versioned delivery packages were removed from the working tree after their
independent E-drive archives were verified. Git history remains a second
recovery source without keeping large bundles in every checkout.

## Preferred accepted package

- Version: Codex `0.144.5` with Windows Terminal `1.24.11911.0`
- Cold archive:
  `E:\XINAO_EXTERNAL_SOURCES\archives\codex-input-bridge\0.144.5-wt-1.24.11911.0-20260716`
- Historical repository commits: `7a68b44`, `70d8bb1`
- Verified on 2026-08-06:
  - archive manifest and product hashes passed up to the legacy script's
    repository-context-sensitive `git bundle verify` call;
  - independent fresh clones matched Codex HEAD
    `3a7a19df93328b7fa3a098562f951c4e461f9d5c` and tree
    `fa716bda2443b45cbd9e6d46ed2d5f7776075260`;
  - independent fresh clones matched Windows Terminal HEAD
    `2c8d7bf01a734710be366276c23250ac0dd657ce` and tree
    `df29dbf6e6a3c909e715ac3cbbb00a5822780592`.

## Superseded package

- Version: Codex `0.144.4`
- Cold archive:
  `E:\XINAO_EXTERNAL_SOURCES\archives\codex-tui-mouse-experience\0.144.4-7774391`
- Historical repository commit: `6e53e8d`
- Verified on 2026-08-06: an independent fresh clone matched HEAD
  `14702e9e7d17ed130c82d1db68fc7e8c7be256ea` and tree
  `155d7306656583812ffa169f5b0514f49d08e636`.

At closure time neither package had a live process, installed D-drive runtime,
or desktop shortcut consumer. Restoring either package is an explicit,
side-by-side recovery task: verify the cold archive first, never copy account
credentials or sessions, and do not replace the current Codex installation in
place.
