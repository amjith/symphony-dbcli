from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from symphony_dbcli.clock import utc_now
from symphony_dbcli.runtime import RuntimeCycleResult
from symphony_dbcli.web.dependencies import WebAppState, get_app_state, page_context, templates
from symphony_dbcli.web.runtime_views import WorkersRuntimeStatusView

router = APIRouter(tags=["workers"])


@router.get("/workers")
def index(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="workers/index.html",
        context=_workers_context(request),
    )


@router.post("/workflow/run-cycle")
def run_cycle(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="workers/index.html",
        context=_workers_context(request, cycle_result=_run_manual_cycle(get_app_state(request))),
    )


def _workers_context(
    request: Request,
    *,
    cycle_result: RuntimeCycleResult | None = None,
) -> dict[str, object]:
    app_state = get_app_state(request)
    context = page_context(request, title="Workers", active="workers")
    runtime_status = app_state.runtime.status() if app_state.runtime is not None else None
    context["runtime_status"] = WorkersRuntimeStatusView.from_runtime(
        app_state.config,
        app_state.store,
        runtime_status,
    )
    context["cycle_result"] = cycle_result
    return context


def _run_manual_cycle(app_state: WebAppState) -> RuntimeCycleResult:
    if app_state.runtime is None:
        return RuntimeCycleResult.skipped_cycle("manual", "runtime_not_attached")
    try:
        return app_state.runtime.run_cycle(trigger="manual")
    except RuntimeError as exc:
        return RuntimeCycleResult.failed("manual", utc_now(), str(exc))
