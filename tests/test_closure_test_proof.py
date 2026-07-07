from services.agent_runtime.closure_test_proof import hello

def test_closure_test_proof_hello() -> None:
    assert hello() == "closure_ok"
