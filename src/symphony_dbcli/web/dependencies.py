from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import Request
from fastapi.templating import Jinja2Templates

from symphony_dbcli.config import WorkflowConfig
from symphony_dbcli.dashboard import DashboardRuntime
from symphony_dbcli.db import SessionFactory
from symphony_dbcli.sources import SourceRepository
from symphony_dbcli.store import Store

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@dataclass(frozen=True)
class WebAppState:
    config: WorkflowConfig
    store: Store
    session_factory: SessionFactory
    workflow_path: str


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str


NAV_ITEMS = (
    NavItem("board", "Board", "/board"),
    NavItem("sources", "Sources", "/sources"),
    NavItem("work_items", "Work Items", "/work-items"),
    NavItem("workers", "Workers", "/workers"),
    NavItem("workflow", "Workflow", "/workflow"),
    NavItem("ask", "Ask", "/ask"),
    NavItem("settings", "Settings", "/settings"),
)


def get_app_state(request: Request) -> WebAppState:
    return cast(WebAppState, request.app.state.symphony)


def source_repository(request: Request) -> SourceRepository:
    return SourceRepository(get_app_state(request).session_factory)


def page_context(request: Request, *, title: str, active: str) -> dict[str, object]:
    state = get_app_state(request)
    return {
        "request": request,
        "title": title,
        "active": active,
        "nav_items": NAV_ITEMS,
        "runtime": DashboardRuntime.from_config(state.config),
        "workflow_path": state.workflow_path,
    }
