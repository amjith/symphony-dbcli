from __future__ import annotations

from pathlib import Path

from symphony_dbcli.config import default_config, render_workflow
from symphony_dbcli.store import IssueSnapshot, Store


def test_store_records_workflow_versions_and_attempt_metrics(tmp_path: Path) -> None:
    store = Store(tmp_path / "symphony.db")
    store.init()
    config = default_config()
    workflow = render_workflow(config)

    version_id = store.record_workflow_version("WORKFLOW.md", workflow, config)
    same_version_id = store.record_workflow_version("WORKFLOW.md", workflow, config)

    assert same_version_id == version_id
    latest = store.latest_workflow_version()
    assert latest is not None
    assert latest["id"] == version_id

    store.upsert_issue(
        IssueSnapshot(
            repo="dbcli/pgcli",
            number=42,
            title="Investigate completion bug",
            url="https://github.com/dbcli/pgcli/issues/42",
            state="open",
            labels=["symphony:todo", "symphony:type:code"],
            task_type="code",
        )
    )
    attempt_id = store.create_attempt(
        repo="dbcli/pgcli",
        issue_number=42,
        task_type="code",
        workflow_version_id=version_id,
    )
    store.start_attempt(attempt_id, "worker-1")
    store.record_timeline_event(
        attempt_id,
        phase="codex",
        event_type="completed",
        started_monotonic_ns=1_000_000,
        ended_monotonic_ns=6_000_000,
    )
    store.record_codex_turn(
        attempt_id,
        thread_id="thread-1",
        turn_index=1,
        status="completed",
        started_monotonic_ns=1_000_000,
        ended_monotonic_ns=6_000_000,
    )
    store.record_error(
        attempt_id,
        phase="test",
        error_type="pytest_failed",
        message="one test failed",
        recoverable=True,
    )
    store.finish_attempt(attempt_id, "review", "needs_review")

    detail = store.attempt_detail(attempt_id)

    assert detail is not None
    assert detail["attempt"]["turn_count"] == 1
    assert detail["attempt"]["error_count"] == 1
    assert detail["attempt"]["codex_duration_ms"] == 5
    assert detail["attempt"]["duration_ms"] == 5


def test_eligible_issues_use_labels(tmp_path: Path) -> None:
    store = Store(tmp_path / "symphony.db")
    store.init()
    store.upsert_issue(
        IssueSnapshot(
            repo="dbcli/litecli",
            number=7,
            title="Support question",
            url="https://github.com/dbcli/litecli/issues/7",
            state="open",
            labels=["symphony:todo"],
            task_type="research",
        )
    )

    eligible = store.eligible_issues("symphony:todo", "symphony:blocked")

    assert len(eligible) == 1
    assert eligible[0]["repo"] == "dbcli/litecli"
