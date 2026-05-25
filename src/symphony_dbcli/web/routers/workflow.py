from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from symphony_dbcli.web.dependencies import get_app_state, page_context, templates
from symphony_dbcli.workflow_visualization import WorkflowFlowchartView

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("")
def index(request: Request) -> Response:
    app_state = get_app_state(request)
    workflow = app_state.config.workflow
    pending_gates = app_state.store.pending_workflow_gates(limit=20)
    workflow_history = app_state.store.workflow_history(limit=5)
    state_counts = app_state.store.workflow_state_counts()
    context = page_context(request, title="Workflow", active="workflow")
    context["workflow_chart"] = WorkflowFlowchartView.from_definition(
        workflow,
        state_counts=state_counts,
        orientation="vertical",
    )
    context["state_count"] = len(workflow.states)
    context["transition_count"] = len(workflow.transitions)
    context["automatic_count"] = sum(
        1 for transition in workflow.transitions.values() if transition.trigger == "automatic"
    )
    context["human_gate_count"] = sum(
        1 for transition in workflow.transitions.values() if transition.trigger == "human"
    )
    context["states"] = workflow.states.items()
    context["transitions"] = workflow.transitions.items()
    context["pending_gates"] = pending_gates
    context["workflow_history"] = workflow_history
    return templates.TemplateResponse(
        request=request,
        name="workflow/index.html",
        context=context,
    )


@router.get("/edit")
def edit(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="workflow/edit.html",
        context=page_context(request, title="Workflow Editor", active="workflow"),
    )
