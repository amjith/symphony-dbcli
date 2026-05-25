from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from starlette.responses import RedirectResponse, Response

from symphony_dbcli.github import GitHubClient
from symphony_dbcli.sources import SourceCreate, SourceSyncService, SourceValidationError
from symphony_dbcli.web.dependencies import get_app_state, page_context, source_repository, templates

router = APIRouter(tags=["sources"])


@router.get("/sources")
def index(request: Request) -> Response:
    context = page_context(request, title="Sources", active="sources")
    context["sources"] = source_repository(request).list_sources()
    return templates.TemplateResponse(
        request=request,
        name="sources/index.html",
        context=context,
    )


@router.get("/sources/new")
def new(request: Request) -> Response:
    context = page_context(request, title="Add Source", active="sources")
    context["repo"] = ""
    context["error"] = ""
    return templates.TemplateResponse(
        request=request,
        name="sources/new.html",
        context=context,
    )


@router.post("/sources")
def create(request: Request, repo: Annotated[str, Form()]) -> Response:
    try:
        source_repository(request).create_source(SourceCreate(repo=repo))
    except SourceValidationError as exc:
        context = page_context(request, title="Add Source", active="sources")
        context["repo"] = repo
        context["error"] = str(exc)
        return templates.TemplateResponse(
            request=request,
            name="sources/new.html",
            context=context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse("/sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sources/{source_id}/sync")
def sync(request: Request, source_id: int) -> Response:
    state = get_app_state(request)
    client = state.source_sync_client or GitHubClient(state.config.github)
    service = SourceSyncService(source_repository(request), client)
    try:
        service.sync_source(source_id)
    except SourceValidationError:
        return RedirectResponse("/sources", status_code=status.HTTP_303_SEE_OTHER)
    except RuntimeError:
        return RedirectResponse(
            f"/board?source_id={source_id}&sync=failed", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        f"/board?source_id={source_id}&sync=succeeded", status_code=status.HTTP_303_SEE_OTHER
    )
