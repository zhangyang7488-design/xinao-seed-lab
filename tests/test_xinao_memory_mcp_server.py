from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from services.mcp import local_mem0_store as store
from services.mcp import xinao_memory_mcp_server as server


def _local_config() -> dict[str, Any]:
    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": server.COLLECTION_NAME,
                "path": str(server.MEMORY_ROOT / "qdrant"),
                "on_disk": True,
                "embedding_model_dims": server.EMBEDDING_DIMS,
            },
        },
        "llm": {
            "provider": "ollama",
            "config": {
                "model": server.LLM_MODEL,
                "ollama_base_url": server.OLLAMA_BASE_URL,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": server.EMBEDDER_MODEL,
                "ollama_base_url": server.OLLAMA_BASE_URL,
            },
        },
        "history_db_path": str(server.MEMORY_ROOT / "history.db"),
    }


class FakeMemory:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.history_records: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_id = 1

    def add(
        self,
        text: str,
        *,
        user_id: str,
        run_id: str,
        metadata: dict[str, Any],
        infer: bool,
    ) -> dict[str, Any]:
        memory_id = f"mem-{self.next_id}"
        self.next_id += 1
        self.calls.append(
            (
                "add",
                {
                    "text": text,
                    "user_id": user_id,
                    "run_id": run_id,
                    "metadata": deepcopy(metadata),
                    "infer": infer,
                },
            )
        )
        self.records[memory_id] = {
            "id": memory_id,
            "memory": text,
            "user_id": user_id,
            "run_id": run_id,
            "metadata": deepcopy(metadata),
        }
        return {"results": [{"id": memory_id, "memory": text, "event": "ADD"}]}

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any],
        top_k: int,
        threshold: float,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "search",
                {
                    "query": query,
                    "filters": deepcopy(filters),
                    "top_k": top_k,
                    "threshold": threshold,
                },
            )
        )
        # Deliberately return every record. The MCP boundary must post-filter backend output.
        return {"results": list(deepcopy(self.records).values())}

    def get_all(self, *, filters: dict[str, Any], top_k: int) -> dict[str, Any]:
        self.calls.append(("get_all", {"filters": deepcopy(filters), "top_k": top_k}))
        return {"results": list(deepcopy(self.records).values())}

    def get(self, memory_id: str) -> dict[str, Any] | None:
        self.calls.append(("get", {"memory_id": memory_id}))
        record = self.records.get(memory_id)
        return deepcopy(record) if record is not None else None

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        self.calls.append(("history", {"memory_id": memory_id}))
        return deepcopy(self.history_records.get(memory_id, []))

    def update(
        self,
        memory_id: str,
        *,
        data: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "update",
                {"memory_id": memory_id, "data": data, "metadata": deepcopy(metadata)},
            )
        )
        record = self.records[memory_id]
        if data is not None:
            record["memory"] = data
        record["metadata"].update(deepcopy(metadata))
        return {"message": "Memory updated successfully!"}

    def delete(self, memory_id: str) -> dict[str, Any]:
        self.calls.append(("delete", {"memory_id": memory_id}))
        del self.records[memory_id]
        return {"message": "Memory deleted successfully!"}


@pytest.fixture
def fake_memory(monkeypatch: pytest.MonkeyPatch) -> FakeMemory:
    fake = FakeMemory()
    monkeypatch.setattr(server, "_memory_instance", fake)
    return fake


def _seed_record(
    fake: FakeMemory,
    memory_id: str,
    *,
    user_id: str = "user-a",
    project: str = "project-a",
    scope: str = "private",
    metadata: dict[str, Any] | None = None,
) -> None:
    fake.records[memory_id] = {
        "id": memory_id,
        "memory": f"text for {memory_id}",
        "user_id": user_id,
        "run_id": server._domain_run_id({"user_id": user_id, "project": project, "scope": scope}),
        "metadata": {
            "project": project,
            "scope": scope,
            "provenance": "test fixture",
            "timestamp": "2026-07-10T00:00:00Z",
            **deepcopy(metadata or {}),
        },
    }


def test_generated_config_is_fixed_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert store.build_local_mem0_config(runtime_root=server.RUNTIME_ROOT) == _local_config()

    captured: dict[str, Any] = {}

    def fake_builder(*, runtime_root: Any) -> dict[str, Any]:
        captured["runtime_root"] = runtime_root
        return _local_config()

    monkeypatch.setenv("MEM0_TELEMETRY", "true")
    monkeypatch.setenv("MEM0_DIR", r"C:\outside")
    monkeypatch.setattr(server, "build_local_mem0_config", fake_builder)
    config = server._build_local_config()

    assert config == _local_config()
    assert captured["runtime_root"] == server.RUNTIME_ROOT
    assert server.os.environ["MEM0_TELEMETRY"] == "false"
    assert server.os.environ["MEM0_DIR"] == str(server.MEMORY_ROOT)


def test_remote_generated_config_fails_closed() -> None:
    config = _local_config()
    config["llm"]["config"]["ollama_base_url"] = "http://remote-host:11434"
    with pytest.raises(server.LocalBoundaryError, match="not fixed-local"):
        server._validate_local_config(config)

    config = _local_config()
    config["vector_store"]["config"]["path"] = r"C:\outside\qdrant"
    with pytest.raises(server.LocalBoundaryError, match="outside the fixed local path"):
        server._validate_local_config(config)


def test_memory_session_is_per_operation_and_disables_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []
    closed: list[FakeMemory] = []
    fake = FakeMemory()
    fake_module = types.ModuleType("mem0")

    class Memory:
        @classmethod
        def from_config(cls, config: dict[str, Any]) -> FakeMemory:
            assert server.os.environ["MEM0_TELEMETRY"] == "false"
            assert server.os.environ["MEM0_DIR"] == str(server.MEMORY_ROOT)
            created.append(deepcopy(config))
            return fake

    fake_module.Memory = Memory
    monkeypatch.setitem(sys.modules, "mem0", fake_module)
    monkeypatch.setattr(server, "_memory_instance", None)
    monkeypatch.setattr(server, "build_local_mem0_config", lambda *, runtime_root: _local_config())

    @contextmanager
    def fake_process_lock(runtime_root: Any) -> Any:
        assert runtime_root == server.RUNTIME_ROOT
        yield server.MEMORY_ROOT / ".xinao-memory-operation.lock"

    monkeypatch.setattr(server, "local_mem0_operation_lock", fake_process_lock)
    monkeypatch.setattr(server, "close_local_mem0_memory", lambda memory: closed.append(memory))

    with server._memory_session() as first:
        assert first is fake
    with server._memory_session() as second:
        assert second is fake
    assert created == [_local_config(), _local_config()]
    assert closed == [fake, fake]


def test_explicit_close_releases_qdrant_then_history() -> None:
    closed: list[str] = []
    memory = types.SimpleNamespace(
        vector_store=types.SimpleNamespace(
            client=types.SimpleNamespace(close=lambda: closed.append("qdrant"))
        ),
        close=lambda: closed.append("history"),
    )

    store.close_local_mem0_memory(memory)

    assert closed == ["qdrant", "history"]


def test_preloaded_enabled_mem0_telemetry_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("mem0")

    class Memory:
        @classmethod
        def from_config(cls, config: dict[str, Any]) -> FakeMemory:
            raise AssertionError("from_config must not run with enabled telemetry")

    fake_module.Memory = Memory
    telemetry_module = types.ModuleType("mem0.memory.telemetry")
    telemetry_module.MEM0_TELEMETRY = True
    monkeypatch.setitem(sys.modules, "mem0", fake_module)
    monkeypatch.setitem(sys.modules, "mem0.memory.telemetry", telemetry_module)
    monkeypatch.setattr(server, "build_local_mem0_config", lambda *, runtime_root: _local_config())

    with pytest.raises(server.LocalBoundaryError, match="refusing startup"):
        server._create_memory_instance()


def test_stdio_main_preloads_mem0_before_starting_fastmcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        server,
        "_preload_local_backend_dependencies",
        lambda: calls.append("preload") or True,
    )
    monkeypatch.setattr(server.mcp, "run", lambda transport: calls.append(f"run:{transport}"))

    server.main()

    assert calls == ["preload", "run:stdio"]


def test_backend_preload_is_storage_lazy_and_disables_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = types.ModuleType("mem0")

    class Memory:
        @classmethod
        def from_config(cls, config: dict[str, Any]) -> FakeMemory:
            raise AssertionError("dependency preload must not initialize storage")

    fake_module.Memory = Memory
    monkeypatch.setitem(sys.modules, "mem0", fake_module)
    monkeypatch.delitem(sys.modules, "mem0.memory.telemetry", raising=False)
    monkeypatch.setenv("MEM0_TELEMETRY", "true")
    monkeypatch.setenv("MEM0_DIR", r"C:\outside")

    assert server._preload_local_backend_dependencies() is True
    assert server.os.environ["MEM0_TELEMETRY"] == "false"
    assert server.os.environ["MEM0_DIR"] == str(server.MEMORY_ROOT)


def test_registered_tools_are_explicit_and_have_no_bulk_delete() -> None:
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    names = set(tools)
    assert names == {
        "xinao_memory_status",
        "xinao_memory_search",
        "xinao_memory_list",
        "xinao_memory_get",
        "xinao_memory_history",
        "xinao_memory_add",
        "xinao_memory_remember",
        "xinao_memory_update",
        "xinao_memory_delete",
    }
    assert all("delete_all" not in name for name in names)
    annotations = {
        name: tool.annotations.model_dump(by_alias=True, exclude_none=True)
        for name, tool in tools.items()
    }
    read_only = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    for name in {
        "xinao_memory_status",
        "xinao_memory_search",
        "xinao_memory_list",
        "xinao_memory_get",
        "xinao_memory_history",
    }:
        assert annotations[name] == read_only
    assert annotations["xinao_memory_add"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    assert annotations["xinao_memory_remember"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    assert annotations["xinao_memory_update"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    assert annotations["xinao_memory_delete"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert set(tools["xinao_memory_history"].inputSchema["required"]) == {
        "memory_id",
        "user_id",
        "project",
        "scope",
    }
    managed_properties = tools["xinao_memory_remember"].inputSchema["properties"]
    assert {
        "memory_type",
        "confidence",
        "expires_at",
        "supersedes",
        "source_ref",
        "valid_from",
        "last_verified_at",
        "sensitivity",
    }.issubset(managed_properties)
    server_source = Path(server.__file__).read_text(encoding="utf-8")
    store_source = Path(store.__file__).read_text(encoding="utf-8")
    for source in (server_source, store_source):
        assert "MemoryClient" not in source
        assert "MEM0_API_KEY" not in source
        assert "services.agent_runtime" not in source
        assert "materials" not in source
        assert "chroma" not in source.lower()
    assert 'mcp.run("stdio")' in server_source


def test_status_is_non_initializing_and_does_not_echo_environment_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_memory_instance", None)
    monkeypatch.setattr(
        server,
        "_probe_local_ollama",
        lambda: {"reachable": True, "ready": True, "status_code": 200},
    )
    monkeypatch.setattr(server, "_dependency_available", lambda: True)
    monkeypatch.setenv("UNRELATED_TEST_SECRET", "do-not-echo-this")
    payload = server.xinao_memory_status()
    assert payload["ok"] is True
    assert payload["initialized"] is False
    assert payload["ready"] is True
    assert payload["mem0_oss_mode"] is True
    assert payload["hosted_mem0_enabled"] is False
    assert payload["telemetry_enabled"] is False
    assert payload["multiprocess_safe_access"] is True
    assert payload["backend_lifecycle"] == "per_operation_interprocess_serialized"
    assert payload["operation_lock_timeout_sec"] == 10.0
    assert payload["local_config_ok"] is True
    assert payload["memory_lifecycle"] == {
        "metadata_fields": ["memory_type", "confidence", "expires_at", "supersedes"],
        "supported_memory_types": ["semantic", "episodic", "procedural"],
        "expired_read_default": "exclude",
        "include_expired_override": True,
        "supersedes_semantics": "advisory_memory_id_reference",
        "automatic_expired_deletion": False,
    }
    assert payload["memory_evidence"] == {
        "metadata_fields": ["source_ref", "valid_from", "last_verified_at", "sensitivity"],
        "supported_sensitivities": ["public", "internal", "sensitive"],
        "timestamps_normalized_to_utc": True,
    }
    assert payload["history_read"] == {
        "exposed": True,
        "read_only": True,
        "ownership_gate": "current_record_exact_domain",
        "credential_redaction": True,
        "max_events": 50,
    }
    assert payload["limits"]["max_history_events"] == 50
    assert payload["bulk_delete_exposed"] is False
    assert "do-not-echo-this" not in str(payload)


def test_ollama_probe_uses_only_fixed_loopback_and_required_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeResponse:
        status = 200

        def read(self, limit: int) -> bytes:
            observed["read_limit"] = limit
            return b'{"models":[{"name":"qwen3:8b"},{"model":"nomic-embed-text:latest"}]}'

    class FakeConnection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            observed.update({"host": host, "port": port, "timeout": timeout})

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            observed.update({"method": method, "path": path, "headers": headers})

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(server, "HTTPConnection", FakeConnection)
    probe = server._probe_local_ollama()
    assert probe["ready"] is True
    assert observed == {
        "host": "127.0.0.1",
        "port": 11434,
        "timeout": 1.5,
        "method": "GET",
        "path": "/api/tags",
        "headers": {"Accept": "application/json"},
        "read_limit": 200_001,
        "closed": True,
    }


def test_add_and_remember_attach_domain_metadata(fake_memory: FakeMemory) -> None:
    added = server.xinao_memory_add(
        "User prefers concise answers",
        "user-a",
        "project-a",
        "private",
        "explicit user statement",
        {"confidence": 1.0},
        "2026-07-10T08:30:00+08:00",
    )
    remembered = server.xinao_memory_remember(
        "The workspace uses PowerShell",
        "user-a",
        "project-a",
        "workspace",
        "AGENTS.md",
    )

    assert added["ok"] is True
    assert added["infer"] is True
    assert added["record_timestamp"] == "2026-07-10T00:30:00Z"
    assert remembered["ok"] is True
    assert remembered["infer"] is False

    first = fake_memory.calls[0][1]
    assert first["user_id"] == "user-a"
    assert first["run_id"] == server._domain_run_id(
        {"user_id": "user-a", "project": "project-a", "scope": "private"}
    )
    assert first["metadata"] == {
        "confidence": 1.0,
        "user_id": "user-a",
        "run_id": server._domain_run_id(
            {"user_id": "user-a", "project": "project-a", "scope": "private"}
        ),
        "project": "project-a",
        "scope": "private",
        "provenance": "explicit user statement",
        "timestamp": "2026-07-10T00:30:00Z",
    }
    assert fake_memory.calls[1][1]["infer"] is False


def test_managed_fields_are_normalized_into_metadata(fake_memory: FakeMemory) -> None:
    payload = server.xinao_memory_remember(
        "A corrected preference",
        "user-a",
        "project-a",
        "private",
        "explicit correction",
        memory_type="semantic",
        confidence=1,
        expires_at="2999-01-01T08:00:00+08:00",
        supersedes="  prior-memory-id  ",
        source_ref="  docs/current/source.md#fact  ",
        valid_from="2026-07-10T08:00:00+08:00",
        last_verified_at="2026-07-10T09:30:00+08:00",
        sensitivity="internal",
    )

    assert payload["ok"] is True
    stored = fake_memory.calls[0][1]["metadata"]
    assert stored["memory_type"] == "semantic"
    assert stored["confidence"] == 1.0
    assert stored["expires_at"] == "2999-01-01T00:00:00Z"
    assert stored["supersedes"] == "prior-memory-id"
    assert stored["source_ref"] == "docs/current/source.md#fact"
    assert stored["valid_from"] == "2026-07-10T00:00:00Z"
    assert stored["last_verified_at"] == "2026-07-10T01:30:00Z"
    assert stored["sensitivity"] == "internal"

    # Existing callers that supplied lifecycle values through metadata remain compatible,
    # but the values now pass through the same validation and normalization path.
    legacy = server.xinao_memory_remember(
        "A dated event",
        "user-a",
        "project-a",
        "private",
        "legacy metadata caller",
        metadata={
            "memory_type": "episodic",
            "confidence": 0,
            "expires_at": "2999-02-01T00:00:00Z",
            "source_ref": "AGENTS.md",
            "valid_from": "2026-01-01T00:00:00Z",
            "last_verified_at": "2026-07-10T00:00:00Z",
            "sensitivity": "public",
        },
    )
    assert legacy["ok"] is True
    legacy_metadata = fake_memory.calls[1][1]["metadata"]
    assert legacy_metadata["memory_type"] == "episodic"
    assert legacy_metadata["confidence"] == 0.0
    assert legacy_metadata["source_ref"] == "AGENTS.md"
    assert legacy_metadata["sensitivity"] == "public"


def test_expired_records_are_hidden_by_default_but_can_be_read_explicitly(
    fake_memory: FakeMemory,
) -> None:
    _seed_record(fake_memory, "active")
    _seed_record(fake_memory, "expired", metadata={"expires_at": "2000-01-01T00:00:00Z"})
    _seed_record(fake_memory, "future", metadata={"expires_at": "2999-01-01T00:00:00Z"})
    _seed_record(fake_memory, "legacy-malformed", metadata={"expires_at": "not-a-time"})

    searched = server.xinao_memory_search("preference", "user-a", "project-a", "private")
    listed = server.xinao_memory_list("user-a", "project-a", "private")
    hidden = server.xinao_memory_get("expired", "user-a", "project-a", "private")
    visible = server.xinao_memory_get(
        "expired", "user-a", "project-a", "private", include_expired=True
    )
    all_results = server.xinao_memory_search(
        "preference", "user-a", "project-a", "private", include_expired=True
    )

    expected_default = ["active", "future", "legacy-malformed"]
    assert [item["id"] for item in searched["results"]] == expected_default
    assert [item["id"] for item in listed["results"]] == expected_default
    assert hidden["found"] is False
    assert visible["found"] is True
    assert [item["id"] for item in all_results["results"]] == [
        "active",
        "expired",
        "future",
        "legacy-malformed",
    ]


def test_search_list_and_get_enforce_exact_domain(fake_memory: FakeMemory) -> None:
    _seed_record(fake_memory, "own")
    _seed_record(fake_memory, "foreign", user_id="user-b")

    searched = server.xinao_memory_search(
        "answer style", "user-a", "project-a", "private", top_k=5, min_score=0.25
    )
    listed = server.xinao_memory_list("user-a", "project-a", "private", top_k=5)
    own = server.xinao_memory_get("own", "user-a", "project-a", "private")
    concealed = server.xinao_memory_get("foreign", "user-a", "project-a", "private")

    assert searched["ok"] is True
    assert [item["id"] for item in searched["results"]] == ["own"]
    search_call = next(call for call in fake_memory.calls if call[0] == "search")
    assert search_call[1]["filters"] == {
        "user_id": "user-a",
        "run_id": server._domain_run_id(
            {"user_id": "user-a", "project": "project-a", "scope": "private"}
        ),
        "project": "project-a",
        "scope": "private",
    }
    assert search_call[1]["top_k"] == 5
    assert search_call[1]["threshold"] == 0.25
    assert [item["id"] for item in listed["results"]] == ["own"]
    assert own["found"] is True
    assert own["result"]["id"] == "own"
    assert concealed["ok"] is True
    assert concealed["found"] is False
    assert concealed["result"] is None


def test_history_requires_current_domain_ownership_and_redacts_events(
    fake_memory: FakeMemory,
) -> None:
    _seed_record(fake_memory, "own", metadata={"expires_at": "2000-01-01T00:00:00Z"})
    _seed_record(fake_memory, "foreign", user_id="user-b")
    fake_memory.history_records["own"] = [
        {
            "id": "history-1",
            "memory_id": "own",
            "old_memory": "token=old-secret",
            "new_memory": "Authorization: Bearer abc.def password=new-secret",
            "event": "UPDATE",
            "created_at": "2026-07-10T00:00:00Z",
            "updated_at": "2026-07-10T01:00:00Z",
            "is_deleted": 0,
            "actor_id": "operator",
            "role": "user",
            "unexpected_secret": "must-not-leak",
        },
        {"id": "wrong", "memory_id": "another-id", "new_memory": "must-not-leak"},
    ]
    fake_memory.history_records["foreign"] = [
        {"id": "foreign-history", "memory_id": "foreign", "new_memory": "private"}
    ]

    own = server.xinao_memory_history("own", "user-a", "project-a", "private")
    concealed = server.xinao_memory_history("foreign", "user-a", "project-a", "private")

    assert own["ok"] is True
    assert own["found"] is True
    assert own["count"] == 1
    event = own["results"][0]
    assert set(event) == {
        "id",
        "memory_id",
        "old_memory",
        "new_memory",
        "event",
        "created_at",
        "updated_at",
        "actor_id",
        "role",
        "is_deleted",
    }
    assert "old-secret" not in str(event)
    assert "abc.def" not in str(event)
    assert "new-secret" not in str(event)
    assert "must-not-leak" not in str(event)
    assert event["old_memory"] == "token=[REDACTED]"
    assert concealed["found"] is False
    assert concealed["results"] == []

    own_get_index = fake_memory.calls.index(("get", {"memory_id": "own"}))
    own_history_index = fake_memory.calls.index(("history", {"memory_id": "own"}))
    assert own_get_index < own_history_index
    assert ("history", {"memory_id": "foreign"}) not in fake_memory.calls


def test_history_result_count_and_text_are_bounded(fake_memory: FakeMemory) -> None:
    _seed_record(fake_memory, "own")
    fake_memory.history_records["own"] = [
        {
            "id": f"history-{index}",
            "memory_id": "own",
            "old_memory": "x" * (server.MAX_TEXT_CHARS + 100) if index == 0 else None,
            "new_memory": f"value-{index}",
            "event": "UPDATE",
            "is_deleted": False,
        }
        for index in range(server.MAX_HISTORY_EVENTS + 5)
    ]

    payload = server.xinao_memory_history("own", "user-a", "project-a", "private")

    assert payload["ok"] is True
    assert payload["count"] == server.MAX_HISTORY_EVENTS
    assert payload["truncated"] is True
    assert len(payload["results"][0]["old_memory"]) == server.MAX_TEXT_CHARS
    assert payload["results"][0]["old_memory"].endswith("...[TRUNCATED]")


def test_update_and_single_delete_require_domain_match(fake_memory: FakeMemory) -> None:
    _seed_record(fake_memory, "own")
    _seed_record(fake_memory, "foreign", user_id="user-b")

    denied_update = server.xinao_memory_update(
        "foreign",
        "user-a",
        "project-a",
        "private",
        "correction request",
        text="must not cross boundary",
    )
    denied_delete = server.xinao_memory_delete(
        "foreign", "user-a", "project-a", "private", "delete request"
    )
    assert denied_update["found"] is False
    assert denied_update["updated"] is False
    assert denied_delete["found"] is False
    assert denied_delete["deleted"] is False
    assert not any(call[0] == "update" for call in fake_memory.calls)
    assert not any(call[0] == "delete" for call in fake_memory.calls)

    updated = server.xinao_memory_update(
        "own",
        "user-a",
        "project-a",
        "private",
        "explicit correction",
        text="corrected text",
        metadata={"confidence": 0.9},
        timestamp="2026-07-10T01:02:03Z",
    )
    deleted = server.xinao_memory_delete(
        "own",
        "user-a",
        "project-a",
        "private",
        "explicit delete",
        "2026-07-10T01:03:00Z",
    )
    assert updated["ok"] is True
    assert updated["updated"] is True
    assert updated["record"]["memory"] == "corrected text"
    assert updated["record"]["metadata"]["scope"] == "private"
    assert deleted["ok"] is True
    assert deleted["deleted"] is True
    assert "own" not in fake_memory.records
    assert "foreign" in fake_memory.records


def test_expired_record_remains_available_to_exact_update_and_delete(
    fake_memory: FakeMemory,
) -> None:
    _seed_record(fake_memory, "expired", metadata={"expires_at": "2000-01-01T00:00:00Z"})

    updated = server.xinao_memory_update(
        "expired",
        "user-a",
        "project-a",
        "private",
        "lifecycle correction",
        confidence=0.75,
    )
    deleted = server.xinao_memory_delete(
        "expired", "user-a", "project-a", "private", "explicit cleanup"
    )

    assert updated["ok"] is True
    assert updated["updated"] is True
    assert updated["record"]["metadata"]["confidence"] == 0.75
    assert deleted["ok"] is True
    assert deleted["deleted"] is True
    assert "expired" not in fake_memory.records


@pytest.mark.parametrize(
    ("call", "expected_code"),
    [
        (
            lambda: server.xinao_memory_add(
                "x" * (server.MAX_TEXT_CHARS + 1),
                "u",
                "p",
                "s",
                "test",
            ),
            "value_too_long",
        ),
        (
            lambda: server.xinao_memory_add(
                "text",
                "u",
                "p",
                "s",
                "test",
                {"project": "override"},
            ),
            "reserved_metadata_key",
        ),
        (
            lambda: server.xinao_memory_add("text", "u", "p", "s", "test", timestamp="2026-07-10"),
            "invalid_timestamp",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", memory_type="working"
            ),
            "invalid_memory_type",
        ),
        (
            lambda: server.xinao_memory_remember("text", "u", "p", "s", "test", confidence=1.01),
            "invalid_confidence",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", metadata={"confidence": -0.01}
            ),
            "invalid_confidence",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", expires_at="2999-01-01"
            ),
            "invalid_expires_at",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", supersedes="bad\x00id"
            ),
            "invalid_identifier",
        ),
        (
            lambda: server.xinao_memory_update("same", "u", "p", "s", "test", supersedes="same"),
            "invalid_supersedes",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text",
                "u",
                "p",
                "s",
                "test",
                source_ref="x" * (server.MAX_SOURCE_REF_CHARS + 1),
            ),
            "value_too_long",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", valid_from="2026-07-10"
            ),
            "invalid_valid_from",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", last_verified_at="not-a-time"
            ),
            "invalid_last_verified_at",
        ),
        (
            lambda: server.xinao_memory_remember(
                "text", "u", "p", "s", "test", sensitivity="secret"
            ),
            "invalid_sensitivity",
        ),
        (
            lambda: server.xinao_memory_search(
                "query",
                "u",
                "p",
                "s",
                include_expired="yes",  # type: ignore[arg-type]
            ),
            "invalid_include_expired",
        ),
        (
            lambda: server.xinao_memory_search("query", "u", "p", "s", top_k=0),
            "invalid_top_k",
        ),
        (
            lambda: server.xinao_memory_search("q" * (server.MAX_QUERY_CHARS + 1), "u", "p", "s"),
            "value_too_long",
        ),
    ],
)
def test_parameter_boundaries_fail_before_backend_call(
    fake_memory: FakeMemory,
    call: Any,
    expected_code: str,
) -> None:
    payload = call()
    assert payload["ok"] is False
    assert payload["error"]["code"] == expected_code
    assert fake_memory.calls == []


def test_backend_errors_are_structured_and_do_not_echo_secret(
    fake_memory: FakeMemory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNRELATED_TEST_SECRET", "environment-secret-value")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("token=backend-secret environment-secret-value")

    monkeypatch.setattr(fake_memory, "search", fail)
    payload = server.xinao_memory_search("query", "u", "p", "s")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "local_backend_error"
    assert "backend-secret" not in str(payload)
    assert "environment-secret-value" not in str(payload)


def test_interprocess_lock_contention_is_bounded_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def busy_process_lock(runtime_root: Any) -> Any:
        raise server.Mem0OperationBusy("locked by another process")
        yield

    monkeypatch.setattr(server, "_memory_instance", None)
    monkeypatch.setattr(server, "local_mem0_operation_lock", busy_process_lock)
    payload = server.xinao_memory_remember(
        "stable preference",
        "user-a",
        "project-a",
        "private",
        "explicit user statement",
    )
    assert payload["ok"] is False
    assert payload["error"] == {
        "code": "memory_busy",
        "type": "MemoryBusyError",
        "message": "Local memory is busy; retry shortly",
        "retryable": True,
        "retry_after_seconds": 2,
    }
