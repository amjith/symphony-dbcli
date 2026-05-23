from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TaskType = Literal["code", "research"]
AttemptStatus = Literal["queued", "running", "review", "failed", "blocked", "cancelled", "done"]


@dataclass(frozen=True)
class AttemptSummary:
    id: int
    repo: str
    issue_number: int
    task_type: str
    status: str
    current_phase: str
    duration_ms: int | None
    codex_duration_ms: int
    turn_count: int
    error_count: int
    workflow_version_id: int | None
    updated_at: str

    @property
    def issue_ref(self) -> str:
        return f"{self.repo}#{self.issue_number}"
