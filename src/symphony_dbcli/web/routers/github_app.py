from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from symphony_dbcli.web.dependencies import page_context, templates

router = APIRouter(prefix="/github-app", tags=["github app"])


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "") -> Response:
    context = page_context(request, title="GitHub App Created", active="settings")
    context["code"] = code
    context["state"] = state
    return templates.TemplateResponse(
        request=request,
        name="github_app/callback.html",
        context=context,
    )
