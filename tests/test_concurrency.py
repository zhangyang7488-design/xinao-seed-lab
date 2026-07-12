from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xinao_coordination import CoordinationService


def test_only_one_parallel_claim_wins(db_path: Path) -> None:
    root = CoordinationService(db_path)
    task = root.dispatch_task(actor="codex", title="one", goal="one winner", idempotency_key="dispatch")[
        "task"
    ]

    def claim(index: int) -> dict[str, object]:
        service = CoordinationService(db_path)
        return service.claim_task(worker_id=f"admin-{index}", idempotency_key=f"claim-{index}")

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(claim, range(32)))
    winners = [result for result in results if result["task"] is not None]
    assert len(winners) == 1
    assert winners[0]["task"]["task_id"] == task["task_id"]
    assert root.get_task(task["task_id"])["task"]["attempt_count"] == 1


def test_parallel_posts_have_no_projection_gap(db_path: Path) -> None:
    root = CoordinationService(db_path)
    opened = root.open_thread(actor="codex", title="parallel", max_rounds=200, idempotency_key="open")
    thread_id = opened["thread"]["thread_id"]

    def post(index: int) -> None:
        CoordinationService(db_path).post_message(
            actor="codex" if index % 2 else "grok_4_5",
            thread_id=thread_id,
            body=f"message-{index}",
            idempotency_key=f"post-{index}",
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(post, range(48)))
    thread = root.get_thread(thread_id)
    assert thread["thread"]["rounds"] == 48
    assert len(thread["messages"]) == 48
    versions = [
        event["stream_version"] for event in root.events(stream_type="thread", stream_id=thread_id)["events"]
    ]
    assert versions == list(range(1, 50))
