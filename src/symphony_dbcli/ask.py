from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select

from .db import SessionFactory, create_db_engine, create_session_factory
from .models import Source, SourceItem, WorkItem, WorkItemLink, create_model_tables
from .sources import SourceRepository
from .store import Store
from .types import AttemptSummary
from .work_items import KANBAN_STATES, STATE_LABELS, WorkItemRepository

ISSUE_RE = re.compile(r"(?:#|issue\s+)(?P<number>\d+)", re.IGNORECASE)
WORK_ITEM_RE = re.compile(r"work\s+item\s+#?(?P<number>\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerLink:
    label: str
    url: str


@dataclass(frozen=True)
class AskAnswer:
    text: str
    links: list[AnswerLink]


class AskFallback(Protocol):
    def answer(self, question: str, context: AskContext) -> str: ...


@dataclass(frozen=True)
class AskContext:
    attempts: list[AttemptSummary]
    pending_gate_count: int
    pending_gate_examples: list[str]
    total_errors: int


def answer_question(store: Store, question: str) -> str:
    return answer_with_links(store, question).text


def answer_with_links(store: Store, question: str, fallback: AskFallback | None = None) -> AskAnswer:
    normalized = question.strip().lower()
    board_answer = _answer_from_board(store, question, normalized)
    if board_answer is not None:
        return board_answer
    attempts = store.attempt_summaries()
    if not attempts:
        return AskAnswer("I do not have any worker attempts recorded yet.", [])
    context = _ask_context(store, attempts)

    issue_match = ISSUE_RE.search(question)
    if issue_match:
        issue_number = int(issue_match.group("number"))
        matching = [row for row in attempts if row.issue_number == issue_number]
        if not matching:
            return AskAnswer(f"I do not have recorded attempts for issue #{issue_number}.", [])
        return AskAnswer(_summarize_attempt(matching[0]), _links_for_attempt(matching[0]))

    if "error" in normalized:
        worst = max(attempts, key=lambda row: row.error_count)
        return AskAnswer(
            (
                f"{context.total_errors} worker errors are recorded across the latest {len(attempts)} attempts. "
                f"The highest-error attempt is {worst.issue_ref} with {worst.error_count} errors."
            ),
            _links_for_attempt(worst),
        )

    if "gate" in normalized or "review" in normalized or "waiting" in normalized:
        return AskAnswer(_summarize_gates(context), _links_for_attempt(attempts[0]))

    if "stuck" in normalized or "blocked" in normalized or "why" in normalized:
        return AskAnswer(_summarize_stuck_work(context), _links_for_attempt(attempts[0]))

    if "turn" in normalized:
        total = sum(row.turn_count for row in attempts)
        latest = attempts[0]
        return AskAnswer(
            f"{total} Codex turns are recorded across the latest {len(attempts)} attempts.",
            _links_for_attempt(latest),
        )

    if "long" in normalized or "time" in normalized or "duration" in normalized:
        completed = [row for row in attempts if row.duration_ms is not None]
        if not completed:
            return AskAnswer("No completed attempt durations are recorded yet.", [])
        slowest = max(completed, key=lambda row: row.duration_ms or 0)
        return AskAnswer(
            (
                f"The slowest recorded attempt is {slowest.issue_ref} at {_format_ms(slowest.duration_ms)}. "
                f"Codex time for that attempt is {_format_ms(slowest.codex_duration_ms)}."
            ),
            _links_for_attempt(slowest),
        )

    latest = attempts[0]
    if fallback:
        fallback_text = fallback.answer(question, context).strip()
        if fallback_text:
            return AskAnswer(fallback_text, _links_for_attempt(latest))
    return AskAnswer(_structured_fallback(context), _links_for_attempt(latest))


def _answer_from_board(store: Store, question: str, normalized: str) -> AskAnswer | None:
    engine = create_db_engine(store.path)
    create_model_tables(engine)
    session_factory = create_session_factory(engine)
    source_repo = SourceRepository(session_factory)
    work_item_repo = WorkItemRepository(session_factory)
    sources = source_repo.list_sources()
    if not sources:
        return None

    work_item_match = WORK_ITEM_RE.search(question)
    if work_item_match:
        work_item_id = int(work_item_match.group("number"))
        work_item = work_item_repo.detail(work_item_id)
        if work_item is None:
            return AskAnswer(
                f"I do not have work item #{work_item_id}.", [AnswerLink("Work Items", "/work-items")]
            )
        return AskAnswer(
            f"Work item #{work_item.id} is {work_item.state_label} for {work_item.source_label} #{work_item.source_number}.",
            [AnswerLink(f"Work Item {work_item.id}", f"/work-items/{work_item.id}")],
        )

    issue_match = ISSUE_RE.search(question)
    if issue_match:
        answer = _answer_source_item_question(session_factory, int(issue_match.group("number")))
        if answer is not None:
            return answer

    if any(
        term in normalized for term in ("board", "backlog", "todo", "in progress", "review", "done", "status")
    ):
        backlog_count = sum(len(source_repo.backlog_source_items(source.id)) for source in sources)
        state_counts = {
            state: sum(len(work_item_repo.list_by_state(source.id, state)) for source in sources)
            for state in KANBAN_STATES
        }
        summary = ", ".join(
            [
                f"Backlog: {backlog_count}",
                *[f"{STATE_LABELS[state]}: {count}" for state, count in state_counts.items()],
            ]
        )
        return AskAnswer(
            f"Board status across {len(sources)} source(s): {summary}.",
            [AnswerLink("Board", "/board"), AnswerLink("Work Items", "/work-items")],
        )

    if "source" in normalized or "sync" in normalized:
        statuses = ", ".join(f"{source.repo}: {source.sync_status}" for source in sources)
        return AskAnswer(
            f"{len(sources)} source(s) are configured. {statuses}.",
            [AnswerLink("Sources", "/sources")],
        )
    return None


def _answer_source_item_question(session_factory: SessionFactory, number: int) -> AskAnswer | None:
    with session_factory() as session:
        row = session.execute(
            select(Source, SourceItem)
            .join(SourceItem, SourceItem.source_id == Source.id)
            .where(SourceItem.number == number)
            .order_by(Source.repo.asc())
        ).first()
        if row is None:
            return None
        source, source_item = row
        work_item = session.scalars(
            select(WorkItem)
            .outerjoin(WorkItemLink, WorkItemLink.work_item_id == WorkItem.id)
            .where(
                WorkItem.disposition == "active",
                (WorkItem.primary_source_item_id == source_item.id)
                | (WorkItemLink.source_item_id == source_item.id),
            )
            .order_by(WorkItem.id.desc())
        ).first()
        if work_item:
            return AskAnswer(
                f"{source.repo} #{number} is linked to work item #{work_item.id}, currently {STATE_LABELS[work_item.state]}.",
                [
                    AnswerLink(f"Work Item {work_item.id}", f"/work-items/{work_item.id}"),
                    AnswerLink("Board", f"/board?source_id={source.id}"),
                ],
            )
        return AskAnswer(
            f"{source.repo} #{number} is in {source_item.state} source state and has not been activated.",
            [AnswerLink("Board", f"/board?source_id={source.id}")],
        )


def _summarize_attempt(row: AttemptSummary) -> str:
    return (
        f"{row.issue_ref} is {row.status} in phase '{row.current_phase or 'unknown'}'. "
        f"Total time: {_format_ms(row.duration_ms)}. Codex time: {_format_ms(row.codex_duration_ms)}. "
        f"Turns: {row.turn_count}. Errors: {row.error_count}. "
        f"Workflow version: {row.workflow_version_id or 'unknown'}."
    )


def _format_ms(value: int | None) -> str:
    if value is None:
        return "not complete"
    ms = int(value)
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(round(seconds), 60)
    return f"{minutes}m {remaining}s"


def _links_for_attempt(row: AttemptSummary) -> list[AnswerLink]:
    return [
        AnswerLink("Issue detail", f"/issues/{row.repo}/{row.issue_number}"),
        AnswerLink(f"Attempt {row.id}", f"/attempts/{row.id}"),
    ]


def _ask_context(store: Store, attempts: list[AttemptSummary]) -> AskContext:
    gates = store.pending_workflow_gates(limit=5)
    return AskContext(
        attempts=attempts,
        pending_gate_count=len(store.pending_workflow_gates(limit=100)),
        pending_gate_examples=[
            f"{row['repo']}#{row['issue_number']}:{row['transition_name']}" for row in gates
        ],
        total_errors=sum(row.error_count for row in attempts),
    )


def _summarize_gates(context: AskContext) -> str:
    if context.pending_gate_count == 0:
        return "There are no pending human gates right now."
    examples = ", ".join(context.pending_gate_examples)
    return f"{context.pending_gate_count} human gate(s) are pending. Examples: {examples}."


def _summarize_stuck_work(context: AskContext) -> str:
    blocked = [row for row in context.attempts if row.status in {"blocked", "failed"}]
    if context.pending_gate_count:
        return _summarize_gates(context)
    if blocked:
        latest = blocked[0]
        return (
            f"{latest.issue_ref} is {latest.status} in phase '{latest.current_phase or 'unknown'}'. "
            f"It has {latest.error_count} errors and {latest.turn_count} turns."
        )
    latest = context.attempts[0]
    return (
        f"I do not see an obvious stuck worker. Latest attempt {latest.issue_ref} is {latest.status} "
        f"in phase '{latest.current_phase or 'unknown'}'."
    )


def _structured_fallback(context: AskContext) -> str:
    latest = context.attempts[0]
    gate_sentence = (
        f" {context.pending_gate_count} human gate(s) are pending."
        if context.pending_gate_count
        else " No human gates are pending."
    )
    return (
        f"Latest attempt: {latest.issue_ref} is {latest.status} "
        f"in phase '{latest.current_phase or 'unknown'}', with {latest.turn_count} turns "
        f"and {latest.error_count} errors.{gate_sentence}"
    )
