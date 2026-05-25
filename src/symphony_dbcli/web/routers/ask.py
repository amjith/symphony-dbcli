from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from symphony_dbcli.ask import answer_with_links
from symphony_dbcli.web.dependencies import get_app_state, page_context, templates

router = APIRouter(tags=["ask"])


@router.get("/ask")
def index(request: Request, q: str = "") -> Response:
    context = page_context(request, title="Ask Symphony", active="ask")
    context["question"] = q
    context["answer"] = answer_with_links(get_app_state(request).store, q) if q.strip() else None
    return templates.TemplateResponse(
        request=request,
        name="ask/index.html",
        context=context,
    )
