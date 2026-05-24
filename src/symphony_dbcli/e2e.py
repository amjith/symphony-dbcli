from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .config import (
    CodexConfig,
    DashboardConfig,
    DatabaseConfig,
    GitHubConfig,
    PolicyConfig,
    ProfileConfig,
    WorkerConfig,
    WorkflowConfig,
    WorkspaceConfig,
    render_toml,
)
from .github import GitHubClient, GitHubError
from .orchestrator import Orchestrator, load_and_record_workflow
from .review_actions import ReviewActions
from .store import Store
from .worktree import safe_key

DEFAULT_FIXTURE_REPO = "amjith/symphony-dbcli-e2e-fixture"
FIXTURE_TITLE_PREFIX = "Symphony e2e"


@dataclass(frozen=True)
class E2EFixtureConfig:
    repo: str = DEFAULT_FIXTURE_REPO
    root: Path = Path(".symphony/e2e")
    task_type: str = "code"
    create_pr: bool = True
    reset_open_todo: bool = True


@dataclass(frozen=True)
class E2EFixtureResult:
    issue_url: str
    attempt_id: int
    workflow_path: Path
    database_path: Path
    worktree_path: str
    pull_request_url: str = ""


class E2EFixtureError(RuntimeError):
    """Raised when the GitHub-backed e2e fixture cannot run."""


def run_fixture(config: E2EFixtureConfig) -> E2EFixtureResult:
    _ensure_github_token()
    paths = _fixture_paths(config)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.workflow.parent.mkdir(parents=True, exist_ok=True)
    _write_fake_codex(paths.fake_codex)
    workflow_config = _workflow_config(config, paths)
    _write_fixture_workflow(paths.workflow, workflow_config)
    store = Store(workflow_config.database.path)
    store.init()
    workflow_config, workflow_version_id = load_and_record_workflow(store, paths.workflow)

    _ensure_labels(config.repo)
    if config.reset_open_todo:
        _clear_open_todo_issues(config.repo)
    issue_url = _create_issue(config.repo, config.task_type)
    issue_number = _issue_number_from_url(issue_url)

    orchestrator = Orchestrator(workflow_config, store, workflow_version_id)
    _poll_until_issue_visible(orchestrator, store, config.repo, issue_number)
    attempt_id = orchestrator.claim_next()
    if attempt_id is None:
        raise E2EFixtureError(f"No eligible issue was claimed for {config.repo}#{issue_number}.")
    attempt = store.attempt_by_id(attempt_id)
    if not attempt or int(attempt["issue_number"]) != issue_number:
        raise E2EFixtureError("The fixture claimed an unexpected issue; rerun with a clean fixture repo.")
    orchestrator.run_attempt(attempt_id)

    pull_request_url = ""
    if config.create_pr and config.task_type == "code":
        pull_request_url = (
            ReviewActions(
                workflow_config,
                store,
                github=_E2EGitHubClient(workflow_config.github),
            )
            .create_draft_pr(attempt_id)
            .url
        )
    completed_attempt = store.attempt_by_id(attempt_id)
    worktree_path = str(completed_attempt["worktree_path"]) if completed_attempt else ""
    return E2EFixtureResult(
        issue_url=issue_url,
        attempt_id=attempt_id,
        workflow_path=paths.workflow,
        database_path=paths.database,
        worktree_path=worktree_path,
        pull_request_url=pull_request_url,
    )


def _poll_until_issue_visible(
    orchestrator: Orchestrator,
    store: Store,
    repo: str,
    issue_number: int,
) -> None:
    for _ in range(6):
        orchestrator.poll_once()
        if store.issue_detail(repo, issue_number):
            return
        time.sleep(2)
    raise E2EFixtureError(f"GitHub issue {repo}#{issue_number} was not visible to the poller.")


@dataclass(frozen=True)
class _FixturePaths:
    root: Path
    database: Path
    workflow: Path
    fake_codex: Path
    worktrees: Path
    repos: Path


def _fixture_paths(config: E2EFixtureConfig) -> _FixturePaths:
    run_key = str(time.time_ns())
    root = config.root / safe_key(config.repo)
    run_root = root / "runs" / run_key
    return _FixturePaths(
        root=root,
        database=run_root / "symphony.db",
        workflow=run_root / "WORKFLOW.md",
        fake_codex=root / "bin" / "fake-codex",
        worktrees=run_root / "worktrees",
        repos=root / "repos",
    )


def _workflow_config(config: E2EFixtureConfig, paths: _FixturePaths) -> WorkflowConfig:
    return WorkflowConfig(
        profile=ProfileConfig(active="e2e"),
        github=GitHubConfig(
            repos=[config.repo],
            auth_strategy="token",
            token_env="SYMPHONY_GITHUB_TOKEN",
            fallback_token_env="GH_TOKEN",
        ),
        workspace=WorkspaceConfig(
            root=str(paths.worktrees),
            bare_repos_root=str(paths.repos),
            retention_days=1,
        ),
        workers=WorkerConfig(
            max_global=1,
            max_per_repo=1,
            default_task_type=config.task_type,
            poll_interval_seconds=5,
            retry_limit=0,
        ),
        dashboard=DashboardConfig(host="127.0.0.1", port=8766),
        database=DatabaseConfig(path=str(paths.database)),
        codex=CodexConfig(
            command=str(paths.fake_codex),
            transport="exec",
            approval_policy="never",
        ),
        policy=PolicyConfig(dry_run=False),
        instructions=(
            "This is an e2e fixture run. Keep changes limited to the fixture task, "
            "run the local unittest suite, and summarize the result succinctly."
        ),
    )


def _write_fixture_workflow(path: Path, config: WorkflowConfig) -> None:
    data = config.to_dict()
    data["profiles"] = {
        "e2e": {
            "database": {"path": config.database.path},
            "workspace": {
                "root": config.workspace.root,
                "bare_repos_root": config.workspace.bare_repos_root,
            },
            "dashboard": {"host": config.dashboard.host, "port": config.dashboard.port},
        }
    }
    path.write_text(
        "\n".join(
            [
                "# Symphony DBCLI E2E Workflow",
                "",
                "Generated by `symphony-dbcli e2e run-fixture`.",
                "",
                "```toml",
                render_toml(data).rstrip(),
                "```",
                "",
                "## Worker Instructions",
                "",
                config.instructions,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_fake_codex(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_CODEX_SCRIPT, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _ensure_github_token() -> None:
    if os.environ.get("SYMPHONY_GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        return
    token = _gh(["auth", "token"]).strip()
    if not token:
        raise E2EFixtureError("Could not read a token from `gh auth token`.")
    os.environ["SYMPHONY_GITHUB_TOKEN"] = token


def _ensure_labels(repo: str) -> None:
    labels = {
        "symphony:todo": ("1f7a5a", "Dispatchable Symphony work"),
        "symphony:working": ("d99a2b", "Symphony worker claimed this issue"),
        "symphony:review": ("135f7a", "Symphony output needs review"),
        "symphony:blocked": ("9f3a38", "Blocked from Symphony dispatch"),
        "symphony:done": ("6a737d", "Symphony terminal state"),
        "symphony:type:code": ("5319e7", "Symphony coding task"),
        "symphony:type:research": ("c5def5", "Symphony research task"),
    }
    for name, (color, description) in labels.items():
        _gh(
            [
                "label",
                "create",
                name,
                "--repo",
                repo,
                "--color",
                color,
                "--description",
                description,
                "--force",
            ]
        )


def _clear_open_todo_issues(repo: str) -> None:
    raw = _gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            "symphony:todo",
            "--json",
            "number",
            "--limit",
            "100",
        ]
    )
    for issue in cast(list[dict[str, Any]], json.loads(raw)):
        _gh(
            [
                "issue",
                "edit",
                str(issue["number"]),
                "--repo",
                repo,
                "--remove-label",
                "symphony:todo",
            ]
        )


def _create_issue(repo: str, task_type: str) -> str:
    task_label = "symphony:type:code" if task_type == "code" else "symphony:type:research"
    title = f"{FIXTURE_TITLE_PREFIX} {task_type} task {int(time.time())}"
    body = "\n".join(
        [
            "This issue is generated by the symphony-dbcli e2e harness.",
            "",
            "For code tasks, fix `fixture_calc.add()` so the unittest suite passes.",
            "For research tasks, explain the expected fix without editing files.",
        ]
    )
    return _gh(
        [
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
            "--label",
            "symphony:todo",
            "--label",
            task_label,
        ]
    ).strip()


def _issue_number_from_url(issue_url: str) -> int:
    match = re.search(r"/issues/(\d+)$", issue_url.strip())
    if not match:
        raise E2EFixtureError(f"Could not parse issue number from {issue_url!r}.")
    return int(match.group(1))


def _gh(args: list[str]) -> str:
    result = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise E2EFixtureError(result.stderr.strip() or f"gh {' '.join(args)} failed")
    return result.stdout


class _E2EGitHubClient(GitHubClient):
    def push_branch(self, *, repo: str, worktree_path: str, branch: str) -> None:
        result = subprocess.run(
            ["git", "-C", worktree_path, "push", f"git@github.com:{repo}.git", f"{branch}:{branch}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitHubError(result.stderr.strip() or "git push failed")


FAKE_CODEX_SCRIPT = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="fake-codex")
    subcommands = parser.add_subparsers(dest="command", required=True)
    exec_parser = subcommands.add_parser("exec")
    exec_parser.add_argument("--cd", required=True)
    exec_parser.add_argument("--ask-for-approval", default="never")
    exec_parser.add_argument("prompt")
    args = parser.parse_args()
    cwd = Path(args.cd)
    if "Task type: code" in args.prompt:
        source = cwd / "fixture_calc.py"
        source.write_text(source.read_text(encoding="utf-8").replace("left - right", "left + right"), encoding="utf-8")
        result = subprocess.run(["python", "-m", "unittest", "discover", "-v"], cwd=cwd, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode
        print("Summary:")
        print("- Updated `fixture_calc.add()` to return the sum of both arguments.")
        print("- Verified the fixture unittest suite.")
        print()
        print("Checks run:")
        print("- `python -m unittest discover -v` passed.")
        return 0
    print("Summary:")
    print("- Researched the fixture issue and identified that `fixture_calc.add()` should return `left + right`.")
    print()
    print("Checks run:")
    print("- No code changes were made for this research task.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
