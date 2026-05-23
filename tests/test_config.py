from __future__ import annotations

import pytest

from symphony_dbcli.config import (
    WorkflowError,
    default_config,
    parse_workflow,
    render_workflow,
    validate_config,
)


def test_rendered_workflow_round_trips() -> None:
    workflow = render_workflow(default_config())

    config = parse_workflow(workflow)

    assert config.tracker.kind == "github"
    assert config.github.repos == ["dbcli/pgcli", "dbcli/mycli", "dbcli/litecli"]
    assert config.workspace.strategy == "worktree"
    assert "Workers should be direct" in config.instructions


def test_workflow_validation_rejects_missing_toml_block() -> None:
    with pytest.raises(WorkflowError, match="fenced toml"):
        parse_workflow("# no config here")


def test_workflow_validation_rejects_invalid_repo() -> None:
    workflow = render_workflow(default_config()).replace('"dbcli/pgcli"', '"not a repo"')

    with pytest.raises(WorkflowError, match="invalid repository"):
        validate_config(parse_workflow(workflow))
