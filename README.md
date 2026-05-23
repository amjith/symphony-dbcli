# symphony-dbcli

Python implementation of a Symphony-style worker orchestrator for the DBCLI
projects: `dbcli/pgcli`, `dbcli/mycli`, and `dbcli/litecli`.

The project is intentionally lightweight for the first implementation:

- `uv` and `pyproject.toml` for packaging.
- `WORKFLOW.md` with a fenced TOML configuration block.
- SQLite for durable state, workflow version history, and worker metrics.
- GitHub Issues as the tracker.
- Git worktrees for parallel per-issue coding workers.
- A stdlib-powered dashboard for status and operational questions.

## Quick Start

```bash
uv run symphony-dbcli init-workflow
uv run symphony-dbcli init-db
uv run symphony-dbcli status
uv run symphony-dbcli serve
```

The default workflow is safe for local development. GitHub writes require
credentials before workers can comment, label issues, or open pull requests.

## Development

```bash
uv sync --dev
uv run pre-commit install
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```
