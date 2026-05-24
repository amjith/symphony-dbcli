from __future__ import annotations

import pytest

from symphony_dbcli.config import default_config
from symphony_dbcli.workflow_engine import (
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowExecutionContext,
    condition_matches,
)


def test_workflow_engine_selects_task_type_transition() -> None:
    engine = WorkflowEngine(default_config().workflow)

    code_match = engine.single_transition(
        from_state="setup_complete",
        trigger="automatic",
        context=WorkflowExecutionContext(task_type="code"),
        actions={"codex.fix_issue", "codex.research_issue"},
    )
    research_match = engine.single_transition(
        from_state="setup_complete",
        trigger="automatic",
        context=WorkflowExecutionContext(task_type="research"),
        actions={"codex.fix_issue", "codex.research_issue"},
    )

    assert code_match is not None
    assert code_match.name == "fix_issue"
    assert research_match is not None
    assert research_match.name == "research_issue"


def test_workflow_engine_lists_matching_human_gates() -> None:
    engine = WorkflowEngine(default_config().workflow)

    matches = engine.matching_transitions(
        from_state="review",
        trigger="human",
        context=WorkflowExecutionContext(task_type="code"),
    )

    assert [match.name for match in matches] == ["create_draft_pr", "mark_blocked"]


def test_condition_matching_rejects_unknown_conditions() -> None:
    assert condition_matches('task.type == "code"', WorkflowExecutionContext(task_type="code")) is True

    with pytest.raises(WorkflowEngineError, match="Unsupported workflow condition"):
        condition_matches("issue.priority == high", WorkflowExecutionContext(task_type="code"))
