from services.agent_runtime.thin_glue_work_proof import last_run_id


def test_thin_glue_work_proof_has_run_id() -> None:
    assert last_run_id()
