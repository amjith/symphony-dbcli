from __future__ import annotations

import difflib
import json
import socket
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .clock import elapsed_ms, monotonic_ns, utc_now
from .config import WorkflowConfig, workflow_hash
from .types import AttemptSummary

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IssueSnapshot:
    repo: str
    number: int
    title: str
    url: str
    state: str
    labels: list[str]
    task_type: str
    body: str = ""
    author: str = ""
    updated_at: str = ""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            for statement in SCHEMA:
                conn.execute(statement)
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES('schema_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (str(SCHEMA_VERSION), utc_now()),
            )

    def record_workflow_version(
        self,
        path: str | Path,
        content: str,
        config: WorkflowConfig | None,
        *,
        status: str = "accepted",
        error: str | None = None,
    ) -> int:
        config_json = json.dumps(config.to_dict() if config else {}, sort_keys=True)
        content_hash = workflow_hash(content)
        with self.connect() as conn:
            previous = conn.execute(
                """
                SELECT id, content FROM workflow_versions
                WHERE status = 'accepted'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if status == "accepted":
                existing = conn.execute(
                    "SELECT id FROM workflow_versions WHERE status = 'accepted' AND content_hash = ?",
                    (content_hash,),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            diff = ""
            if previous:
                diff = "\n".join(
                    difflib.unified_diff(
                        str(previous["content"]).splitlines(),
                        content.splitlines(),
                        fromfile=f"workflow:{previous['id']}",
                        tofile="workflow:new",
                        lineterm="",
                    )
                )
            created_at = utc_now()
            cursor = conn.execute(
                """
                INSERT INTO workflow_versions(
                    path, content_hash, content, parsed_config_json, status, error, diff, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(path), content_hash, content, config_json, status, error, diff, created_at),
            )
            version_id = _lastrowid(cursor)
            conn.execute(
                """
                INSERT INTO workflow_reload_events(
                    workflow_version_id, status, error, created_at
                )
                VALUES(?, ?, ?, ?)
                """,
                (version_id, status, error, created_at),
            )
            return version_id

    def latest_workflow_version(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return cast(
                sqlite3.Row | None,
                conn.execute(
                    """
                    SELECT * FROM workflow_versions
                    WHERE status = 'accepted'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone(),
            )

    def workflow_history(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT id, path, content_hash, status, error, created_at
                    FROM workflow_versions
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def upsert_repo(self, full_name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO repos(full_name, created_at, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(full_name) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (full_name, utc_now(), utc_now()),
            )

    def upsert_issue(self, issue: IssueSnapshot) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._upsert_repo_conn(conn, issue.repo)
            conn.execute(
                """
                INSERT INTO issues(
                    repo, number, title, url, state, task_type, body, author,
                    labels_json, github_updated_at, first_seen_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, number) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    state = excluded.state,
                    task_type = excluded.task_type,
                    body = excluded.body,
                    author = excluded.author,
                    labels_json = excluded.labels_json,
                    github_updated_at = excluded.github_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    issue.repo,
                    issue.number,
                    issue.title,
                    issue.url,
                    issue.state,
                    issue.task_type,
                    issue.body,
                    issue.author,
                    json.dumps(issue.labels, sort_keys=True),
                    issue.updated_at,
                    now,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM issue_labels WHERE repo = ? AND issue_number = ?", (issue.repo, issue.number)
            )
            conn.executemany(
                "INSERT INTO issue_labels(repo, issue_number, label) VALUES(?, ?, ?)",
                [(issue.repo, issue.number, label) for label in issue.labels],
            )

    def list_issues(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT repo, number, title, state, task_type, labels_json, url, updated_at
                    FROM issues
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def eligible_issues(self, todo_label: str, blocked_label: str, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT i.*
                    FROM issues i
                    WHERE i.state = 'open'
                      AND EXISTS (
                          SELECT 1 FROM issue_labels l
                          WHERE l.repo = i.repo AND l.issue_number = i.number AND l.label = ?
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM issue_labels l
                          WHERE l.repo = i.repo AND l.issue_number = i.number AND l.label = ?
                      )
                    ORDER BY i.first_seen_at ASC, i.repo ASC, i.number ASC
                    LIMIT ?
                    """,
                    (todo_label, blocked_label, limit),
                )
            )

    def create_attempt(
        self,
        *,
        repo: str,
        issue_number: int,
        task_type: str,
        workflow_version_id: int | None,
        worktree_path: str = "",
        base_repo_path: str = "",
        branch: str = "",
        status: str = "queued",
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO attempts(
                    repo, issue_number, task_type, workflow_version_id, status,
                    base_repo_path, worktree_path, branch, queued_at, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo,
                    issue_number,
                    task_type,
                    workflow_version_id,
                    status,
                    base_repo_path,
                    worktree_path,
                    branch,
                    now,
                    now,
                    now,
                ),
            )
            return _lastrowid(cursor)

    def update_attempt_workspace(
        self,
        attempt_id: int,
        *,
        base_repo_path: str,
        worktree_path: str,
        branch: str,
        commit_sha: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE attempts
                SET base_repo_path = ?, worktree_path = ?, branch = ?, commit_sha = ?, updated_at = ?
                WHERE id = ?
                """,
                (base_repo_path, worktree_path, branch, commit_sha, utc_now(), attempt_id),
            )

    def start_attempt(self, attempt_id: int, worker_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE attempts
                SET status = 'running', worker_id = ?, started_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (worker_id, now, now, attempt_id),
            )
            conn.execute(
                """
                INSERT INTO workers(id, attempt_id, status, hostname, started_at, updated_at)
                VALUES(?, ?, 'running', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    attempt_id = excluded.attempt_id,
                    status = excluded.status,
                    hostname = excluded.hostname,
                    updated_at = excluded.updated_at
                """,
                (worker_id, attempt_id, socket.gethostname(), now, now),
            )

    def finish_attempt(self, attempt_id: int, status: str, outcome: str = "") -> None:
        now = utc_now()
        with self.connect() as conn:
            started = conn.execute("SELECT started_at FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            duration_ms = None
            if started and started["started_at"]:
                duration_ms = self._duration_from_timeline(conn, attempt_id)
            conn.execute(
                """
                UPDATE attempts
                SET status = ?, outcome = ?, completed_at = ?, duration_ms = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, outcome, now, duration_ms, now, attempt_id),
            )
            conn.execute(
                """
                UPDATE workers
                SET status = ?, completed_at = ?, updated_at = ?
                WHERE attempt_id = ?
                """,
                (status, now, now, attempt_id),
            )

    def record_timeline_event(
        self,
        attempt_id: int,
        *,
        phase: str,
        event_type: str,
        message: str = "",
        data: dict[str, Any] | None = None,
        started_monotonic_ns: int | None = None,
        ended_monotonic_ns: int | None = None,
    ) -> int:
        now = utc_now()
        start_ns = started_monotonic_ns or monotonic_ns()
        end_ns = ended_monotonic_ns
        duration = elapsed_ms(start_ns, end_ns) if end_ns is not None else None
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO worker_timeline_events(
                    attempt_id, phase, event_type, message, data_json,
                    started_at, ended_at, started_monotonic_ns, ended_monotonic_ns, duration_ms
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    phase,
                    event_type,
                    message,
                    json.dumps(data or {}, sort_keys=True),
                    now,
                    now if end_ns is not None else None,
                    start_ns,
                    end_ns,
                    duration,
                ),
            )
            conn.execute(
                "UPDATE attempts SET current_phase = ?, updated_at = ? WHERE id = ?",
                (phase, now, attempt_id),
            )
            return _lastrowid(cursor)

    def record_codex_event(
        self,
        attempt_id: int,
        *,
        thread_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO codex_events(attempt_id, thread_id, event_type, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (attempt_id, thread_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
            )
            return _lastrowid(cursor)

    def record_codex_turn(
        self,
        attempt_id: int,
        *,
        thread_id: str,
        turn_index: int,
        status: str,
        model: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        tool_call_count: int = 0,
        started_monotonic_ns: int | None = None,
        ended_monotonic_ns: int | None = None,
    ) -> int:
        now = utc_now()
        start_ns = started_monotonic_ns or monotonic_ns()
        end_ns = ended_monotonic_ns or monotonic_ns()
        duration = elapsed_ms(start_ns, end_ns)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO codex_turns(
                    attempt_id, thread_id, turn_index, status, model,
                    input_tokens, output_tokens, tool_call_count,
                    started_at, ended_at, started_monotonic_ns, ended_monotonic_ns, duration_ms
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    thread_id,
                    turn_index,
                    status,
                    model,
                    input_tokens,
                    output_tokens,
                    tool_call_count,
                    now,
                    now,
                    start_ns,
                    end_ns,
                    duration,
                ),
            )
            self._refresh_attempt_metrics(conn, attempt_id)
            return _lastrowid(cursor)

    def record_error(
        self,
        attempt_id: int,
        *,
        phase: str,
        error_type: str,
        message: str,
        recoverable: bool = False,
        turn_id: int | None = None,
        log_excerpt: str = "",
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO worker_errors(
                    attempt_id, turn_id, phase, error_type, message, recoverable, log_excerpt, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (attempt_id, turn_id, phase, error_type, message, int(recoverable), log_excerpt, utc_now()),
            )
            self._refresh_attempt_metrics(conn, attempt_id)
            return _lastrowid(cursor)

    def record_worker_log(self, attempt_id: int, level: str, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO worker_logs(attempt_id, level, message, created_at) VALUES(?, ?, ?, ?)",
                (attempt_id, level, message, utc_now()),
            )

    def record_pr(self, attempt_id: int, repo: str, number: int, url: str, title: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pull_requests(attempt_id, repo, number, url, title, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, number) DO UPDATE SET
                    attempt_id = excluded.attempt_id,
                    url = excluded.url,
                    title = excluded.title
                """,
                (attempt_id, repo, number, url, title, utc_now()),
            )

    def record_comment(
        self,
        attempt_id: int | None,
        repo: str,
        issue_number: int,
        url: str,
        body: str,
        status: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO comments(attempt_id, repo, issue_number, url, body, status, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (attempt_id, repo, issue_number, url, body, status, utc_now()),
            )

    def dashboard_summary(self) -> dict[str, Any]:
        with self.connect() as conn:
            issue_count = conn.execute("SELECT COUNT(*) AS count FROM issues").fetchone()["count"]
            running = conn.execute(
                "SELECT COUNT(*) AS count FROM attempts WHERE status = 'running'"
            ).fetchone()["count"]
            queued = conn.execute(
                "SELECT COUNT(*) AS count FROM attempts WHERE status = 'queued'"
            ).fetchone()["count"]
            errors = conn.execute("SELECT COUNT(*) AS count FROM worker_errors").fetchone()["count"]
            turns = conn.execute("SELECT COUNT(*) AS count FROM codex_turns").fetchone()["count"]
            attempts = list(
                conn.execute(
                    """
                    SELECT id, repo, issue_number, task_type, status, current_phase,
                           turn_count, error_count, duration_ms, worktree_path, updated_at
                    FROM attempts
                    ORDER BY updated_at DESC
                    LIMIT 20
                    """
                )
            )
            return {
                "issue_count": issue_count,
                "running_attempts": running,
                "queued_attempts": queued,
                "error_count": errors,
                "turn_count": turns,
                "attempts": attempts,
            }

    def attempt_detail(self, attempt_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            if not attempt:
                return None
            return {
                "attempt": attempt,
                "timeline": list(
                    conn.execute(
                        "SELECT * FROM worker_timeline_events WHERE attempt_id = ? ORDER BY id ASC",
                        (attempt_id,),
                    )
                ),
                "turns": list(
                    conn.execute(
                        "SELECT * FROM codex_turns WHERE attempt_id = ? ORDER BY turn_index ASC",
                        (attempt_id,),
                    )
                ),
                "errors": list(
                    conn.execute(
                        "SELECT * FROM worker_errors WHERE attempt_id = ? ORDER BY id ASC", (attempt_id,)
                    )
                ),
                "logs": list(
                    conn.execute(
                        "SELECT * FROM worker_logs WHERE attempt_id = ? ORDER BY id DESC LIMIT 50",
                        (attempt_id,),
                    )
                ),
            }

    def issue_detail(self, repo: str, number: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            issue = conn.execute(
                "SELECT * FROM issues WHERE repo = ? AND number = ?", (repo, number)
            ).fetchone()
            if not issue:
                return None
            attempts = list(
                conn.execute(
                    "SELECT * FROM attempts WHERE repo = ? AND issue_number = ? ORDER BY id DESC",
                    (repo, number),
                )
            )
            return {
                "issue": issue,
                "attempts": attempts,
                "comments": list(
                    conn.execute(
                        "SELECT * FROM comments WHERE repo = ? AND issue_number = ? ORDER BY id DESC",
                        (repo, number),
                    )
                ),
                "labels": list(
                    conn.execute(
                        "SELECT label FROM issue_labels WHERE repo = ? AND issue_number = ? ORDER BY label",
                        (repo, number),
                    )
                ),
            }

    def answerable_attempts(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT id, repo, issue_number, task_type, status, current_phase,
                           duration_ms, codex_duration_ms, turn_count, error_count,
                           workflow_version_id, updated_at
                    FROM attempts
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """
                )
            )

    def attempt_summaries(self, limit: int = 100) -> list[AttemptSummary]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, repo, issue_number, task_type, status, current_phase,
                       duration_ms, codex_duration_ms, turn_count, error_count,
                       workflow_version_id, updated_at
                FROM attempts
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                AttemptSummary(
                    id=int(row["id"]),
                    repo=str(row["repo"]),
                    issue_number=int(row["issue_number"]),
                    task_type=str(row["task_type"]),
                    status=str(row["status"]),
                    current_phase=str(row["current_phase"] or ""),
                    duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
                    codex_duration_ms=int(row["codex_duration_ms"] or 0),
                    turn_count=int(row["turn_count"] or 0),
                    error_count=int(row["error_count"] or 0),
                    workflow_version_id=int(row["workflow_version_id"])
                    if row["workflow_version_id"] is not None
                    else None,
                    updated_at=str(row["updated_at"]),
                )
                for row in rows
            ]

    def _upsert_repo_conn(self, conn: sqlite3.Connection, full_name: str) -> None:
        now = utc_now()
        conn.execute(
            """
            INSERT INTO repos(full_name, created_at, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(full_name) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (full_name, now, now),
        )

    def _refresh_attempt_metrics(self, conn: sqlite3.Connection, attempt_id: int) -> None:
        turn_count = conn.execute(
            "SELECT COUNT(*) AS count FROM codex_turns WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()["count"]
        error_count = conn.execute(
            "SELECT COUNT(*) AS count FROM worker_errors WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()["count"]
        codex_duration = conn.execute(
            "SELECT COALESCE(SUM(duration_ms), 0) AS duration FROM codex_turns WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()["duration"]
        conn.execute(
            """
            UPDATE attempts
            SET turn_count = ?, error_count = ?, codex_duration_ms = ?, updated_at = ?
            WHERE id = ?
            """,
            (turn_count, error_count, codex_duration, utc_now(), attempt_id),
        )

    def _duration_from_timeline(self, conn: sqlite3.Connection, attempt_id: int) -> int | None:
        row = conn.execute(
            """
            SELECT MIN(started_monotonic_ns) AS started, MAX(ended_monotonic_ns) AS ended
            FROM worker_timeline_events
            WHERE attempt_id = ? AND ended_monotonic_ns IS NOT NULL
            """,
            (attempt_id,),
        ).fetchone()
        if not row or row["started"] is None or row["ended"] is None:
            return None
        return elapsed_ms(int(row["started"]), int(row["ended"]))


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return a row id for an insert.")
    return cursor.lastrowid


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repos(
        full_name TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS issues(
        repo TEXT NOT NULL,
        number INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        state TEXT NOT NULL,
        task_type TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        labels_json TEXT NOT NULL,
        github_updated_at TEXT NOT NULL DEFAULT '',
        first_seen_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(repo, number),
        FOREIGN KEY(repo) REFERENCES repos(full_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS issue_labels(
        repo TEXT NOT NULL,
        issue_number INTEGER NOT NULL,
        label TEXT NOT NULL,
        PRIMARY KEY(repo, issue_number, label),
        FOREIGN KEY(repo, issue_number) REFERENCES issues(repo, number) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_versions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        content TEXT NOT NULL,
        parsed_config_json TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT,
        diff TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_reload_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_version_id INTEGER,
        status TEXT NOT NULL,
        error TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(workflow_version_id) REFERENCES workflow_versions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repo TEXT NOT NULL,
        issue_number INTEGER NOT NULL,
        task_type TEXT NOT NULL,
        workflow_version_id INTEGER,
        worker_id TEXT,
        status TEXT NOT NULL,
        outcome TEXT NOT NULL DEFAULT '',
        current_phase TEXT NOT NULL DEFAULT '',
        base_repo_path TEXT NOT NULL DEFAULT '',
        worktree_path TEXT NOT NULL DEFAULT '',
        branch TEXT NOT NULL DEFAULT '',
        commit_sha TEXT NOT NULL DEFAULT '',
        queued_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        duration_ms INTEGER,
        codex_duration_ms INTEGER NOT NULL DEFAULT 0,
        turn_count INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(repo, issue_number) REFERENCES issues(repo, number),
        FOREIGN KEY(workflow_version_id) REFERENCES workflow_versions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workers(
        id TEXT PRIMARY KEY,
        attempt_id INTEGER,
        status TEXT NOT NULL,
        hostname TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_timeline_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        phase TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        data_json TEXT NOT NULL DEFAULT '{}',
        started_at TEXT NOT NULL,
        ended_at TEXT,
        started_monotonic_ns INTEGER NOT NULL,
        ended_monotonic_ns INTEGER,
        duration_ms INTEGER,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codex_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        thread_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codex_turns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        thread_id TEXT NOT NULL,
        turn_index INTEGER NOT NULL,
        status TEXT NOT NULL,
        model TEXT NOT NULL DEFAULT '',
        input_tokens INTEGER,
        output_tokens INTEGER,
        tool_call_count INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        started_monotonic_ns INTEGER NOT NULL,
        ended_monotonic_ns INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_errors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        turn_id INTEGER,
        phase TEXT NOT NULL,
        error_type TEXT NOT NULL,
        message TEXT NOT NULL,
        recoverable INTEGER NOT NULL DEFAULT 0,
        log_excerpt TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
        FOREIGN KEY(turn_id) REFERENCES codex_turns(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pull_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        repo TEXT NOT NULL,
        number INTEGER NOT NULL,
        url TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(repo, number),
        FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER,
        repo TEXT NOT NULL,
        issue_number INTEGER NOT NULL,
        url TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES attempts(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orchestrator_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        data_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ask_threads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]
