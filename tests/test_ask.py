from __future__ import annotations

from pathlib import Path

from symphony_dbcli.ask import answer_question
from symphony_dbcli.config import default_config, render_workflow
from symphony_dbcli.store import IssueSnapshot, Store


def test_ask_summarizes_issue_metrics(tmp_path: Path) -> None:
    store = Store(tmp_path / "symphony.db")
    store.init()
    config = default_config()
    version_id = store.record_workflow_version("WORKFLOW.md", render_workflow(config), config)
    store.upsert_issue(
        IssueSnapshot(
            repo="dbcli/mycli",
            number=99,
            title="Question",
            url="https://github.com/dbcli/mycli/issues/99",
            state="open",
            labels=["symphony:todo"],
            task_type="research",
        )
    )
    attempt_id = store.create_attempt(
        repo="dbcli/mycli",
        issue_number=99,
        task_type="research",
        workflow_version_id=version_id,
    )
    store.record_codex_turn(
        attempt_id,
        thread_id="thread-99",
        turn_index=1,
        status="completed",
        started_monotonic_ns=1_000_000,
        ended_monotonic_ns=3_000_000,
    )

    answer = answer_question(store, "How long did issue #99 take?")

    assert "dbcli/mycli#99" in answer
    assert "Turns: 1" in answer
    assert f"Workflow version: {version_id}" in answer
