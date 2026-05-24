from __future__ import annotations

from pathlib import Path

import pytest

from symphony_dbcli.e2e import (
    E2EFixtureConfig,
    E2EFixtureError,
    _fixture_paths,
    _issue_number_from_url,
    _workflow_config,
)


def test_fixture_workflow_uses_fast_local_paths(tmp_path: Path) -> None:
    config = E2EFixtureConfig(repo="amjith/symphony-dbcli-e2e-fixture", root=tmp_path)
    paths = _fixture_paths(config)

    workflow = _workflow_config(config, paths)

    assert workflow.github.repos == ["amjith/symphony-dbcli-e2e-fixture"]
    assert workflow.github.auth_strategy == "token"
    assert workflow.policy.dry_run is False
    assert workflow.codex.transport == "exec"
    assert workflow.codex.command == str(paths.fake_codex)
    assert workflow.workers.poll_interval_seconds == 5
    assert workflow.database.path == str(paths.database)
    assert str(paths.worktrees).startswith(str(tmp_path))


def test_issue_number_from_url() -> None:
    assert _issue_number_from_url("https://github.com/amjith/symphony-dbcli-e2e-fixture/issues/42") == 42


def test_issue_number_from_url_rejects_invalid_url() -> None:
    with pytest.raises(E2EFixtureError, match="Could not parse"):
        _issue_number_from_url("https://github.com/amjith/symphony-dbcli-e2e-fixture")
