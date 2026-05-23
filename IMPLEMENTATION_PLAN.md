# Python Symphony for DBCLI on exe.dev

## Summary

Build a Python implementation of the
[OpenAI Symphony spec](https://github.com/openai/symphony/blob/main/SPEC.md)
for `dbcli/pgcli`, `dbcli/mycli`, and `dbcli/litecli`, replacing Linear with
GitHub Issues and using SQLite as durable orchestrator state.

The v1 system runs as a single long-lived exe.dev VM with a private
exe.dev-authenticated dashboard.

Primary v1 capabilities:

- Poll GitHub Issues across the three DBCLI repos.
- Dispatch labeled issues into isolated per-issue workspaces.
- Run Codex App Server over stdio JSON-RPC.
- Support both coding tasks and research/support-answer tasks.
- Persist workers, issue snapshots, attempts, events, comments, PR links,
  token metrics, and dashboard state in SQLite.
- Provide a dashboard plus an "ask Symphony" interface for issue, worker, and
  task status questions.

## Architecture

The implementation should be a Python package in this repository with a CLI
entrypoint named `symphony-dbcli`.

Main subsystems:

- Orchestrator: polls GitHub, reconciles SQLite state, claims work, and launches
  workers.
- GitHub tracker adapter: normalizes GitHub Issues into the Symphony issue model
  and handles labels, comments, branches, and PR metadata.
- SQLite store: durable source of truth for issue snapshots, workers, attempts,
  events, logs, comments, PRs, and dashboard state.
- Workspace manager: creates deterministic per-issue workspaces on the exe.dev
  persistent disk.
- Codex runner: starts `codex app-server` per worker over local stdio JSON-RPC.
- Dashboard web app: shows worker health, queue state, attempts, timelines, and
  issue/worker details.
- Ask interface: answers questions about active tasks and workers from SQLite,
  recent logs, and optionally refreshed GitHub state.

## GitHub Workflow

Use GitHub labels as the workflow source of truth instead of Linear or GitHub
Projects.

Initial labels:

- `symphony:todo`: dispatchable work.
- `symphony:working`: claimed or running.
- `symphony:review`: human review needed, PR ready, or answer comment ready.
- `symphony:blocked`: not dispatchable.
- `symphony:done`: terminal.
- `symphony:type:code`: coding task.
- `symphony:type:research`: research, triage, or support-answer task.

Dispatch rules:

- Only open issues with `symphony:todo` and without `symphony:blocked` are
  eligible.
- Task type comes from the `symphony:type:*` label.
- Candidates are sorted by label-derived priority, creation time, then repo and
  issue number.
- The orchestrator moves claimed issues to `symphony:working`.
- Finished coding tasks move to `symphony:review` with a linked PR.
- Finished research tasks move to `symphony:review` with a drafted or posted
  answer comment.

## Configuration

Repository-owned configuration should live in `WORKFLOW.md`, extended from the
Symphony model with DBCLI-specific settings.

Minimum v1 configuration fields:

- `tracker.kind: github`
- `github.repos: ["dbcli/pgcli", "dbcli/mycli", "dbcli/litecli"]`
- label mappings for active, terminal, blocked, task type, and review states
- per-repo workspace bootstrap hooks
- Codex command/settings pass-through
- dashboard host/port settings
- SQLite database path

The default local configuration should run without credentials for development
where possible, but GitHub writes require a configured GitHub App.

## SQLite Data Model

SQLite is the durable orchestrator database, not a cache.

Initial tables:

- `repos`
- `issues`
- `issue_labels`
- `workers`
- `attempts`
- `codex_events`
- `worker_logs`
- `pull_requests`
- `comments`
- `orchestrator_events`
- `ask_threads`
- `settings`

Database requirements:

- Enable WAL mode.
- Enable foreign keys.
- Store immutable event rows with timestamps.
- Keep current-state columns for fast dashboard queries.
- Persist worker state before launching external processes so restarts can
  reconcile safely.

## Worker Behavior

For coding tasks:

- Clone or update the target repository into a deterministic workspace path.
- Prompt Codex to inspect the issue, implement the fix, run relevant tests, and
  summarize proof of work.
- Create a branch, commit, push, and open or update a PR through the GitHub App.
- Comment on the issue with the PR link and test summary.
- Move the issue to `symphony:review`.

For research/support tasks:

- Load issue context, recent comments, relevant repository docs/code, and any
  configured support context.
- Prompt Codex to draft a concise answer with evidence.
- Either post the answer or store it for review, depending on workflow policy.
- Move the issue to `symphony:review` once the answer is ready.

On restart:

- Reconcile active workers from SQLite.
- Check whether GitHub state changed while the service was down.
- Requeue interrupted eligible work.
- Preserve previous attempts and logs.

## Dashboard

Expose a private dashboard through exe.dev's authenticated HTTPS proxy.

Initial routes:

- `/`: worker health, queue depth, retries, blocked issues, PR-ready tasks, and
  answer-ready tasks.
- `/issues/{repo}/{number}`: issue timeline, worker attempts, Codex events,
  comments, PR links, and current labels.
- `/workers/{id}`: worker status, issue assignment, workspace path, recent logs,
  runtime, and token metrics.
- `/ask`: natural-language questions about current tasks, workers, and issue
  state.

The dashboard should be polished but operational: dense, scannable, and useful
for repeated monitoring rather than a marketing-style page.

## CLI

Initial commands:

- `symphony-dbcli init-db`
- `symphony-dbcli serve`
- `symphony-dbcli poll-once`
- `symphony-dbcli worker run --repo OWNER/REPO --issue NUMBER`
- `symphony-dbcli status`

The CLI should read configuration from `WORKFLOW.md` by default, with explicit
flags for database path, log level, and dry-run mode.

## exe.dev Deployment

Run the v1 service on a single exe.dev VM.

Deployment assumptions:

- SQLite database lives on the persistent VM disk.
- Workspaces live under a persistent path such as `/srv/symphony/workspaces`.
- Dashboard is exposed through exe.dev private HTTPS.
- Codex App Server is launched locally per worker over stdio.
- The Codex WebSocket listener is not exposed remotely.

## Test Plan

Add focused tests for:

- Workflow parsing and validation.
- GitHub label-state mapping.
- Issue normalization.
- Workspace key sanitization.
- Retry/backoff behavior.
- SQLite schema creation and persistence.
- Polling and claiming behavior with mocked GitHub API responses.
- Label transitions, comments, PR recording, and restart reconciliation.
- Codex runner behavior using a fake JSON-RPC app-server process.
- Dashboard pages and `/ask` responses using seeded SQLite fixtures.

Before enabling the three DBCLI repos, run an end-to-end dry run against a test
GitHub repository.

## Assumptions

- Initial scope is exactly `dbcli/pgcli`, `dbcli/mycli`, and `dbcli/litecli`.
- GitHub Issues are the v1 tracker source of truth.
- GitHub Projects are out of scope for v1.
- Linear is out of scope for v1.
- Dashboard access is private through exe.dev authentication.
- GitHub writes use a GitHub App, not a user PAT or persistent `gh` session.
- Merging PRs and destructive repo actions are out of scope for v1.
- Research/support tasks produce reviewed answers before any later automation
  that posts without human review.

## References

- [OpenAI Symphony spec](https://github.com/openai/symphony/blob/main/SPEC.md)
- [OpenAI Symphony announcement](https://openai.com/index/open-source-codex-orchestration-symphony/)
- [Codex App Server docs](https://developers.openai.com/codex/app-server)
- [exe.dev docs](https://exe.dev/docs/all)
- [GitHub Issues REST docs](https://docs.github.com/en/rest/issues/issues)
- [dbcli/pgcli](https://github.com/dbcli/pgcli)
- [dbcli/mycli](https://github.com/dbcli/mycli)
- [dbcli/litecli](https://github.com/dbcli/litecli)
