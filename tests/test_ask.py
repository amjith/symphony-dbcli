from __future__ import annotations

from pathlib import Path

from symphony_dbcli.ask import answer_question, answer_with_links
from symphony_dbcli.config import default_config, render_workflow
from symphony_dbcli.db import create_db_engine, create_session_factory
from symphony_dbcli.models import create_model_tables
from symphony_dbcli.sources import SourceCreate, SourceItemUpsert, SourceRepository
from symphony_dbcli.store import IssueSnapshot, Store
from symphony_dbcli.work_items import WorkItemActivation, WorkItemRepository


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

    rich_answer = answer_with_links(store, "How long did issue #99 take?")

    assert rich_answer.text == answer
    assert rich_answer.links[0].label == "Issue detail"
    assert rich_answer.links[0].url == "/issues/dbcli/mycli/99"
    assert rich_answer.links[1].label == f"Attempt {attempt_id}"
    assert rich_answer.links[1].url == f"/attempts/{attempt_id}"


def test_ask_summarizes_pending_gates(tmp_path: Path) -> None:
    store = Store(tmp_path / "symphony.db")
    store.init()
    _seed_issue(store)
    attempt_id = store.create_attempt(
        repo="dbcli/mycli",
        issue_number=99,
        task_type="research",
        workflow_version_id=None,
    )
    instance_id = store.create_workflow_instance(
        repo="dbcli/mycli",
        issue_number=99,
        task_type="research",
        workflow_version_id=None,
        initial_state="review",
        attempt_id=attempt_id,
    )
    store.open_workflow_gate(
        instance_id=instance_id,
        workflow_version_id=None,
        gate="review_answer",
        transition_name="post_answer",
        state="review",
    )

    answer = answer_with_links(store, "What is waiting for review?")

    assert "1 human gate(s) are pending" in answer.text
    assert "dbcli/mycli#99:post_answer" in answer.text
    assert answer.links[0].url == "/issues/dbcli/mycli/99"


def test_ask_answers_board_and_work_item_questions(tmp_path: Path) -> None:
    store = Store(tmp_path / "symphony.db")
    store.init()
    engine = create_db_engine(store.path)
    create_model_tables(engine)
    session_factory = create_session_factory(engine)
    source_repo = SourceRepository(session_factory)
    work_item_repo = WorkItemRepository(session_factory)
    source = source_repo.create_source(SourceCreate(repo="dbcli/litecli"))
    source_repo.upsert_source_items(
        source_id=source.id,
        items=[
            SourceItemUpsert(
                kind="issue",
                number=245,
                title="Board issue",
                url="https://github.com/dbcli/litecli/issues/245",
                state="open",
                author="alice",
                labels=["bug"],
                body="issue body",
                github_updated_at="2026-05-25T01:00:00Z",
            )
        ],
    )

    board_answer = answer_with_links(store, "What is on the board?")
    source_item = source_repo.backlog_source_items(source.id)[0]
    work_item = work_item_repo.activate_source_item(
        WorkItemActivation(source_item_id=source_item.id, task_type="code")
    )
    work_item_answer = answer_with_links(store, f"What about work item #{work_item.id}?")

    assert "Backlog: 1" in board_answer.text
    assert board_answer.links[0].url == "/board"
    assert f"Work item #{work_item.id} is Todo" in work_item_answer.text
    assert work_item_answer.links[0].url == f"/work-items/{work_item.id}"


def _seed_issue(store: Store) -> None:
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
