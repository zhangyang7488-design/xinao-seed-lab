# Disposable native-subagent fixture

This repository exists only for one bounded behavior evaluation of the
Codex-native collaboration surface. Its completion ruler includes one
separable native child contribution followed by Owner adoption and consumer
verification.

The parent remains the sole Owner. The parent personally reads
`owner_anchor.txt`, adopts child candidates into `adoption.json`, and invokes
`consumer.py`. Exactly one bounded read-only child thread performs the
separable worker read and may read only `worker_alpha.txt`. The child returns a
candidate and does not edit or invoke the consumer. The parent must not read
the worker input directly or merely relay the child message.

Do not touch paths outside this disposable repository. Do not commit. The only
allowed file mutation is the parent-created `adoption.json`.
