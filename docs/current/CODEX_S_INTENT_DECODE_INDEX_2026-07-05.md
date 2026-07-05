# Codex S intent decode index

SENTINEL:CODEX_S_INTENT_DECODE_INDEX_20260705

Role: short reference index only. Not L0, not a completion gate, not an execution controller.

## Foreground Mirror Watch

Match: 轮询 / 盯后台 / 监工 / 后台镜像 / 看后台 / 不要停 / watch backend / keep watching.

Decode: 当前前台 Codex turn 进入 live watch；333 后台耐久事务还活时默认镜像轮询/监工；后台活或仍有 backlog/source gap/next frontier/blocker 时不 final，只短中文心跳 + poll/kick/resume。

Default when: 333 durable backend evidence still active.

Exit only when: explicit user stop; explicit one-shot explanation request; terminal clean backend; hard blocker requiring user decision.

Source reference: `C:\Users\xx363\Desktop\前台长watch_后台镜像语义.txt`

Legacy filename alias: `C:\Users\xx363\Desktop\前台长watch_后台镜像语义_旧仓库搜索与S挂载建议_20260704.txt`

Execution owner remains: RootIntentLoop / S Default Dynamic Loop / Temporal worker pool.

## Default Durable Transaction

后台耐久事务 / 333 / 默认主链 / 默认主路 = RootIntentLoop / S Default Dynamic Loop.

It is not rescue, report, latest.json, or a worker lane.

## Dialogue Boundary

human_dialogue / diagnosis: answer or analyze directly; do not start 333 and do not manufacture worker evidence.

## Fake Completion Surfaces

Stop / final / report / PASS / readback / latest.json cannot claim completion.

If a text/worker/readback says incomplete / missing / next step, anchor it as next dispatch/repair/bind work; do not stop at a report.

SENTINEL:XINAO_CODEX_S_INTENT_DECODE_INDEX_READY
