from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from fastapi import Request
from fastapi.templating import Jinja2Templates

from symphony_dbcli.config import WorkflowConfig
from symphony_dbcli.db import SessionFactory
from symphony_dbcli.runtime import RuntimeCycleResult, RuntimeStatus
from symphony_dbcli.sources import SourceRepository, SourceSyncClient
from symphony_dbcli.store import Store
from symphony_dbcli.web.runtime_views import RuntimeConfigView
from symphony_dbcli.work_items import WorkItemRepository

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _format_ms(value: object) -> str:
    if value is None:
        return "-"
    ms = int(str(value))
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(round(seconds), 60)
    return f"{minutes}m {remaining}s"


templates.env.filters["ms"] = _format_ms


class WebRuntime(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def run_cycle(self, *, trigger: str = "manual") -> RuntimeCycleResult: ...

    def status(self) -> RuntimeStatus: ...


@dataclass(frozen=True)
class WebAppState:
    config: WorkflowConfig
    store: Store
    session_factory: SessionFactory
    workflow_path: str
    source_sync_client: SourceSyncClient | None = None
    runtime: WebRuntime | None = None


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str


NAV_ITEMS = (
    NavItem("board", "Board", "/board"),
    NavItem("sources", "Sources", "/sources"),
    NavItem("work_items", "Work Items", "/work-items"),
    NavItem("operations", "Operations", "/operations"),
    NavItem("workers", "Workers", "/workers"),
    NavItem("workflow", "Workflow", "/workflow"),
    NavItem("ask", "Ask", "/ask"),
    NavItem("settings", "Settings", "/settings"),
)


def get_app_state(request: Request) -> WebAppState:
    return cast(WebAppState, request.app.state.symphony)


def source_repository(request: Request) -> SourceRepository:
    return SourceRepository(get_app_state(request).session_factory)


def work_item_repository(request: Request) -> WorkItemRepository:
    return WorkItemRepository(get_app_state(request).session_factory)


def page_context(request: Request, *, title: str, active: str) -> dict[str, object]:
    state = get_app_state(request)
    return {
        "request": request,
        "title": title,
        "active": active,
        "nav_items": NAV_ITEMS,
        "runtime": RuntimeConfigView.from_config(state.config),
        "workflow_path": state.workflow_path,
    }
