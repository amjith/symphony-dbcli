from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from starlette.responses import RedirectResponse, Response

from symphony_dbcli.sources import SourceCreate, SourceValidationError
from symphony_dbcli.web.dependencies import page_context, source_repository, templates

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
