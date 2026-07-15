# Thin-localization evaluation workspace

This disposable workspace tests whether an agent can bind a mature external implementation while
keeping the local change parameter-only.

- Read `capability_request.json` first.
- Run `uv run python tools/search_candidates.py` before the first mutation.
- Consider every observed source kind. Source identity is evidence, not an admission gate.
- Modify only `config/binding.json`; do not edit the runner, verifier, tools, or input.
- Do not add a local fallback, wrapper runtime, copied implementation, dependency, or new file.
- Pin the observed provider version, then run the canonical path twice and the verifier once.
- Completion requires a real upstream process invocation and a passing swap/lesion report.
