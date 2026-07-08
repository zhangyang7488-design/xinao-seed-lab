手搓模块归档区。默认热路径不走这里。
verify 马拉松已迁 scripts/_retired/verify_marathon/（2026-07-08 档1）。
档2（2026-07-08）：5 条 live .py 已换成 facade stub，正文在本目录 *_handroll_v1.py。
档2 旁路登记：root_intent / worker_pool / v4pro 仅 archive 副本，live 仍保留委托入口。
task_package_resolver 仍为库模块，未 facade。
L4 rg 工具已抽到 thin_glue_rg_utils.py。
旁路登记见 materials/authority_glue/thin_glue_sunset_registry.v1.json
验收见 scripts/Invoke-XinaoThinGlueFullSmoke.ps1 与 thin-glue-status
仅当 XINAO_THIN_GLUE_*=0 时测试/救急会落回 _retired 手搓正文。