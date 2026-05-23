from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from .ask import answer_question
from .config import (
    WorkflowConfig,
    WorkflowError,
    default_config,
    load_workflow,
    prompt_for_config,
    validate_config,
    write_workflow,
)
from .dashboard import serve_dashboard
from .orchestrator import Orchestrator, WorkflowWatcher, load_and_record_workflow
from .store import Store
from .worktree import WorktreeManager


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = cast(Callable[[argparse.Namespace], int], args.func)
    try:
        return command(args)
    except WorkflowError as exc:
        print(f"workflow error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="symphony-dbcli")
    parser.add_argument("--workflow", default="WORKFLOW.md", help="Path to WORKFLOW.md")
    subcommands = parser.add_subparsers(required=True)

    init_workflow = subcommands.add_parser("init-workflow", help="Interactively create WORKFLOW.md")
    init_workflow.add_argument("--force", action="store_true", help="Overwrite an existing workflow file")
    init_workflow.add_argument("--defaults", action="store_true", help="Write defaults without prompting")
    init_workflow.set_defaults(func=cmd_init_workflow)

    init_db = subcommands.add_parser("init-db", help="Create or migrate the SQLite database")
    init_db.set_defaults(func=cmd_init_db)

    workflow = subcommands.add_parser("workflow", help="Workflow tools")
    workflow_sub = workflow.add_subparsers(required=True)
    validate = workflow_sub.add_parser("validate", help="Validate WORKFLOW.md")
    validate.set_defaults(func=cmd_workflow_validate)
    history = workflow_sub.add_parser("history", help="Show recorded workflow versions")
    history.add_argument("--limit", type=int, default=20)
    history.set_defaults(func=cmd_workflow_history)

    status = subcommands.add_parser("status", help="Show orchestrator status")
    status.set_defaults(func=cmd_status)

    ask = subcommands.add_parser("ask", help="Ask about workers, issues, timing, turns, or errors")
    ask.add_argument("question", nargs="+")
    ask.set_defaults(func=cmd_ask)

    poll_once = subcommands.add_parser("poll-once", help="Sync dispatchable GitHub issues into SQLite")
    poll_once.set_defaults(func=cmd_poll_once)

    serve = subcommands.add_parser("serve", help="Run dashboard and optional polling loop")
    serve.add_argument("--no-poll", action="store_true", help="Only run the dashboard")
    serve.add_argument("--dispatch", action="store_true", help="Claim one eligible issue after each poll")
    serve.set_defaults(func=cmd_serve)

    worker = subcommands.add_parser("worker", help="Worker commands")
    worker_sub = worker.add_subparsers(required=True)
    run = worker_sub.add_parser("run", help="Run one issue worker")
    run.add_argument("--repo", required=True)
    run.add_argument("--issue", required=True, type=int)
    run.add_argument("--task-type", choices=["code", "research"])
    run.set_defaults(func=cmd_worker_run)

    worktree = subcommands.add_parser("worktree", help="Worktree commands")
    worktree_sub = worktree.add_subparsers(required=True)
    cleanup = worktree_sub.add_parser("cleanup", help="Prune stale git worktree metadata")
    cleanup.set_defaults(func=cmd_worktree_cleanup)

    return parser


def cmd_init_workflow(args: argparse.Namespace) -> int:
    config = default_config() if args.defaults else prompt_for_config()
    validate_config(config)
    path = write_workflow(args.workflow, config, force=args.force)
    print(f"Wrote {path}")
    return 0


def cmd_init_db(args: argparse.Namespace) -> int:
    config = _load_config_if_exists(args.workflow)
    store = Store(config.database.path)
    store.init()
    workflow_path = Path(args.workflow)
    if workflow_path.exists():
        load_and_record_workflow(store, workflow_path)
    print(f"Initialized {config.database.path}")
    return 0


def cmd_workflow_validate(args: argparse.Namespace) -> int:
    config = load_workflow(args.workflow)
    validate_config(config)
    print(f"{args.workflow} is valid")
    return 0


def cmd_workflow_history(args: argparse.Namespace) -> int:
    config = _load_config_if_exists(args.workflow)
    store = Store(config.database.path)
    store.init()
    for row in store.workflow_history(args.limit):
        error = f" error={row['error']}" if row["error"] else ""
        print(f"{row['id']:>4} {row['created_at']} {row['status']} {row['content_hash'][:12]}{error}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = _load_config_if_exists(args.workflow)
    store = Store(config.database.path)
    store.init()
    summary = store.dashboard_summary()
    print(
        f"issues={summary['issue_count']} running={summary['running_attempts']} queued={summary['queued_attempts']}"
    )
    print(f"turns={summary['turn_count']} errors={summary['error_count']}")
    for row in summary["attempts"][:10]:
        print(
            f"attempt={row['id']} {row['repo']}#{row['issue_number']} "
            f"status={row['status']} phase={row['current_phase'] or '-'} "
            f"turns={row['turn_count']} errors={row['error_count']}"
        )
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    config = _load_config_if_exists(args.workflow)
    store = Store(config.database.path)
    store.init()
    print(answer_question(store, " ".join(args.question)))
    return 0


def cmd_poll_once(args: argparse.Namespace) -> int:
    config, version_id, store = _load_config_store_and_record(args.workflow)
    synced = Orchestrator(config, store, version_id).poll_once()
    print(f"Synced {synced} issues")
    return 0


def cmd_worker_run(args: argparse.Namespace) -> int:
    config, version_id, store = _load_config_store_and_record(args.workflow)
    attempt_id = Orchestrator(config, store, version_id).run_issue(
        args.repo,
        args.issue,
        task_type=args.task_type,
    )
    print(f"Recorded attempt {attempt_id}")
    return 0


def cmd_worktree_cleanup(args: argparse.Namespace) -> int:
    config = load_workflow(args.workflow)
    print(WorktreeManager(config.workspace).cleanup_prunable())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config, _, store = _load_config_store_and_record(args.workflow)
    if not args.no_poll:
        thread = threading.Thread(target=_poll_loop, args=(args, store), daemon=True)
        thread.start()
    serve_dashboard(store, config.dashboard.host, config.dashboard.port)
    return 0


def _poll_loop(args: argparse.Namespace, store: Store) -> None:
    watcher = WorkflowWatcher(store, args.workflow)
    interval = 60
    while True:
        try:
            config, version_id, _changed = watcher.reload_if_changed()
            interval = config.workers.poll_interval_seconds
            orchestrator = Orchestrator(config, store, version_id)
            orchestrator.poll_once()
            if args.dispatch:
                orchestrator.claim_next()
        except Exception as exc:  # Keep the dashboard alive.
            print(f"poll loop error: {exc}", file=sys.stderr)
        time.sleep(interval)


def _load_config_store_and_record(workflow_path: str) -> tuple[WorkflowConfig, int, Store]:
    config = load_workflow(workflow_path)
    store = Store(config.database.path)
    store.init()
    config, version_id = load_and_record_workflow(store, workflow_path)
    return config, version_id, store


def _load_config_if_exists(workflow_path: str) -> WorkflowConfig:
    path = Path(workflow_path)
    if path.exists():
        return load_workflow(path)
    return default_config()


if __name__ == "__main__":
    raise SystemExit(main())
