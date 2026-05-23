from __future__ import annotations

import re

from .store import Store
from .types import AttemptSummary

ISSUE_RE = re.compile(r"(?:#|issue\s+)(?P<number>\d+)", re.IGNORECASE)


def answer_question(store: Store, question: str) -> str:
    normalized = question.strip().lower()
    attempts = store.attempt_summaries()
    if not attempts:
        return "I do not have any worker attempts recorded yet."

    issue_match = ISSUE_RE.search(question)
    if issue_match:
        issue_number = int(issue_match.group("number"))
        matching = [row for row in attempts if row.issue_number == issue_number]
        if not matching:
            return f"I do not have recorded attempts for issue #{issue_number}."
        return _summarize_attempt(matching[0])

    if "error" in normalized:
        total = sum(row.error_count for row in attempts)
        worst = max(attempts, key=lambda row: row.error_count)
        return (
            f"{total} worker errors are recorded across the latest {len(attempts)} attempts. "
            f"The highest-error attempt is {worst.issue_ref} with {worst.error_count} errors."
        )

    if "turn" in normalized:
        total = sum(row.turn_count for row in attempts)
        return f"{total} Codex turns are recorded across the latest {len(attempts)} attempts."

    if "long" in normalized or "time" in normalized or "duration" in normalized:
        completed = [row for row in attempts if row.duration_ms is not None]
        if not completed:
            return "No completed attempt durations are recorded yet."
        slowest = max(completed, key=lambda row: row.duration_ms or 0)
        return (
            f"The slowest recorded attempt is {slowest.issue_ref} at {_format_ms(slowest.duration_ms)}. "
            f"Codex time for that attempt is {_format_ms(slowest.codex_duration_ms)}."
        )

    latest = attempts[0]
    return (
        f"Latest attempt: {latest.issue_ref} is {latest.status} "
        f"in phase '{latest.current_phase or 'unknown'}', with {latest.turn_count} turns "
        f"and {latest.error_count} errors."
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
